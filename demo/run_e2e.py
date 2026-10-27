#!/usr/bin/env python
"""端到端演示：用真实数据把八步链完整跑一遍（检索 → 脚本 → 数值 → 引用 → 落账 → 审计）。

真实数据（都在 demo/data/，可离线复现）
----------------------------------------
1. `rfc8785.txt` —— 从 https://www.rfc-editor.org/rfc/rfc8785.txt 实际下载的 RFC 8785 正文
   （41,879 bytes，UTF-8 BOM）；`RETRIEVAL.json` 记录 URL / DOI / 取回时间 / 字节哈希。
   它既是「检索」这一步的产物，也是步 6 的一手快照（verification=primary）。
2. `git-log.tsv` —— 本仓库真实历史 `git log --numstat --format='commit %H %aI'` 导出
   （11 次提交、102 行）；脚本对它做描述统计，统计结果作为步 4/5 的数值产物。

八步链的每一步在这里都是**真实触发**的：
  步 0 rail（六道门）→ 步 1 schema → 步 2 执行溯源/事件链 → 步 3 数据上下文传递性
  → 步 4 脚本与产物 hash 绑定/计划绑定 → 步 5 值定位与比对 → 步 6 引用一致性
  → 步 7 偏差标注 → 步 8 幂等落账 + WAL；随后做双源对账（audit）与崩溃恢复（recover）。

除正例之外，脚本对每一步都构造一个**只用真实数据改一处**的负例，断言它被对应的冻结错误码拒绝，
且拒绝后账本行数不变（「拒绝不产生痕迹」）。

用法：`python demo/run_e2e.py`（可选 `--keep` 保留上一次的 store）。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import jcs  # noqa: E402  (tools/jcs.py)
from m1 import Ledger  # noqa: E402
from m1.ledger import (  # noqa: E402
    LedgerError,
    SimulatedCrash,
    sha256_bytes,
    sha256_file,
)
from m1.manifest import Entry, Manifest, ManifestError, RunContext  # noqa: E402
from m1 import rails  # noqa: E402

DATA = ROOT / "demo" / "data"
OUT = ROOT / "demo" / "out"
STORE = ROOT / "demo" / ".store"
RPC = DATA / "rfc8785.txt"
GITLOG = DATA / "git-log.tsv"
STATS_SCRIPT = ROOT / "demo" / "scripts" / "git_commit_stats.py"
STATS_OUT = OUT / "git_commit_stats.json"

RUN_ID = "run_demo-e2e-01"
MANIFEST_VERSION = "MANIFEST#2026-10-27"
VENUE = "vp-2026.10"
T0 = 1_790_000_000.0  # 固定的逻辑时钟：同样的输入重跑得到同样的行

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")

CHECKS = 0
FAILED: list[str] = []


def ok(cond: bool, label: str) -> None:
    """记录一项检查（失败继续跑，最后汇总）。"""
    global CHECKS
    CHECKS += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILED.append(label)


def hx12(subject: str) -> str:
    return jcs.digest16(subject)[:12]


def hx16(subject: str) -> str:
    return jcs.digest16(subject)


def stage(n: int, title: str) -> None:
    print(f"\n[{n}/8] {title}")


def card(
    claim_type: str,
    text: str,
    *,
    evidence: dict | None = None,
    citation_refs: list | None = None,
    framing_ref: dict | None = None,
    confidence: str = "confirmatory",
    role: str = "analyst",
    tag: str = "",
    **lineage_extra,
) -> dict:
    """造一张 ClaimCard 1.4.0（字段严格按冻结 schema）。"""
    body = {
        "claim_id": "clm_" + hx16(f"{claim_type}|{text}|{tag}"),
        "claim_type": claim_type,
        "claim_text": text,
        "status": "active",
        "confidence": confidence,
        "lineage": {
            "created_by_role": role,
            "credential_kind": "rail",
            "created_at": "2026-10-27T14:00:00Z",
            "run_id": RUN_ID,
            **lineage_extra,
        },
    }
    if evidence is not None:
        body["evidence"] = evidence
    if citation_refs is not None:
        body["citation_refs"] = citation_refs
    if framing_ref is not None:
        body["framing_ref"] = framing_ref
    return body


def expect_code(label: str, code: str, fn) -> None:
    """执行 fn，断言它以指定冻结码失败；成功则不通过。"""
    try:
        fn()
    except (LedgerError, ManifestError) as exc:
        got = getattr(exc, "code", "")
        ok(got == code, f"{label} → {code}" + ("" if got == code else f"（实际 {got}）"))
        return
    except Exception as exc:  # noqa: BLE001 - 演示脚本需要把意外异常暴露成失败
        ok(False, f"{label} → {code}（实际异常 {type(exc).__name__}: {exc}）")
        return
    ok(False, f"{label} → {code}（实际未拒绝）")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="八步链真实数据端到端演示")
    ap.add_argument("--keep", action="store_true", help="保留已有 store（默认清空重建）")
    args = ap.parse_args(argv)

    for path in (RPC, GITLOG, STATS_SCRIPT):
        if not path.exists():
            print(f"缺少输入：{path}", file=sys.stderr)
            return 2
    if not args.keep and STORE.exists():
        shutil.rmtree(STORE)
    OUT.mkdir(parents=True, exist_ok=True)

    ledger = Ledger(STORE)
    print(f"账本根目录：{STORE}")

    # ------------------------------------------------------------------ #
    # 1. 检索：下载的 RFC 正文 + 真实 git 历史
    # ------------------------------------------------------------------ #
    stage(1, "检索（retrieval）：一手文献快照 + 本轮数据")
    retrieval = json.loads((DATA / "RETRIEVAL.json").read_text(encoding="utf-8"))
    rfc_text = RPC.read_text(encoding="utf-8-sig")
    rfc_bytes = RPC.read_bytes()
    ok(sha256_bytes(rfc_bytes) == retrieval["sha256"], "RFC 正文与 RETRIEVAL.json 记录的字节哈希一致")
    snapshot_ref = ledger.store_snapshot(rfc_text)
    ok(snapshot_ref == "sha256:" + __import__("hashlib").sha256(rfc_text.encode("utf-8")).hexdigest(),
       f"正文快照入库（snapshot_ref={snapshot_ref[:23]}…）")

    data_bytes = GITLOG.read_bytes()
    data_hash = sha256_bytes(data_bytes)
    lit_entry = Entry(
        entry_id="mfe_" + hx12(retrieval["doi"]),
        kind="literature",
        doi=retrieval["doi"],
        role="backbone",
        snapshot_ref=snapshot_ref,
        locators=("sec 3.2", "sec 3.2.2.3", "sec 3.2.3", "Table 1"),
        license="IETF-Trust-BCP78",
        provenance={"url": retrieval["url"], "retrieved_at": retrieval["retrieved_at"],
                    "http_status": retrieval["http_status"], "bytes": retrieval["bytes"]},
    )
    data_entry = Entry(
        entry_id="mfe_" + hx12("git-log.tsv"),
        kind="data",
        sha256=data_hash,
        provenance={"query_path_ref": "git log --numstat --format='commit %H %aI' --output=demo/data/git-log.tsv",
                    "retriever_version": "git 2.56.0.windows.2",
                    "rows": sum(1 for ln in data_bytes.decode("utf-8").splitlines() if ln)},
    )
    manifest = Manifest(MANIFEST_VERSION, entries=[lit_entry, data_entry])
    run_context = RunContext(run_id=RUN_ID, manifest_version=MANIFEST_VERSION,
                             run_context_ref="ctx_demo_e2e", manifest=manifest,
                             venue_profile_version=VENUE)
    rail_context = rails.RailContext(now=T0, allowed_claim_types=("result", "context"),
                                     forbidden_licenses=("proprietary",), human_approver="hesheng4")
    n_commits = sum(1 for ln in data_bytes.decode("utf-8").splitlines() if ln.startswith("commit "))
    print(f"  文献：{retrieval['title']}（DOI {retrieval['doi']}，{retrieval['bytes']} bytes）")
    print(f"  数据：git-log.tsv（{data_hash[:23]}…，{len(data_bytes)} bytes，{n_commits} 次提交）")
    ok(n_commits == 11, f"数据文件真实包含 {n_commits} 次提交记录")

    # ------------------------------------------------------------------ #
    # 2. 脚本：登记为内容寻址对象，并登记计划（步 4 的 plan_ref）
    # ------------------------------------------------------------------ #
    stage(2, "脚本（execution）：脚本入库 + PlanItem 登记 + 执行编号")
    script_bytes = STATS_SCRIPT.read_bytes()
    script_hash = ledger.store_script(script_bytes)
    plan_ref = "pln_" + hx12("PLAN-GIT-COMMIT-STATS|v1")
    ledger.register_plan(plan_ref, script_hash)
    execution_id = "exec_" + hx16(f"{script_hash}|{data_hash}")
    ok(ledger.script_path(script_hash).exists(), f"脚本以内容寻址入库（script_hash={script_hash[:23]}…）")
    ok(sha256_file(ledger.script_path(script_hash)) == script_hash, "脚本库中的字节重算后与 script_hash 相符")

    started = time.time()
    proc = subprocess.run([sys.executable, str(STATS_SCRIPT),
                           "--data", str(GITLOG), "--out", str(STATS_OUT)])  # 不捕获管道（沙箱限制）
    ok(proc.returncode == 0, f"脚本真实执行成功（{time.time() - started:.2f}s，退出码 {proc.returncode}）")
    ledger.record_execution(execution_id, status="completed", audit_status="available", now=T0 + 1)
    ledger.verify_event_chain()
    ok(True, f"执行 {execution_id} 已登记，事件链验算通过（事件数 {len(ledger.raw_events())}）")

    # ------------------------------------------------------------------ #
    # 3. 产物与数值
    # ------------------------------------------------------------------ #
    stage(3, "数值（artifact）：产物入库 + 读数")
    artifact_bytes = STATS_OUT.read_bytes()
    artifact_hash = ledger.store_artifact(artifact_bytes)
    stats = json.loads(artifact_bytes.decode("utf-8"))
    print(f"  产物：n_commits={stats['n_commits']} total_added={stats['total_added']} "
          f"total_deleted={stats['total_deleted']} median={stats['lines_per_commit_median']}")
    ok(artifact_hash == sha256_bytes(artifact_bytes), "产物入库哈希与字节一致")
    ok(stats["source"]["sha256"] == data_hash, "产物内记录的输入哈希 == 本轮 MANIFEST 数据条目哈希")

    # ------------------------------------------------------------------ #
    # 4+5+6. 组装 result / context 卡（引用来自真实 RFC）
    # ------------------------------------------------------------------ #
    stage(4, "绑定（步 4）：脚本/产物 hash + 计划绑定")
    stage(5, "取值（步 5）：按 RFC 6901 指针定位并比对")
    stage(6, "引用（步 6）：DOI + 档位 + locator + 一手快照")

    result_card = card(
        "result",
        f"真实仓库 {stats['n_commits']} 次提交的改动行数中位数是 {stats['lines_per_commit_median']} 行",
        evidence={
            "sandbox_execution_id": execution_id,
            "script_hash": script_hash,
            "plan_ref": plan_ref,
            "data_refs": [{"data_hash": data_hash, "manifest_entry_id": data_entry.entry_id}],
            "output_hashes": [artifact_hash],
            "values": [
                {"output_index": 0, "pointer": "/n_commits",
                 "value": stats["n_commits"], "comparison": "exact"},
                {"output_index": 0, "pointer": "/lines_per_commit_median",
                 "value": stats["lines_per_commit_median"], "comparison": "float_rel",
                 "tolerance": 1e-9, "unit": "行"},
            ],
        },
    )
    citation = {
        "doi": retrieval["doi"],
        "manifest_entry_id": lit_entry.entry_id,
        "verification": "primary",
        "locator": "sec 3.2.2.3",
        "snapshot_ref": snapshot_ref,
    }
    context_card = card(
        "context",
        "RFC 8785 §3.2.2.3 规定 JSON 数字的规范序列化形式（如 1e-7 序列化为 1e-7）",
        citation_refs=[citation],
        role="librarian",
    )
    print(f"  result  卡 claim_id={result_card['claim_id']}（2 个 value 指针）")
    print(f"  context 卡 claim_id={context_card['claim_id']}（primary 引用 + 正文快照）")

    # ------------------------------------------------------------------ #
    # 7. 落账
    # ------------------------------------------------------------------ #
    stage(7, "写入账本（步 0–8：rail → schema → 执行 → 上下文 → 绑定 → 取值 → 引用 → 偏差 → 落账）")
    rows_before = len(ledger.rows())
    r1 = ledger.append(result_card, manifest=manifest, run_context=run_context,
                       venue_profile_version=VENUE, now=T0 + 2, context=rail_context)
    r2 = ledger.append(context_card, manifest=manifest, run_context=run_context,
                       venue_profile_version=VENUE, now=T0 + 3, context=rail_context)
    ok(r1.appended and r1.row_seq == 1, f"result 卡落账（row_id={r1.row_id[:16]}…，row_seq=1）")
    ok(r2.appended and r2.row_seq == 2, f"context 卡落账（row_id={r2.row_id[:16]}…，row_seq=2）")
    ok(len(ledger.rows()) == rows_before + 2, "账本行数 +2")
    ok(len(list(ledger.wal_dir.glob('*.json'))) == 0, "WAL 已清理（无悬挂事务）")

    # 幂等：同一张卡再落一次
    r1b = ledger.append(result_card, manifest=manifest, run_context=run_context,
                        venue_profile_version=VENUE, now=T0 + 4, context=rail_context)
    ok(r1b.duplicate and not r1b.appended and r1b.row_id == r1.row_id, "同卡重复 append → 幂等短路（duplicate=True）")

    # ------------------------------------------------------------------ #
    # 8. 审计与篡改检测
    # ------------------------------------------------------------------ #
    stage(8, "审计（audit）：双源对账 + 篡改/中断/缺失检测 + 恢复")
    report = ledger.audit()
    ok(report.ok and report.rows == 2, f"正常账本审计通过（rows={report.rows}，findings={len(report.findings)}）")
    replay_ids = [r["card"]["claim_id"] for r in ledger.replay()]
    ok(replay_ids == [result_card["claim_id"], context_card["claim_id"]],
       "只读重放按 row_seq 顺序还原两行稳定投影（row_id/row_seq 等易变字段已剔除）")

    claims_file = ledger.claims_path
    rawlog_file = ledger.rawlog_path
    claims_bak = claims_file.read_bytes()
    rawlog_bak = rawlog_file.read_bytes()

    # (a) 改写账本行 → TAMPER_DETECTED
    rows = [json.loads(ln) for ln in claims_bak.decode("utf-8").splitlines() if ln.strip()]
    rows[0]["card"]["claim_text"] += "（被篡改）"
    claims_file.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                           encoding="utf-8")
    codes = [f["code"] for f in ledger.audit().findings]
    ok("TAMPER_DETECTED" in codes, f"改写账本行 → TAMPER_DETECTED（{len(codes)} 条 findings）")
    claims_file.write_bytes(claims_bak)

    # (b) 删掉 rawlog 中的一条 claim 事件 → PHANTOM_EVENT
    events = [json.loads(ln) for ln in rawlog_bak.decode("utf-8").splitlines() if ln.strip()]
    keep = [e for e in events if e.get("event_type") != "claim.append"]
    rawlog_file.write_text("".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in keep),
                           encoding="utf-8")
    codes = [f["code"] for f in ledger.audit().findings]
    ok("PHANTOM_EVENT" in codes, f"删除 rawlog 事件 → PHANTOM_EVENT（{len(codes)} 条 findings）")
    rawlog_file.write_bytes(rawlog_bak)

    # (c) 产物文件被删 → ARTIFACT_MISSING
    art_path = ledger.artifact_path(artifact_hash)
    art_bak = art_path.read_bytes()
    art_path.unlink()
    codes = [f["code"] for f in ledger.audit().findings]
    ok("ARTIFACT_MISSING" in codes, "删除产物副本 → ARTIFACT_MISSING")
    art_path.write_bytes(art_bak)
    ok(ledger.audit().ok, "恢复后审计重新通过")

    # (d) 崩溃注入：rawlog 写完、账本未写 → UNCOMMITTED_EVENT → recover 回滚
    crash_card = card("result", "崩溃注入实验：rawlog 已写、账本未写（应被回滚）",
                      evidence=copy.deepcopy(result_card["evidence"]), tag="crash-rawlog")
    try:
        ledger.append(crash_card, manifest=manifest, run_context=run_context,
                      venue_profile_version=VENUE, now=T0 + 5, context=rail_context,
                      crash_after="rawlog")
    except SimulatedCrash:
        pass
    codes = [f["code"] for f in ledger.audit().findings]
    ok("UNCOMMITTED_EVENT" in codes, f"崩溃注入（rawlog 后）→ UNCOMMITTED_EVENT（{len(codes)} 条 findings）")
    rec = ledger.recover()
    ok(rec["rolled_back"] == 1, f"recover() 回滚悬挂事务（{rec}）")
    ok(ledger.audit().ok and len(ledger.rows()) == 2, "回滚后审计通过、账本仍为 2 行")

    # (e) 崩溃注入：账本已写、WAL 未清 → recover 补完
    crash_card2 = card("result", "崩溃注入实验：账本已写、WAL 未清（应被补完）",
                       evidence=copy.deepcopy(result_card["evidence"]), tag="crash-ledger")
    try:
        ledger.append(crash_card2, manifest=manifest, run_context=run_context,
                      venue_profile_version=VENUE, now=T0 + 6, context=rail_context,
                      crash_after="ledger")
    except SimulatedCrash:
        pass
    ok(len(ledger.rows()) == 3, "账本已提交（3 行），WAL 仍悬挂")
    rec = ledger.recover()
    ok(rec["finished"] + rec["cleaned"] == 1, f"recover() 收尾悬挂 WAL（{rec}）")
    ok(ledger.audit().ok, "收尾后审计通过")

    # ------------------------------------------------------------------ #
    # 负例：每一步都用一个「只改真实数据一处」的卡片触发它的错误码
    # ------------------------------------------------------------------ #
    print("\n[负例] 逐步触发冻结错误码（每次拒绝后账本行数不变）")
    base_rows = len(ledger.rows())

    def attempt(c, *, context=None, run_context_=None):
        return ledger.append(c, manifest=manifest, run_context=run_context_ or run_context,
                            venue_profile_version=VENUE, now=T0 + 10, context=context or rail_context)

    # 步 1：schema（claim_text 太短 / 未登记角色）
    bad = card("result", "短", evidence=copy.deepcopy(result_card["evidence"]), tag="b1")
    expect_code("步1 非法 claim_text", "SCHEMA_FAIL", lambda: attempt(bad))
    bad = card("result", "角色词汇未登记（owner 已废除）", evidence=copy.deepcopy(result_card["evidence"]),
               role="owner", tag="b1b")
    expect_code("步1 未登记角色 owner", "SCHEMA_FAIL", lambda: attempt(bad))

    # 步 2：执行未登记 / 执行被拒
    ev = copy.deepcopy(result_card["evidence"])
    ev["sandbox_execution_id"] = "exec_" + "0" * 16
    expect_code("步2 未登记执行编号", "EXEC_UNRESOLVED",
                lambda: attempt(card("result", "执行编号不存在的声明（应被拒绝）", evidence=ev, tag="b2")))
    rejected_exec = "exec_" + hx16("rejected-execution")
    ledger.record_execution(rejected_exec, status="rejected", audit_status="available", now=T0 + 7)
    ev = copy.deepcopy(result_card["evidence"])
    ev["sandbox_execution_id"] = rejected_exec
    expect_code("步2 执行已被拒", "EXEC_REJECTED",
                lambda: attempt(card("result", "执行状态为 rejected 的声明（应被拒绝）", evidence=ev, tag="b2b")))

    # 步 3：数据哈希漂移 / 文献条目冒充数据
    ev = copy.deepcopy(result_card["evidence"])
    ev["data_refs"] = [{"data_hash": "sha256:" + "1" * 64, "manifest_entry_id": data_entry.entry_id}]
    expect_code("步3 数据哈希漂移", "TRANSPORTIVITY_FAIL",
                lambda: attempt(card("result", "引用旧数据集哈希的声明（应被拒绝）", evidence=ev, tag="b3")))
    ev = copy.deepcopy(result_card["evidence"])
    ev["data_refs"] = [{"data_hash": data_hash, "manifest_entry_id": lit_entry.entry_id}]
    expect_code("步3 文献条目冒充数据条目", "MANIFEST_CONTEXT_MISMATCH",
                lambda: attempt(card("result", "把文献条目当数据源的声明（应被拒绝）", evidence=ev, tag="b3b")))

    # 步 4：产物哈希不符 / 产物缺失 / 计划未登记 / 计划不符
    ev = copy.deepcopy(result_card["evidence"])
    ev["output_hashes"] = ["sha256:" + "2" * 64]
    expect_code("步4 产物哈希不符", "ARTIFACT_UNREACHABLE",
                lambda: attempt(card("result", "声称的产物哈希不存在的声明（应被拒绝）", evidence=ev, tag="b4")))
    ev = copy.deepcopy(result_card["evidence"])
    ev["plan_ref"] = "pln_" + hx12("PLAN-NOT-REGISTERED")
    expect_code("步4 计划未登记", "PLAN_UNBOUND",
                lambda: attempt(card("result", "计划未登记的声明（应被拒绝）", evidence=ev, tag="b4b")))
    other_plan = "pln_" + hx12("PLAN-OTHER-SCRIPT")
    ledger.register_plan(other_plan, "sha256:" + "3" * 64)
    ev = copy.deepcopy(result_card["evidence"])
    ev["plan_ref"] = other_plan
    expect_code("步4 脚本与计划不符", "PLAN_MISMATCH",
                lambda: attempt(card("result", "脚本哈希与计划不符的声明（应被拒绝）", evidence=ev, tag="b4c")))

    # 步 5：数值不符 / 输出索引越界 / 指针定位失败
    ev = copy.deepcopy(result_card["evidence"])
    ev["values"] = [{"output_index": 0, "pointer": "/n_commits", "value": 999, "comparison": "exact"}]
    expect_code("步5 声明数值与产物不符", "VALUE_LOCATOR_FAIL",
                lambda: attempt(card("result", "声称 999 次提交的声明（应被拒绝）", evidence=ev, tag="b5")))
    ev = copy.deepcopy(result_card["evidence"])
    ev["values"] = [{"output_index": 1, "pointer": "/n_commits", "value": 11, "comparison": "exact"}]
    expect_code("步5 输出索引越界", "OUTPUT_INDEX_OUT_OF_RANGE",
                lambda: attempt(card("result", "输出索引越界的声明（应被拒绝）", evidence=ev, tag="b5b")))
    ev = copy.deepcopy(result_card["evidence"])
    ev["values"] = [{"output_index": 0, "pointer": "/no_such_field", "value": 1, "comparison": "exact"}]
    expect_code("步5 指针指向不存在的字段", "VALUE_LOCATOR_FAIL",
                lambda: attempt(card("result", "指针不存在的声明（应被拒绝）", evidence=ev, tag="b5c")))

    # 步 6：DOI 不在 MANIFEST / locator 不可解析 / 快照缺失 / 档位不符
    if True:
        c = card("context", "引用一篇不在本轮 MANIFEST 的文献（应被拒绝）",
                 citation_refs=[{**citation, "doi": "10.9999/not-in-manifest"}], tag="b6")
        expect_code("步6 DOI 不在 MANIFEST", "DOI_NOT_IN_MANIFEST", lambda: attempt(c))
        c = card("context", "locator 不在该条目的可解析白名单（应被拒绝）",
                 citation_refs=[{**citation, "locator": "sec 9.9"}], tag="b6b")
        expect_code("步6 locator 不可解析", "CITATION_LOCATOR_FAIL", lambda: attempt(c))
        c = card("context", "primary 引用的快照不在快照库（应被拒绝）",
                 citation_refs=[{**citation, "snapshot_ref": "sha256:" + "4" * 64}], tag="b6c")
        expect_code("步6 快照缺失", "SNAPSHOT_MISSING", lambda: attempt(c))
        c = card("context", "survey_transfer 指向 supporting 条目（应被拒绝）",
                 citation_refs=[{**citation, "verification": "survey_transfer",
                                 "survey_doi": retrieval["doi"],
                                 "snapshot_ref": snapshot_ref}] , tag="b6d")
        # survey 是自己（backbone）→ 合法；改用 supporting 条目触发档位违规
        supporting = Entry(entry_id="mfe_" + hx12("10.17487/support"), kind="literature",
                           doi="10.17487/support", role="supporting", locators=("p.9",),
                           license="IETF-Trust-BCP78")
        manifest.add(supporting)
        ledger.snapshots.put("支持性材料正文（演示用）")
        c = card("context", "survey_transfer 指向 supporting 条目（应被拒绝）",
                 citation_refs=[{**citation, "verification": "survey_transfer",
                                 "survey_doi": "10.17487/support",
                                 "snapshot_ref": snapshot_ref}], tag="b6d2")
        expect_code("步6 综述转述挂 supporting 条目", "BACKBONE_GRADE_VIOLATION", lambda: attempt(c))

    # 步 7：exploratory 未标偏差
    ev = copy.deepcopy(result_card["evidence"])
    c = card("result", "探索性声明未写偏差说明（应被拒绝）", evidence=ev,
             confidence="exploratory", tag="b7")
    expect_code("步7 探索性声明缺偏差说明", "DEVIATION_UNNOTED", lambda: attempt(c))

    # 步 0：rail 拦截（策略码，不属于八步链错误码）
    c = card("context", "引用许可被禁用的文献（rail 应拦截）",
             citation_refs=[copy.deepcopy(citation)], tag="b0")
    expect_code("rail Compliance 禁用许可", "COMPLIANCE_LICENSE_FORBIDDEN",
                lambda: attempt(c, context=rails.RailContext(now=T0, forbidden_licenses=("IETF-Trust-BCP78",))))
    c = card("context", "本轮不允许产出 context 类声明（rail 应拦截）",
             citation_refs=[copy.deepcopy(citation)], tag="b0b")
    expect_code("rail InferenceScope 超范围", "INFERENCE_SCOPE_OUT_OF_SCOPE",
                lambda: attempt(c, context=rails.RailContext(now=T0, allowed_claim_types=("result",))))
    c = card("result", "预算耗尽后仍尝试落账（rail 应拦截）",
             evidence=copy.deepcopy(result_card["evidence"]), tag="b0c")
    expect_code("rail Budget 超预算", "BUDGET_EXCEEDED",
                lambda: attempt(c, context=rails.RailContext(now=T0, budget_tokens=10, spent_tokens=11)))

    ok(len(ledger.rows()) == base_rows, f"所有负例被拒绝且未留下账本行（保持 {base_rows} 行）")

    # 引用类正例（supplementary：确认正例仍可通过）
    print("\n[汇总]")
    report = ledger.audit()
    ok(report.ok, f"终态审计通过（rows={report.rows}，findings={len(report.findings)}）")
    summary = {
        "checks": CHECKS,
        "failed": FAILED,
        "rows": report.rows,
        "audit_ok": report.ok,
        "replay": ledger.replay(),
        "retrieval": retrieval,
        "data": {"path": str(GITLOG.name), "sha256": data_hash, "commits": n_commits},
        "script_hash": script_hash,
        "artifact_hash": artifact_hash,
        "execution_id": execution_id,
        "result_row": r1.row_id,
        "context_row": r2.row_id,
        "stats": stats,
    }
    (OUT / "e2e-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")

    if FAILED:
        print(f"E2E 演示：{len(FAILED)}/{CHECKS} 项失败 → 见上方 FAIL 行")
        return 1
    print(f"E2E 演示：全绿（{CHECKS} 项检查；账本 {report.rows} 行；产物 {OUT / 'e2e-summary.json'}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
