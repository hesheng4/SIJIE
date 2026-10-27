"""M1 最小闭环行为验收（门禁 GATE 6）。

落账对象是真实 **ClaimRow 1.2.0**（内嵌 ClaimCard 1.4.0），因此本套验收既覆盖运行时承诺，
也覆盖八步链的 **步 1（schema）** 与 **步 4 的 hash 绑定子集**：

A. row_id 派生与行级幂等 —— 同内容重复 append 只落一行；易变字段不影响 id；内容变则 id 变。
B. hash 绑定            —— 脚本/产物哈希不符或缺失一律拒绝，且失败不落任何痕迹。
C. WAL 双写与崩溃恢复    —— rawlog 后崩溃可回滚（pending）、可补齐（rawlog_done）。
D. 双源对账             —— 链式哈希、序号连续、账本↔rawlog 双射、产物仍在，篡改可被点名。
E. 重放确定性           —— 重新打开账本后 row_id 可从稳定投影重派生、顺序确定。
F. 步 1 schema 校验      —— 四类卡正例全过；result 缺 values / framing 带 evidence / 首行终态 /
                          未登记角色 / 非法 audit_event_id / schema 版本不符 全部 SCHEMA_FAIL。

全部使用真实临时目录，不 mock。用法：`python tools/m1_acceptance.py`
退出码 0 全绿 / 1 有失败 / 2 依赖缺失。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # pragma: no cover
        pass

try:
    from m1.ledger import (  # noqa: E402
        CLAIMCARD_VERSION,
        ArtifactUnreachable,
        HashMismatch,
        Ledger,
        SchemaFail,
        SimulatedCrash,
        chain_digest,
        derive_row_id,
        stable_projection,
        validate_card,
        validate_row,
    )
except Exception as exc:  # pragma: no cover
    print(f"m1_acceptance: 依赖缺失（{exc}）→ exit 2")
    raise SystemExit(2)

CHECKS = 0
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


# --------------------------------------------------------------------------- #
# 夹具：真实 ClaimCard 1.4.0（形状对齐 schemas/ 与 validate_freeze.py G2 段）
# --------------------------------------------------------------------------- #
H16 = "a1b2c3d4e5f60718"
MFE = "mfe_0f1e2d3c4b5a"
PLN = "pln_0f1e2d3c4b5a"
EXEC = "exec_" + H16
LINEAGE = {
    "created_by_role": "analyst",
    "credential_kind": "rail",
    "created_at": "2026-10-25T00:00:00Z",
    "run_id": "run_m1accept01",
}


def cid(n: int) -> str:
    return "clm_" + f"{n:016x}"


def _text(t: str) -> str:
    """claim_text 有 minLength=8 约束，短夹具统一补齐，避免负例因长度误判。"""
    return t if len(t) >= 8 else t + "（验收夹具文本）"


def _evidence(script_hash: str, artifact_hash: str) -> dict:
    return {
        "sandbox_execution_id": EXEC,
        "script_hash": script_hash,
        "plan_ref": PLN,
        "data_refs": [{"data_hash": artifact_hash, "manifest_entry_id": MFE}],
        "output_hashes": [artifact_hash],
        "values": [{"output_index": 0, "pointer": "/mean", "value": 0.42,
                    "comparison": "float_rel", "tolerance": 1e-9}],
    }


def result_card(claim_id: str, script_hash: str, artifact_hash: str, text: str) -> dict:
    return {
        "claim_id": claim_id, "claim_type": "result", "claim_text": _text(text),
        "status": "active", "confidence": "confirmatory",
        "evidence": _evidence(script_hash, artifact_hash),
        "lineage": dict(LINEAGE),
    }


def method_card(claim_id: str, script_hash: str, text: str) -> dict:
    ev = _evidence(script_hash, "sha256:" + "00" * 32)
    del ev["values"]
    del ev["data_refs"]
    return {
        "claim_id": claim_id, "claim_type": "method", "claim_text": _text(text),
        "status": "active", "confidence": "confirmatory",
        "evidence": ev, "lineage": dict(LINEAGE),
    }


def context_card(claim_id: str, artifact_hash: str, text: str) -> dict:
    return {
        "claim_id": claim_id, "claim_type": "context", "claim_text": _text(text),
        "status": "active", "confidence": "confirmatory",
        "citation_refs": [{"doi": "10.1234/abc", "manifest_entry_id": MFE,
                           "verification": "primary", "locator": "p.12",
                           "snapshot_ref": artifact_hash}],
        "lineage": dict(LINEAGE),
    }


def framing_card(claim_id: str, text: str) -> dict:
    return {
        "claim_id": claim_id, "claim_type": "framing", "claim_text": _text(text),
        "status": "active", "confidence": "confirmatory",
        "framing_ref": {"survey_doi": "10.1234/survey", "manifest_entry_id": MFE,
                        "locator": "sec 3"},
        "lineage": dict(LINEAGE),
    }


def make_result(ledger: Ledger, *, claim_id: str, text: str,
                artifact_bytes: bytes = b"result: 0.42\n",
                script_bytes: bytes = b"print(0.42)\n",
                break_script_hash: bool = False,
                missing_artifact: bool = False) -> dict:
    """真实落盘脚本与产物（内容寻址），再组装 result 卡。"""
    script_hash = ledger.store_script(script_bytes)
    artifact_hash = ledger.store_artifact(artifact_bytes)
    if break_script_hash:
        ledger.script_path(script_hash).write_bytes(b"print(9.99)\n")  # 落盘后被改
    if missing_artifact:
        artifact_hash = "sha256:" + "11" * 32
    return result_card(claim_id, script_hash, artifact_hash, text)


def code_of(fn) -> str:
    try:
        fn()
        return "NO-RAISE"
    except (SchemaFail, HashMismatch, ArtifactUnreachable) as exc:
        return exc.code


def stub(card: dict) -> dict:
    return {"claimcard_schema_version": CLAIMCARD_VERSION, "card": card,
            "manifest_version": "MANIFEST#0", "venue_profile_version": "vp-2026.10"}


print("==== M1 最小闭环行为验收（ClaimRow 1.2.0 / ClaimCard 1.4.0）====\n")

# --------------------------------------------------------------------------- #
# A. row_id 派生与行级幂等
# --------------------------------------------------------------------------- #
print("-- A. row_id 派生与行级幂等 --")
with tempfile.TemporaryDirectory(prefix="m1-a-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    card = make_result(ledger, claim_id=cid(1), text="样本均值大于 0")

    rid1 = derive_row_id(stub(card))
    rid2 = derive_row_id(stub(json.loads(json.dumps(card))))
    check("A1 同内容两次派生 row_id 相同", rid1 == rid2, f"{rid1} vs {rid2}")
    check("A2 row_id 形如 row_+16 位十六进制", rid1.startswith("row_") and len(rid1) == 20, rid1)

    changed = json.loads(json.dumps(card))
    changed["claim_text"] = "样本均值大于 1"
    check("A3 内容变化 → row_id 变化", derive_row_id(stub(changed)) != rid1)

    decorated = json.loads(json.dumps(stub(card)))
    decorated.update({"row_id": rid1, "appended_at": "2026-10-25T00:00:00Z",
                      "audit_event_id": "evt_" + "ab" * 8, "row_seq": 9,
                      "prev_row_hash": "sha256:" + "cd" * 32,
                      "row_hash": "sha256:" + "ef" * 32})
    check("A4 易变字段（row_id/row_seq/时间/事件id/前后链哈希）不影响 row_id",
          derive_row_id(decorated) == rid1)

    res1 = ledger.append(card, now=1000.0)
    check("A5 首次 append 真实落账（row_seq=1）",
          res1.appended and not res1.duplicate and res1.row_seq == 1, str(res1))
    check("A6 账本与 rawlog 各 1 条",
          len(ledger.rows()) == 1 and len(ledger.raw_events()) == 1,
          f"rows={len(ledger.rows())} events={len(ledger.raw_events())}")

    res2 = ledger.append(card, now=2000.0)
    check("A7 重复 append 命中幂等键（row_id 相同、不新增）",
          res2.duplicate and not res2.appended and res2.row_id == rid1, str(res2))
    check("A8 幂等 append 不新增账本行与 rawlog 事件",
          len(ledger.rows()) == 1 and len(ledger.raw_events()) == 1,
          f"rows={len(ledger.rows())} events={len(ledger.raw_events())}")

# --------------------------------------------------------------------------- #
# B. hash 绑定（失败不落痕迹）
# --------------------------------------------------------------------------- #
print("\n-- B. hash 绑定与失败原子性 --")
with tempfile.TemporaryDirectory(prefix="m1-b-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")

    bad_script = make_result(ledger, claim_id=cid(2), text="脚本落盘后被改写后落账",
                             break_script_hash=True)
    check("B1 脚本落盘后被改 → HASH_MISMATCH",
          code_of(lambda: ledger.append(bad_script)) == "HASH_MISMATCH")

    no_art = make_result(ledger, claim_id=cid(3), text="产物未入库不可达", missing_artifact=True)
    check("B2 产物未入库 → ARTIFACT_UNREACHABLE",
          code_of(lambda: ledger.append(no_art)) == "ARTIFACT_UNREACHABLE")

    no_script_card = method_card(cid(4), "sha256:" + "22" * 32, "脚本未入库不可达")
    check("B3 脚本未入库 → ARTIFACT_UNREACHABLE",
          code_of(lambda: ledger.append(no_script_card)) == "ARTIFACT_UNREACHABLE")

    good = make_result(ledger, claim_id=cid(5), text="产物被篡改后重存")
    ledger.artifact_path(good["evidence"]["output_hashes"][0]).write_bytes(b"result: 9.99\n")
    ledger.store_artifact(b"result: 0.42\n")  # 内容寻址：同内容重存即自愈
    check("B4 产物被篡改后重新入库 → 哈希自洽、可落账", code_of(lambda: ledger.append(good)) == "NO-RAISE")

    before_rows, before_events = len(ledger.rows()), len(ledger.raw_events())
    code_of(lambda: ledger.append(make_result(ledger, claim_id=cid(6), text="该条必须被拒绝落账",
                                              missing_artifact=True)))
    check("B5 校验失败不落账：账本与 rawlog 计数不变、WAL 为空",
          len(ledger.rows()) == before_rows and len(ledger.raw_events()) == before_events
          and not list(ledger.wal_dir.glob("*.json")),
          f"rows={len(ledger.rows())}/{before_rows} events={len(ledger.raw_events())}/{before_events}")

# --------------------------------------------------------------------------- #
# C. WAL 双写与崩溃恢复
# --------------------------------------------------------------------------- #
print("\n-- C. WAL 先行与崩溃恢复 --")
with tempfile.TemporaryDirectory(prefix="m1-c1-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    card = make_result(ledger, claim_id=cid(7), text="rawlog 后崩溃")
    crashed = False
    try:
        ledger.append(card, crash_after="rawlog")
    except SimulatedCrash:
        crashed = True
    check("C1 在 rawlog 之后崩溃被捕获", crashed)
    check("C2 崩溃后账本为空、rawlog 1 条、WAL 为 pending",
          len(ledger.rows()) == 0 and len(ledger.raw_events()) == 1
          and len(list(ledger.wal_dir.glob("*.json"))) == 1,
          f"rows={len(ledger.rows())} events={len(ledger.raw_events())}")

    stats = ledger.recover()
    check("C3 pending 事务被回滚（账本 0 行、rawlog 0 条、WAL 清空）",
          stats["rolled_back"] == 1 and len(ledger.rows()) == 0
          and len(ledger.raw_events()) == 0 and not list(ledger.wal_dir.glob("*.json")),
          str(stats))
    check("C4 回滚后对账全绿（空账本）", ledger.audit().ok)

with tempfile.TemporaryDirectory(prefix="m1-c2-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    card = make_result(ledger, claim_id=cid(8), text="rawlog 已确认后崩溃")
    try:
        ledger.append(card, crash_after="rawlog")
    except SimulatedCrash:
        pass
    wal = next(ledger.wal_dir.glob("*.json"))
    txn = json.loads(wal.read_text(encoding="utf-8"))
    txn["stage"] = "rawlog_done"
    wal.write_text(json.dumps(txn, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    stats = ledger.recover()
    check("C5 rawlog_done 事务被补齐（账本 1 行、WAL 清空）",
          stats["finished"] == 1 and len(ledger.rows()) == 1
          and not list(ledger.wal_dir.glob("*.json")), str(stats))
    check("C6 补齐后对账全绿", ledger.audit().ok, str(ledger.audit().codes))

    again = ledger.append(card)
    check("C7 恢复后重复 append 仍幂等（不产生第二行）",
          again.duplicate and len(ledger.rows()) == 1, str(again))

with tempfile.TemporaryDirectory(prefix="m1-c3-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    card = make_result(ledger, claim_id=cid(9), text="账本已写、WAL 未清")
    try:
        ledger.append(card, crash_after="ledger")
    except SimulatedCrash:
        pass
    check("C8 账本已写而 WAL 未清时，数据可见且对账全绿",
          len(ledger.rows()) == 1 and ledger.audit().ok)
    ledger.recover()
    check("C9 该事务的 WAL 被识别为可完成并清理（不重复写行）",
          len(ledger.rows()) == 1 and not list(ledger.wal_dir.glob("*.json")))

# --------------------------------------------------------------------------- #
# D. 双源对账（篡改可被点名）
# --------------------------------------------------------------------------- #
print("\n-- D. 双源对账 --")
with tempfile.TemporaryDirectory(prefix="m1-d-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    ledger.append(make_result(ledger, claim_id=cid(10), text="第一条声明"), now=1000.0)
    ledger.append(make_result(ledger, claim_id=cid(11), text="第二条声明"), now=1001.0)

    rows = ledger.rows()
    check("D1 两行 row_seq 连续且链式哈希衔接",
          rows[0]["row_seq"] == 1 and rows[1]["row_seq"] == 2
          and rows[1]["prev_row_hash"] == rows[0]["row_hash"]
          and rows[1]["row_hash"] == chain_digest(rows[1]))
    check("D2 正常账本对账全绿", ledger.audit().ok, str(ledger.audit().codes))

    tampered = [dict(r) for r in rows]
    tampered[0]["card"] = json.loads(json.dumps(tampered[0]["card"]))
    tampered[0]["card"]["claim_text"] = "被改过的结论"  # 改内嵌 ClaimCard
    ledger.claims_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in tampered),
        encoding="utf-8")
    report = ledger.audit()
    check("D3 账本内嵌 ClaimCard 被改 → TAMPER_DETECTED",
          "TAMPER_DETECTED" in report.codes, str(report.codes))

with tempfile.TemporaryDirectory(prefix="m1-d2-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    ledger.append(make_result(ledger, claim_id=cid(12), text="删除rawlog事件"))
    ledger.rawlog_path.write_text("", encoding="utf-8")
    report = ledger.audit()
    check("D4 账本有条目而 rawlog 无事件 → PHANTOM_EVENT",
          "PHANTOM_EVENT" in report.codes, str(report.codes))

with tempfile.TemporaryDirectory(prefix="m1-d3-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    ledger.append(make_result(ledger, claim_id=cid(13), text="多出一条事件"))
    with open(ledger.rawlog_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event_type": "claim.append", "row_id": "row_" + "ff" * 8,
                             "claim_id": cid(99), "recorded_at": 1.0},
                            sort_keys=True) + "\n")
    report = ledger.audit()
    check("D5 rawlog 有事件而账本无行 → UNCOMMITTED_EVENT",
          "UNCOMMITTED_EVENT" in report.codes, str(report.codes))

with tempfile.TemporaryDirectory(prefix="m1-d4-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    card = make_result(ledger, claim_id=cid(14), text="产物被删除")
    ledger.append(card)
    ledger.artifact_path(card["evidence"]["output_hashes"][0]).unlink()
    report = ledger.audit()
    check("D6 产物被删 → ARTIFACT_MISSING", "ARTIFACT_MISSING" in report.codes, str(report.codes))

# --------------------------------------------------------------------------- #
# E. 重放确定性
# --------------------------------------------------------------------------- #
print("\n-- E. 重放确定性 --")
with tempfile.TemporaryDirectory(prefix="m1-e-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    card = make_result(ledger, claim_id=cid(15), text="重放确定性一号")
    ledger.append(card)

    reopened = Ledger(tmp / "store")
    rows = reopened.rows()
    check("E1 重新打开账本后 row_id 可从稳定投影重新派生",
          derive_row_id(rows[0]) == rows[0]["row_id"])
    projection = reopened.replay()[0]
    check("E2 重放投影不含易变字段",
          not (set(projection) & {"row_id", "row_seq", "appended_at", "audit_event_id",
                                  "prev_row_hash", "row_hash"}),
          str(sorted(projection)))
    check("E3 稳定投影与落账前 stub 一致", projection == stub(card))

    ledger.append(make_result(ledger, claim_id=cid(16), text="重放确定性二号"))
    check("E4 两行重放顺序按 row_seq 且确定性可复现",
          [p["card"]["claim_id"] for p in reopened.replay()] == [cid(15), cid(16)])

# --------------------------------------------------------------------------- #
# F. 步 1 schema 校验（八步链第 1 步）
# --------------------------------------------------------------------------- #
print("\n-- F. 步 1 schema 校验（八步链第 1 步）--")
with tempfile.TemporaryDirectory(prefix="m1-f-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    r_script = ledger.store_script(b"print(1)\n")
    r_art = ledger.store_artifact(b"1\n")

    four_ok = [result_card(cid(20), r_script, r_art, "结果类声明卡片"),
               method_card(cid(21), r_script, "方法类声明卡片"),
               context_card(cid(22), r_art, "背景类声明卡片"),
               framing_card(cid(23), "框架类声明卡片")]
    check("F1 四类卡（result/method/context/framing）正例全部通过 schema",
          all(code_of(lambda c=c: validate_card(c)) == "NO-RAISE" for c in four_ok))

    no_values = json.loads(json.dumps(four_ok[0]))
    del no_values["evidence"]["values"]
    check("F2 result 卡缺 values → SCHEMA_FAIL",
          code_of(lambda: validate_card(no_values)) == "SCHEMA_FAIL")

    framing_ev = json.loads(json.dumps(four_ok[3]))
    framing_ev["evidence"] = json.loads(json.dumps(four_ok[1]["evidence"]))
    check("F3 framing 卡带 evidence → SCHEMA_FAIL",
          code_of(lambda: validate_card(framing_ev)) == "SCHEMA_FAIL")

    first_superseded = json.loads(json.dumps(four_ok[1]))
    first_superseded["status"] = "superseded"  # 无 transition 只允许 active
    check("F4 首行 status=superseded（无 transition）→ SCHEMA_FAIL",
          code_of(lambda: validate_card(first_superseded)) == "SCHEMA_FAIL")

    bad_role = json.loads(json.dumps(four_ok[1]))
    bad_role["lineage"]["created_by_role"] = "reviewer"  # 未登记角色（词表为 reviewer-1/2/3）
    check("F5 未登记角色 reviewer → SCHEMA_FAIL",
          code_of(lambda: validate_card(bad_role)) == "SCHEMA_FAIL")

    ledger.append(four_ok[0], now=3000.0)
    row = ledger.rows()[0]

    bad_event = json.loads(json.dumps(row))
    bad_event["audit_event_id"] = "evt_zz"
    check("F6 行 audit_event_id 不合 ^evt_[a-f0-9]{16}$ → SCHEMA_FAIL",
          code_of(lambda: validate_row(bad_event)) == "SCHEMA_FAIL")

    bad_ver = json.loads(json.dumps(row))
    bad_ver["claimcard_schema_version"] = "1.3.0"
    check("F7 行 claimcard_schema_version 不符 const → SCHEMA_FAIL",
          code_of(lambda: validate_row(bad_ver)) == "SCHEMA_FAIL")

    before = len(ledger.rows())
    code_of(lambda: ledger.append(no_values))
    code_of(lambda: ledger.append(first_superseded))
    check("F8 schema 失败的卡不落账（账本行数不变、无 WAL）",
          len(ledger.rows()) == before and not list(ledger.wal_dir.glob("*.json")),
          f"rows={len(ledger.rows())}/{before}")

# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
print()
if FAILURES:
    print(f"M1 行为验收：{len(FAILURES)}/{CHECKS} 项失败 → 不可发布")
    for name in FAILURES:
        print(f"  - {name}")
    raise SystemExit(1)
print(f"M1 行为验收：全绿（{CHECKS} 项断言；"
      "A 幂等 / B hash / C WAL / D 对账 / E 重放 / F 步1 schema）")
raise SystemExit(0)
