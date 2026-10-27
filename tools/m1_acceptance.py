"""M1 最小闭环行为验收（门禁 GATE 6）。

覆盖 `m1/ledger.py` 的四条承诺，全部用真实文件系统（临时目录）验证，不 mock：

A. 行级幂等  —— 同一内容重复 append 只落一行、只记一条 rawlog 事件；内容变则 row_id 变。
B. hash 绑定  —— 脚本哈希 / 产物哈希不符或缺失一律拒绝，且失败不落任何痕迹。
C. WAL 双写   —— 在 rawlog 之后、账本之前崩溃，重启可回滚（pending）或补齐（rawlog_done）。
D. 双源对账   —— 链式哈希、序号连续、账本↔rawlog 一一对应、产物仍在，篡改可被点名。

用法：python tools/m1_acceptance.py   → 退出码 0 全绿 / 1 有失败 / 2 依赖缺失
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
        ArtifactUnreachable,
        HashMismatch,
        Ledger,
        SimulatedCrash,
        chain_digest,
        derive_row_id,
        sha256_bytes,
        stable_projection,
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


EXE = "exe_" + "0f1e2d3c4b5a6071"


def make_record(ledger: Ledger, tmp: Path, *, claim_id: str, statement: str,
                artifact_bytes: bytes = b"result: 0.42\n", script_bytes: bytes = b"print(0.42)\n",
                break_script_hash: bool = False, missing_artifact: bool = False) -> dict:
    """造一条最小声明：脚本文件 + 产物（内容寻址）+ 绑定哈希。"""
    scripts = tmp / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    spath = scripts / f"{claim_id}.py"
    spath.write_bytes(script_bytes)
    sdigest = sha256_bytes(script_bytes)
    if break_script_hash:
        sdigest = "sha256:" + "00" * 32
    adigest = ledger.store_artifact(artifact_bytes)
    if missing_artifact:
        adigest = "sha256:" + "11" * 32
    return {
        "claim_id": claim_id,
        "statement": statement,
        "script": {"path": str(spath), "sha256": sdigest},
        "evidence": {
            "artifact_sha256": adigest,
            "data_refs": ["mfe_0f1e2d3c4b5a"],
            "values": [0.42],
        },
        "execution": {"execution_id": EXE, "plan_ref": "pln_0f1e2d3c4b5a"},
    }


print("==== M1 最小闭环行为验收 ====\n")

# --------------------------------------------------------------------------- #
# A. row_id 派生与幂等
# --------------------------------------------------------------------------- #
print("-- A. row_id 派生与行级幂等 --")
with tempfile.TemporaryDirectory(prefix="m1-a-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    rec = make_record(ledger, tmp, claim_id="clm_a", statement="样本均值大于 0")

    rid1 = derive_row_id(rec)
    rid2 = derive_row_id(json.loads(json.dumps(rec)))
    check("A1 同内容两次派生 row_id 相同", rid1 == rid2, f"{rid1} vs {rid2}")
    check("A2 row_id 形如 row_+16 位十六进制", rid1.startswith("row_") and len(rid1) == 20, rid1)

    changed = json.loads(json.dumps(rec))
    changed["statement"] = "样本均值大于 1"
    check("A3 内容变化 → row_id 变化", derive_row_id(changed) != rid1)

    decorated = json.loads(json.dumps(rec))
    decorated.update({"appended_at": 1.0, "audit_event_id": "evt_" + "ab" * 8, "row_seq": 9})
    check("A4 易变字段（appended_at/audit_event_id/row_seq）不影响 row_id",
          derive_row_id(decorated) == rid1)

    res1 = ledger.append(rec, now=1000.0)
    check("A5 首次 append 真实落账", res1.appended and not res1.duplicate and res1.row_seq == 1,
          str(res1))
    check("A6 账本与 rawlog 各 1 条", len(ledger.rows()) == 1 and len(ledger.raw_events()) == 1,
          f"rows={len(ledger.rows())} events={len(ledger.raw_events())}")

    res2 = ledger.append(rec, now=2000.0)
    check("A7 重复 append 命中幂等键（不新增行）",
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

    bad_script = make_record(ledger, tmp, claim_id="clm_b1", statement="脚本被改", break_script_hash=True)
    try:
        ledger.append(bad_script)
        code = "NO-RAISE"
    except HashMismatch as exc:
        code = exc.code
    check("B1 脚本哈希不符 → HASH_MISMATCH", code == "HASH_MISMATCH", code)

    no_art = make_record(ledger, tmp, claim_id="clm_b2", statement="产物不在", missing_artifact=True)
    try:
        ledger.append(no_art)
        code = "NO-RAISE"
    except ArtifactUnreachable as exc:
        code = exc.code
    check("B2 产物缺失 → ARTIFACT_UNREACHABLE", code == "ARTIFACT_UNREACHABLE", code)

    rec = make_record(ledger, tmp, claim_id="clm_b3", statement="先落一条")
    ledger.append(rec)
    tampered = json.loads(json.dumps(rec))
    apath = ledger.artifact_path(tampered["evidence"]["artifact_sha256"])
    apath.write_bytes(b"result: 9.99\n")  # 落账后产物被改
    new = make_record(ledger, tmp, claim_id="clm_b4", statement="产物被篡改后新建卡",
                      artifact_bytes=b"result: 0.42\n")
    try:
        ledger.append(new)
        check("B3 产物库按内容寻址：同内容重新 store 后哈希自洽、可落账", True)
    except Exception as exc:  # pragma: no cover
        check("B3 产物库按内容寻址：同内容重新 store 后哈希自洽、可落账", False, type(exc).__name__)

    before_rows, before_events = len(ledger.rows()), len(ledger.raw_events())
    try:
        ledger.append(make_record(ledger, tmp, claim_id="clm_b5", statement="该条必须被拒",
                                  missing_artifact=True))
    except ArtifactUnreachable:
        pass
    check("B4 校验失败不落账：账本与 rawlog 计数不变、WAL 为空",
          len(ledger.rows()) == before_rows and len(ledger.raw_events()) == before_events
          and not list(ledger.wal_dir.glob("*.json")),
          f"rows={len(ledger.rows())}/{before_rows} events={len(ledger.raw_events())}/{before_events} "
          f"wal={len(list(ledger.wal_dir.glob('*.json')))}")

# --------------------------------------------------------------------------- #
# C. WAL 双写与崩溃恢复
# --------------------------------------------------------------------------- #
print("\n-- C. WAL 先行与崩溃恢复 --")
with tempfile.TemporaryDirectory(prefix="m1-c1-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    rec = make_record(ledger, tmp, claim_id="clm_c1", statement="rawlog 后崩溃")
    try:
        ledger.append(rec, crash_after="rawlog")
        crashed = False
    except SimulatedCrash:
        crashed = True
    check("C1 在 rawlog 之后崩溃被捕获", crashed)
    check("C2 崩溃后账本为空、WAL 为 pending",
          len(ledger.rows()) == 0 and len(list(ledger.wal_dir.glob("*.json"))) == 1,
          f"rows={len(ledger.rows())} wal={len(list(ledger.wal_dir.glob('*.json')))}")

    stats = ledger.recover()
    check("C3 pending 事务被回滚（账本 0 行、rawlog 0 条、WAL 清空）",
          stats["rolled_back"] == 1 and len(ledger.rows()) == 0
          and len(ledger.raw_events()) == 0 and not list(ledger.wal_dir.glob("*.json")),
          str(stats))
    check("C4 回滚后对账全绿（空账本）", ledger.audit().ok)

with tempfile.TemporaryDirectory(prefix="m1-c2-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    rec = make_record(ledger, tmp, claim_id="clm_c2", statement="rawlog 已确认后崩溃")
    try:
        ledger.append(rec, crash_after="rawlog")
    except SimulatedCrash:
        pass
    # 模拟「WAL 已推进到 rawlog_done，账本尚未写」的崩溃点
    wal = next(ledger.wal_dir.glob("*.json"))
    txn = json.loads(wal.read_text(encoding="utf-8"))
    txn["stage"] = "rawlog_done"
    wal.write_text(json.dumps(txn, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    stats = ledger.recover()
    check("C5 rawlog_done 事务被补齐（账本 1 行、WAL 清空）",
          stats["finished"] == 1 and len(ledger.rows()) == 1
          and not list(ledger.wal_dir.glob("*.json")), str(stats))
    check("C6 补齐后对账全绿", ledger.audit().ok, str(ledger.audit().codes))

    again = ledger.append(rec)
    check("C7 恢复后重复 append 仍幂等（不产生第二行）",
          again.duplicate and len(ledger.rows()) == 1, str(again))

with tempfile.TemporaryDirectory(prefix="m1-c3-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    rec = make_record(ledger, tmp, claim_id="clm_c3", statement="账本已写、WAL 未清")
    try:
        ledger.append(rec, crash_after="ledger")
    except SimulatedCrash:
        pass
    check("C8 账本已写而 WAL 未清时，数据本身已可见且对账全绿",
          len(ledger.rows()) == 1 and ledger.audit().ok)
    stats = ledger.recover()
    check("C9 该事务的 WAL 被识别为可完成并清理（不重复写行）",
          len(ledger.rows()) == 1 and not list(ledger.wal_dir.glob("*.json")), str(stats))

# --------------------------------------------------------------------------- #
# D. 双源对账（篡改可被点名）
# --------------------------------------------------------------------------- #
print("\n-- D. 双源对账 --")
with tempfile.TemporaryDirectory(prefix="m1-d-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    r1 = make_record(ledger, tmp, claim_id="clm_d1", statement="第一条")
    r2 = make_record(ledger, tmp, claim_id="clm_d2", statement="第二条")
    ledger.append(r1, now=1000.0)
    ledger.append(r2, now=1001.0)

    rows = ledger.rows()
    check("D1 两行 row_seq 连续且链式哈希衔接",
          rows[0]["row_seq"] == 1 and rows[1]["row_seq"] == 2
          and rows[1]["prev_row_hash"] == rows[0]["row_hash"]
          and rows[1]["row_hash"] == chain_digest(rows[1]))
    check("D2 正常账本对账全绿", ledger.audit().ok, str(ledger.audit().codes))

    # D3 篡改账本内容
    tampered = [dict(r) for r in rows]
    tampered[0]["statement"] = "被改过的结论"
    ledger.claims_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in tampered),
        encoding="utf-8")
    report = ledger.audit()
    check("D3 账本内容被改 → TAMPER_DETECTED", "TAMPER_DETECTED" in report.codes, str(report.codes))

with tempfile.TemporaryDirectory(prefix="m1-d2-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    rec = make_record(ledger, tmp, claim_id="clm_d3", statement="删事件")
    ledger.append(rec)
    ledger.rawlog_path.write_text("", encoding="utf-8")
    report = ledger.audit()
    check("D4 账本有条目而 rawlog 无事件 → PHANTOM_EVENT", "PHANTOM_EVENT" in report.codes,
          str(report.codes))

with tempfile.TemporaryDirectory(prefix="m1-d3-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    rec = make_record(ledger, tmp, claim_id="clm_d4", statement="多出事件")
    ledger.append(rec)
    with open(ledger.rawlog_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event_type": "claim.append", "row_id": "row_" + "ff" * 8,
                             "claim_id": "clm_x", "recorded_at": 1.0}, sort_keys=True) + "\n")
    report = ledger.audit()
    check("D5 rawlog 有事件而账本无行 → UNCOMMITTED_EVENT", "UNCOMMITTED_EVENT" in report.codes,
          str(report.codes))

with tempfile.TemporaryDirectory(prefix="m1-d4-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    rec = make_record(ledger, tmp, claim_id="clm_d5", statement="产物被删")
    ledger.append(rec)
    ledger.artifact_path(rec["evidence"]["artifact_sha256"]).unlink()
    report = ledger.audit()
    check("D6 产物被删 → ARTIFACT_MISSING", "ARTIFACT_MISSING" in report.codes, str(report.codes))

# --------------------------------------------------------------------------- #
# E. 重放确定性
# --------------------------------------------------------------------------- #
print("\n-- E. 重放确定性 --")
with tempfile.TemporaryDirectory(prefix="m1-e-") as td:
    tmp = Path(td)
    ledger = Ledger(tmp / "store")
    rec = make_record(ledger, tmp, claim_id="clm_e", statement="重放")
    ledger.append(rec)

    reopened = Ledger(tmp / "store")
    rows = reopened.rows()
    check("E1 重新打开账本后 row_id 可从稳定投影重新派生",
          derive_row_id(rows[0]) == rows[0]["row_id"])
    projection = reopened.replay()[0]
    check("E2 重放投影不含易变字段",
          not (set(projection) & {"appended_at", "audit_event_id", "row_seq",
                                  "prev_row_hash", "row_hash"}),
          str(sorted(projection)))
    check("E3 稳定投影与落账前记录一致", projection == stable_projection(rec))

    other = make_record(ledger, tmp, claim_id="clm_e2", statement="重放二号")
    ledger.append(other)
    check("E4 两行重放顺序按 row_seq 且确定性可复现",
          [p["claim_id"] for p in reopened.replay()] == ["clm_e", "clm_e2"])

# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
print()
if FAILURES:
    print(f"M1 行为验收：{len(FAILURES)}/{CHECKS} 项失败 → 不可发布")
    for name in FAILURES:
        print(f"  - {name}")
    raise SystemExit(1)
print(f"M1 行为验收：全绿（{CHECKS} 项断言；A 幂等 / B hash / C WAL / D 对账 / E 重放）")
raise SystemExit(0)
