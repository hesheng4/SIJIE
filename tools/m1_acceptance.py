"""M1 最小闭环行为验收 v3（门禁 GATE 6）：八步校验链 + 事件签发 + 六道 rail 集成。

落账对象是真实 **ClaimRow 1.2.0**（内嵌 ClaimCard 1.4.0），夹具带**真实 MANIFEST / RunContext /
执行登记 / 正文快照**，因此每一步都测「会被拒绝」而不仅是「能跑通」：

A. row_id 派生与行级幂等        —— 稳定投影、易变字段、重复 append。
B. 步 1 schema 校验             —— 四类卡正例 + 6 类 schema 负例（含 1.4.0 新规则）。
C. 步 2 执行溯源与事件链        —— 未登记 / 拒斥 / 审计不可用 / 断链 / 改写 / 冒签 / checkpoint。
D. 步 3 MANIFEST 上下文         —— 哈希传递性、条目类型、RunContext 版本一致、缺 manifest。
E. 步 4 hash 绑定               —— 脚本/产物库重算、figure、PlanItem 未登记与错配。
F. 步 5 数值定位                —— JSON pointer / CSV 列 / 容差 / 越界 / 不符。
G. 步 6 引用一致性              —— DOI 归属、locator 白名单、primary 快照、backbone 档位。
H. 步 7 偏差标注                —— exploratory 必须带 deviation_note。
I. 步 8 落账与签发              —— row_seq 冲突、audit_event_id 签发性与确定性、WAL 恢复。
J. 六道 rail 集成               —— 六条决策、拦截即不落账、放行即落账。

全部使用真实临时目录，不 mock。用法：`python tools/m1_acceptance.py`
退出码 0 全绿 / 1 有失败 / 2 依赖缺失。
"""

from __future__ import annotations

import json
import re
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
        Ledger,
        LedgerError,
        SimulatedCrash,
        chain_digest,
        derive_row_id,
        stable_projection,
        validate_card,
        validate_row,
    )
    from m1.manifest import Entry, Manifest, ManifestError, RunContext  # noqa: E402
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


def code_of(fn) -> str:
    """执行 fn，返回其抛出的冻结错误码（无异常返回 NO-RAISE）。"""
    try:
        fn()
        return "NO-RAISE"
    except LedgerError as exc:
        return exc.code
    except ManifestError as exc:
        return exc.code


# --------------------------------------------------------------------------- #
# 夹具：真实 ClaimCard 1.4.0 + MANIFEST + RunContext + 执行登记 + 快照
# --------------------------------------------------------------------------- #
H16 = "a1b2c3d4e5f60718"
EXEC = "exec_" + H16
DATA_ENTRY = "mfe_0f1e2d3c4b5a"
LIT_PRIMARY = "mfe_1a2b3c4d5e6f"
LIT_SURVEY = "mfe_2b3c4d5e6f70"
LIT_SUPPORT = "mfe_3c4d5e6f7081"
PLN = "pln_0f1e2d3c4b5a"
DOI_PRIMARY = "10.1234/abc"
DOI_SURVEY = "10.1234/survey"
DOI_SUPPORT = "10.1234/marginal"
LINEAGE = {
    "created_by_role": "analyst",
    "credential_kind": "rail",
    "created_at": "2026-10-25T00:00:00Z",
    "run_id": "run_m1accept01",
}
ARTIFACT_JSON = b'{"mean": 0.42, "n": 30}'
SCRIPT_BYTES = b"print('mean=0.42')\n"
SNAPSHOT_TEXT = "原文快照：样本均值 0.42（表 2，p.12）"


def cid(n: int) -> str:
    return "clm_" + f"{n:016x}"


def _text(t: str) -> str:
    """claim_text 有 minLength=8 约束，短夹具统一补齐，避免负例因长度误判。"""
    return t if len(t) >= 8 else t + "（验收夹具文本）"


class Fixture:
    """一套自洽的落账上下文（每个测试组一个临时目录）。"""

    def __init__(self, root: Path) -> None:
        self.ledger = Ledger(root / "store")
        self.script_hash = self.ledger.store_script(SCRIPT_BYTES)
        self.artifact_hash = self.ledger.store_artifact(ARTIFACT_JSON)
        self.snapshot = self.ledger.store_snapshot(SNAPSHOT_TEXT)
        self.ledger.register_plan(PLN, self.script_hash)
        self.ledger.record_execution(EXEC, status="completed", audit_status="available", now=900.0)
        self.manifest = Manifest("MANIFEST#7", entries=[
            Entry(DATA_ENTRY, "data", sha256=self.artifact_hash),
            Entry(LIT_PRIMARY, "literature", doi=DOI_PRIMARY, role="backbone",
                  snapshot_ref=self.snapshot, locators=("p.12", "sec 3"), license="cc-by"),
            Entry(LIT_SURVEY, "literature", doi=DOI_SURVEY, role="backbone", locators=("sec 1",)),
            Entry(LIT_SUPPORT, "literature", doi=DOI_SUPPORT, role="supporting", locators=("p.9",)),
        ])
        self.context = RunContext("run_m1accept01", "MANIFEST#7", "runctx_m1_01", self.manifest)

    # ---- 卡片 ----
    def evidence(self) -> dict:
        return {
            "sandbox_execution_id": EXEC,
            "script_hash": self.script_hash,
            "plan_ref": PLN,
            "data_refs": [{"data_hash": self.artifact_hash, "manifest_entry_id": DATA_ENTRY}],
            "output_hashes": [self.artifact_hash],
            "values": [{"output_index": 0, "pointer": "/mean", "value": 0.42,
                        "comparison": "float_rel", "tolerance": 1e-9}],
        }

    def result_card(self, claim_id: str, text: str = "样本均值大于 0", **overrides) -> dict:
        card = {
            "claim_id": claim_id, "claim_type": "result", "claim_text": _text(text),
            "status": "active", "confidence": "confirmatory",
            "evidence": self.evidence(), "lineage": dict(LINEAGE, **overrides.get("lineage", {})),
        }
        card.update({k: v for k, v in overrides.items() if k not in ("lineage",)})
        return card

    def method_card(self, claim_id: str, text: str = "方法类声明卡片") -> dict:
        evidence = self.evidence()
        del evidence["values"]
        del evidence["data_refs"]
        return {
            "claim_id": claim_id, "claim_type": "method", "claim_text": _text(text),
            "status": "active", "confidence": "confirmatory",
            "evidence": evidence, "lineage": dict(LINEAGE),
        }

    def context_card(self, claim_id: str, text: str = "背景类声明卡片", **ref) -> dict:
        entry = {"doi": DOI_PRIMARY, "manifest_entry_id": LIT_PRIMARY,
                 "verification": "primary", "locator": "p.12", "snapshot_ref": self.snapshot}
        entry.update(ref)
        return {
            "claim_id": claim_id, "claim_type": "context", "claim_text": _text(text),
            "status": "active", "confidence": "confirmatory",
            "citation_refs": [entry], "lineage": dict(LINEAGE),
        }

    def framing_card(self, claim_id: str, text: str = "框架类声明卡片", **ref) -> dict:
        entry = {"survey_doi": DOI_SURVEY, "manifest_entry_id": LIT_SURVEY, "locator": "sec 1"}
        entry.update(ref)
        return {
            "claim_id": claim_id, "claim_type": "framing", "claim_text": _text(text),
            "status": "active", "confidence": "confirmatory",
            "framing_ref": entry, "lineage": dict(LINEAGE),
        }

    def stub(self, card: dict, manifest_version: str = "MANIFEST#7") -> dict:
        return {"claimcard_schema_version": CLAIMCARD_VERSION, "card": card,
                "manifest_version": manifest_version, "venue_profile_version": "vp-2026.10"}

    def append(self, card: dict, **kw):
        return self.ledger.append(card, manifest=self.manifest, run_context=self.context, **kw)


print("==== M1 最小闭环行为验收 v3（八步链 + 签发 + rail / ClaimRow 1.2.0 · ClaimCard 1.4.0）====\n")

# --------------------------------------------------------------------------- #
# A. row_id 派生与行级幂等
# --------------------------------------------------------------------------- #
print("-- A. row_id 派生与行级幂等 --")
with tempfile.TemporaryDirectory(prefix="m1-a-") as td:
    f = Fixture(Path(td))
    card = f.result_card(cid(1))

    rid1 = derive_row_id(f.stub(card))
    rid2 = derive_row_id(f.stub(json.loads(json.dumps(card))))
    check("A1 同内容两次派生 row_id 相同", rid1 == rid2, f"{rid1} vs {rid2}")
    check("A2 row_id 形如 row_+16 位十六进制", rid1.startswith("row_") and len(rid1) == 20, rid1)

    changed = json.loads(json.dumps(card))
    changed["claim_text"] = "样本均值大于 1"
    check("A3 内容变化 → row_id 变化", derive_row_id(f.stub(changed)) != rid1)

    decorated = json.loads(json.dumps(f.stub(card)))
    decorated.update({"row_id": rid1, "appended_at": "2026-10-25T00:00:00Z",
                      "audit_event_id": "evt_" + "ab" * 8, "row_seq": 9,
                      "prev_row_hash": "sha256:" + "cd" * 32,
                      "row_hash": "sha256:" + "ef" * 32})
    check("A4 易变字段（row_id/row_seq/时间/事件id/前后链哈希）不影响 row_id",
          derive_row_id(decorated) == rid1)

    res1 = f.append(card, now=1000.0)
    check("A5 首次 append 真实落账（row_seq=1）",
          res1.appended and not res1.duplicate and res1.row_seq == 1, str(res1))
    events_before = len(f.ledger.raw_events())
    res2 = f.append(card, now=2000.0)
    check("A6 重复 append 命中幂等键（row_id 相同、不新增）",
          res2.duplicate and not res2.appended and res2.row_id == rid1, str(res2))
    check("A7 幂等 append 不新增账本行与 rawlog 事件",
          len(f.ledger.rows()) == 1 and len(f.ledger.raw_events()) == events_before,
          f"rows={len(f.ledger.rows())} events={len(f.ledger.raw_events())}")
    check("A8 落账行的 row_hash 可被独立重算",
          f.ledger.rows()[0]["row_hash"] == chain_digest(f.ledger.rows()[0]))

# --------------------------------------------------------------------------- #
# B. 步 1 schema 校验
# --------------------------------------------------------------------------- #
print("\n-- B. 步 1 schema 校验 --")
with tempfile.TemporaryDirectory(prefix="m1-b-") as td:
    f = Fixture(Path(td))
    four_ok = [f.result_card(cid(20)), f.method_card(cid(21)),
               f.context_card(cid(22)), f.framing_card(cid(23))]
    check("B1 四类卡（result/method/context/framing）正例全部通过 schema",
          all(code_of(lambda c=c: validate_card(c)) == "NO-RAISE" for c in four_ok))

    no_values = json.loads(json.dumps(four_ok[0]))
    del no_values["evidence"]["values"]
    check("B2 result 卡缺 values → SCHEMA_FAIL",
          code_of(lambda: validate_card(no_values)) == "SCHEMA_FAIL")

    framing_ev = json.loads(json.dumps(four_ok[3]))
    framing_ev["evidence"] = json.loads(json.dumps(four_ok[1]["evidence"]))
    check("B3 framing 卡带 evidence → SCHEMA_FAIL",
          code_of(lambda: validate_card(framing_ev)) == "SCHEMA_FAIL")

    first_superseded = json.loads(json.dumps(four_ok[1]))
    first_superseded["status"] = "superseded"
    check("B4 首行 status=superseded（无 transition）→ SCHEMA_FAIL",
          code_of(lambda: validate_card(first_superseded)) == "SCHEMA_FAIL")

    bad_role = json.loads(json.dumps(four_ok[1]))
    bad_role["lineage"]["created_by_role"] = "reviewer"
    check("B5 未登记角色 reviewer → SCHEMA_FAIL",
          code_of(lambda: validate_card(bad_role)) == "SCHEMA_FAIL")

    bad_event = json.loads(json.dumps(f.stub(four_ok[0])))
    bad_event.update({"row_id": "row_" + "ab" * 8, "row_seq": 1,
                      "appended_at": "2026-10-25T00:00:00Z",
                      "audit_event_id": "evt_zz", "prev_row_hash": ""})
    check("B6 行 audit_event_id 不合 ^evt_[a-f0-9]{16}$ → SCHEMA_FAIL",
          code_of(lambda: validate_row(dict(bad_event, row_hash="sha256:" + "cd" * 32))) == "SCHEMA_FAIL")

    bad_ver = json.loads(json.dumps(bad_event))
    bad_ver["audit_event_id"] = "evt_" + "ab" * 8
    bad_ver["claimcard_schema_version"] = "1.3.0"
    check("B7 行 claimcard_schema_version 不符 const → SCHEMA_FAIL",
          code_of(lambda: validate_row(dict(bad_ver, row_hash="sha256:" + "cd" * 32))) == "SCHEMA_FAIL")

    before = len(f.ledger.rows())
    code_of(lambda: f.append(no_values))
    code_of(lambda: f.append(first_superseded))
    check("B8 schema 失败的卡不落账（账本行数不变、无 WAL）",
          len(f.ledger.rows()) == before and not list(f.ledger.wal_dir.glob("*.json")),
          f"rows={len(f.ledger.rows())}/{before}")

# --------------------------------------------------------------------------- #
# C. 步 2 执行溯源与事件链
# --------------------------------------------------------------------------- #
print("\n-- C. 步 2 执行溯源与事件链 --")
with tempfile.TemporaryDirectory(prefix="m1-c-") as td:
    f = Fixture(Path(td))
    unknown = f.result_card(cid(30))
    unknown["evidence"]["sandbox_execution_id"] = "exec_" + "deadbeefdeadbeef"
    check("C1 执行未在事件链登记 → EXEC_UNRESOLVED",
          code_of(lambda: f.append(unknown)) == "EXEC_UNRESOLVED")

    f.ledger.record_execution("exec_" + "1111222233334444", status="failed", now=901.0)
    failed = f.result_card(cid(31))
    failed["evidence"]["sandbox_execution_id"] = "exec_" + "1111222233334444"
    check("C2 执行状态 failed → EXEC_REJECTED", code_of(lambda: f.append(failed)) == "EXEC_REJECTED")

    f.ledger.record_execution("exec_" + "5555666677778888", audit_status="missing", now=902.0)
    unaudited = f.result_card(cid(32))
    unaudited["evidence"]["sandbox_execution_id"] = "exec_" + "5555666677778888"
    check("C3 执行审计不可用 → EXEC_REJECTED", code_of(lambda: f.append(unaudited)) == "EXEC_REJECTED")

    check("C4 正常执行登记后 result 卡可落账", code_of(lambda: f.append(f.result_card(cid(33)))) == "NO-RAISE")

    events = f.ledger.raw_events()
    tampered = [dict(e) for e in events]
    tampered[0] = dict(tampered[0], status="completed（被改写）")
    f.ledger.rawlog_path.write_text(
        "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in tampered),
        encoding="utf-8")
    check("C5 rawlog 事件内容被改写 → EXEC_CHAIN_FAIL",
          code_of(lambda: f.ledger.verify_event_chain()) == "EXEC_CHAIN_FAIL")

with tempfile.TemporaryDirectory(prefix="m1-c2-") as td:
    f = Fixture(Path(td))
    events = f.ledger.raw_events()
    forged = [dict(e) for e in events]
    forged[0] = dict(forged[0], event_id="evt_" + "ff" * 8)
    f.ledger.rawlog_path.write_text(
        "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in forged),
        encoding="utf-8")
    check("C6 事件 id 非本账本签发（冒签）→ EXEC_CHAIN_FAIL",
          code_of(lambda: f.ledger.verify_event_chain()) == "EXEC_CHAIN_FAIL")

with tempfile.TemporaryDirectory(prefix="m1-c3-") as td:
    f = Fixture(Path(td))
    f.ledger.CHECKPOINT_EVERY = 3
    for i in range(3):
        f.ledger.record_execution("exec_" + f"{i:016x}", now=910.0 + i)
    cp = f.ledger.checkpoint_path
    payload = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}
    events = f.ledger.raw_events()
    check("C7 每 N 个事件写 checkpoint（count/last_hash）",
          cp.exists() and payload.get("count") == 3
          and payload.get("last_hash") == events[2]["event_hash"],
          str(payload))

    check("C8 从 checkpoint 验到链尾仍全绿", code_of(lambda: f.ledger.verify_event_chain()) == "NO-RAISE")

# --------------------------------------------------------------------------- #
# D. 步 3 MANIFEST 上下文
# --------------------------------------------------------------------------- #
print("\n-- D. 步 3 MANIFEST 上下文 --")
with tempfile.TemporaryDirectory(prefix="m1-d-") as td:
    f = Fixture(Path(td))
    check("D1 数据引用落在本轮 MANIFEST → 放行", code_of(lambda: f.append(f.result_card(cid(40)))) == "NO-RAISE")

    drift = f.result_card(cid(41))
    drift["evidence"]["data_refs"][0]["data_hash"] = "sha256:" + "00" * 32
    check("D2 data_refs 哈希与条目不符 → TRANSPORTIVITY_FAIL",
          code_of(lambda: f.append(drift)) == "TRANSPORTIVITY_FAIL")

    wrong_kind = f.result_card(cid(42))
    wrong_kind["evidence"]["data_refs"][0]["manifest_entry_id"] = LIT_PRIMARY
    check("D3 data_refs 指向文献条目 → MANIFEST_CONTEXT_MISMATCH",
          code_of(lambda: f.append(wrong_kind)) == "MANIFEST_CONTEXT_MISMATCH")

    other_ctx = RunContext("run_other", "MANIFEST#8", "runctx_other", f.manifest)
    check("D4 行 manifest_version ≠ RunContext → MANIFEST_CONTEXT_MISMATCH",
          code_of(lambda: f.ledger.append(f.result_card(cid(43)), manifest=f.manifest,
                                          run_context=other_ctx)) == "MANIFEST_CONTEXT_MISMATCH")

    check("D5 带 data_refs 但不挂 MANIFEST → MANIFEST_CONTEXT_MISMATCH",
          code_of(lambda: f.ledger.append(f.result_card(cid(44)))) == "MANIFEST_CONTEXT_MISMATCH")

    check("D6 Manifest.require_data_ref 对不存在条目报 MANIFEST_CONTEXT_MISMATCH",
          code_of(lambda: f.manifest.require_data_ref("mfe_ffffffffffff", "sha256:" + "00" * 32))
          == "MANIFEST_CONTEXT_MISMATCH")

    check("D7 无 data_refs 的 method 卡可在无 manifest 时落账",
          code_of(lambda: f.ledger.append(f.method_card(cid(45)))) == "NO-RAISE")

# --------------------------------------------------------------------------- #
# E. 步 4 hash 绑定
# --------------------------------------------------------------------------- #
print("\n-- E. 步 4 hash 绑定 --")
with tempfile.TemporaryDirectory(prefix="m1-e-") as td:
    f = Fixture(Path(td))
    bad_script = f.result_card(cid(50))
    f.ledger.script_path(f.script_hash).write_bytes(b"print('tampered')\n")
    check("E1 脚本落盘后被改写 → HASH_MISMATCH", code_of(lambda: f.append(bad_script)) == "HASH_MISMATCH")

with tempfile.TemporaryDirectory(prefix="m1-e2-") as td:
    f = Fixture(Path(td))
    missing = f.result_card(cid(51))
    missing["evidence"]["output_hashes"] = ["sha256:" + "11" * 32]
    check("E2 产物未入库 → ARTIFACT_UNREACHABLE", code_of(lambda: f.append(missing)) == "ARTIFACT_UNREACHABLE")

with tempfile.TemporaryDirectory(prefix="m1-e3-") as td:
    f = Fixture(Path(td))
    fig = f.result_card(cid(52))
    fig["evidence"]["figure_hashes"] = ["sha256:" + "22" * 32]
    check("E3 figure_hash 不在 output_hashes → FIGURE_HASH_UNBOUND",
          code_of(lambda: f.append(fig)) == "FIGURE_HASH_UNBOUND")

    figok = f.result_card(cid(53))
    figok["evidence"]["figure_hashes"] = [f.artifact_hash]
    check("E4 figure_hash 属 output_hashes → 放行", code_of(lambda: f.append(figok)) == "NO-RAISE")

    unbound = f.result_card(cid(54))
    unbound["evidence"]["plan_ref"] = "pln_aaaaaaaaaaaa"
    check("E5 plan_ref 未登记为 PlanItem → PLAN_UNBOUND", code_of(lambda: f.append(unbound)) == "PLAN_UNBOUND")

with tempfile.TemporaryDirectory(prefix="m1-e4-") as td:
    f = Fixture(Path(td))
    f.ledger.register_plan(PLN, "sha256:" + "33" * 32)  # 期望脚本哈希与当前脚本不符
    check("E6 PlanItem expected_script_hash 不符 → PLAN_MISMATCH",
          code_of(lambda: f.append(f.result_card(cid(55)))) == "PLAN_MISMATCH")

    exploratory = f.result_card(cid(56), confidence="exploratory",
                                lineage={"deviation_note": "探索性运行，仅作假设生成"})
    check("E7 exploratory 带 deviation_note 时 plan 错配降级放行",
          code_of(lambda: f.append(exploratory)) == "NO-RAISE")

# --------------------------------------------------------------------------- #
# F. 步 5 数值定位
# --------------------------------------------------------------------------- #
print("\n-- F. 步 5 数值定位 --")
with tempfile.TemporaryDirectory(prefix="m1-f-") as td:
    f = Fixture(Path(td))

    def with_values(**kw) -> dict:
        card = f.result_card(cid(60))
        value = {"output_index": 0, "pointer": "/mean", "value": 0.42,
                 "comparison": "float_rel", "tolerance": 1e-9}
        value.update(kw)
        if value.get("tolerance") is None:
            value.pop("tolerance", None)
        card["evidence"]["values"] = [value]
        return card

    check("F1 JSON pointer 定位 + float_rel 容差内 → 放行", code_of(lambda: f.append(with_values())) == "NO-RAISE")
    check("F2 exact 比较且值相符 → 放行",
          code_of(lambda: f.append(with_values(value=0.42, comparison="exact", tolerance=None)))
          == "NO-RAISE")
    check("F3 声明值与产物不符 → VALUE_LOCATOR_FAIL",
          code_of(lambda: f.append(with_values(value=0.43))) == "VALUE_LOCATOR_FAIL")
    check("F4 超出容差 → VALUE_LOCATOR_FAIL",
          code_of(lambda: f.append(with_values(value=0.4201, tolerance=1e-9))) == "VALUE_LOCATOR_FAIL")
    check("F5 output_index 界外 → OUTPUT_INDEX_OUT_OF_RANGE",
          code_of(lambda: f.append(with_values(output_index=3))) == "OUTPUT_INDEX_OUT_OF_RANGE")
    check("F6 pointer 不存在 → VALUE_LOCATOR_FAIL",
          code_of(lambda: f.append(with_values(pointer="/nope"))) == "VALUE_LOCATOR_FAIL")

    csv_hash = f.ledger.store_artifact(b"metric,value\nmean,0.42\n")
    csv_card = f.result_card(cid(61))
    csv_card["evidence"]["output_hashes"] = [csv_hash]
    csv_card["evidence"]["values"] = [{"output_index": 0, "pointer": "csv:value",
                                       "value": 0.42, "comparison": "float_rel", "tolerance": 1e-9}]
    check("F7 csv:<列名> 定位并转型 → 放行", code_of(lambda: f.append(csv_card)) == "NO-RAISE")

    csv_bad = json.loads(json.dumps(csv_card))
    csv_bad["claim_id"] = cid(62)
    csv_bad["evidence"]["values"][0]["pointer"] = "csv:missing"
    check("F8 csv 列不存在 → VALUE_LOCATOR_FAIL", code_of(lambda: f.append(csv_bad)) == "VALUE_LOCATOR_FAIL")

# --------------------------------------------------------------------------- #
# G. 步 6 引用一致性
# --------------------------------------------------------------------------- #
print("\n-- G. 步 6 引用一致性 --")
with tempfile.TemporaryDirectory(prefix="m1-g-") as td:
    f = Fixture(Path(td))
    check("G1 primary 引用（DOI 在册 + 快照在库 + locator 在册）→ 放行",
          code_of(lambda: f.append(f.context_card(cid(70)))) == "NO-RAISE")

    check("G2 DOI 不在 MANIFEST → DOI_NOT_IN_MANIFEST",
          code_of(lambda: f.append(f.context_card(cid(71), doi="10.9999/ghost")))
          == "DOI_NOT_IN_MANIFEST")

    no_snapshot = f.context_card(cid(72))
    del no_snapshot["citation_refs"][0]["snapshot_ref"]
    check("G3 primary 缺 snapshot_ref → SNAPSHOT_MISSING",
          code_of(lambda: f.append(no_snapshot)) == "SNAPSHOT_MISSING")

    check("G4 snapshot_ref 不在快照库 → SNAPSHOT_MISSING",
          code_of(lambda: f.append(f.context_card(cid(73), snapshot_ref="sha256:" + "44" * 32)))
          == "SNAPSHOT_MISSING")

    check("G5 locator 不在白名单 → CITATION_LOCATOR_FAIL",
          code_of(lambda: f.append(f.context_card(cid(74), locator="p.99")))
          == "CITATION_LOCATOR_FAIL")

    def with_transfer(claim_id: str, survey_doi: str) -> dict:
        """context 卡必须至少有一条 primary；survey_transfer 作为第二条引用受检。"""
        card = f.context_card(claim_id)
        card["citation_refs"].append({
            "doi": DOI_PRIMARY, "manifest_entry_id": LIT_PRIMARY,
            "verification": "survey_transfer", "locator": "p.12", "survey_doi": survey_doi,
        })
        return card

    check("G6 survey_transfer 的 survey 是 supporting → BACKBONE_GRADE_VIOLATION",
          code_of(lambda: f.append(with_transfer(cid(75), DOI_SUPPORT))) == "BACKBONE_GRADE_VIOLATION")

    check("G7 survey_transfer 的 survey 是 backbone → 放行",
          code_of(lambda: f.append(with_transfer(cid(76), DOI_SURVEY))) == "NO-RAISE")

    check("G8 framing 指向 supporting 文献 → BACKBONE_GRADE_VIOLATION",
          code_of(lambda: f.append(f.framing_card(cid(77), survey_doi=DOI_SUPPORT)))
          == "BACKBONE_GRADE_VIOLATION")

    check("G9 framing 指向 backbone 文献 → 放行",
          code_of(lambda: f.append(f.framing_card(cid(78)))) == "NO-RAISE")

    check("G10 带 citation_refs 但不挂 MANIFEST → MANIFEST_CONTEXT_MISMATCH",
          code_of(lambda: f.ledger.append(f.context_card(cid(79)))) == "MANIFEST_CONTEXT_MISMATCH")

    check("G11 manifest_entry_id 与 DOI 所属条目不一致 → MANIFEST_CONTEXT_MISMATCH",
          code_of(lambda: f.append(f.context_card(cid(80), manifest_entry_id=LIT_SUPPORT)))
          == "MANIFEST_CONTEXT_MISMATCH")

# --------------------------------------------------------------------------- #
# H. 步 7 偏差标注
# --------------------------------------------------------------------------- #
print("\n-- H. 步 7 偏差标注 --")
with tempfile.TemporaryDirectory(prefix="m1-h-") as td:
    f = Fixture(Path(td))
    check("H1 exploratory 缺 deviation_note → DEVIATION_UNNOTED",
          code_of(lambda: f.append(f.result_card(cid(90), confidence="exploratory")))
          == "DEVIATION_UNNOTED")
    check("H2 exploratory 带 deviation_note → 放行",
          code_of(lambda: f.append(f.result_card(cid(91), confidence="exploratory",
                                                 lineage={"deviation_note": "探索性假设生成"})))
          == "NO-RAISE")
    check("H3 confirmatory 无 deviation_note → 放行",
          code_of(lambda: f.append(f.result_card(cid(92)))) == "NO-RAISE")

# --------------------------------------------------------------------------- #
# I. 步 8 落账、签发与恢复
# --------------------------------------------------------------------------- #
print("\n-- I. 步 8 落账、签发与恢复 --")
with tempfile.TemporaryDirectory(prefix="m1-i-") as td:
    f = Fixture(Path(td))
    f.append(f.result_card(cid(100)), now=1000.0)
    row = f.ledger.rows()[0]
    check("I1 落账行带 audit_event_id（^evt_[a-f0-9]{16}$）",
          bool(re.match(r"^evt_[a-f0-9]{16}$", row.get("audit_event_id", ""))),
          str(row.get("audit_event_id")))
    check("I2 对账全绿", f.ledger.audit().ok, str(f.ledger.audit().codes))

    forged = [dict(r) for r in f.ledger.rows()]
    forged[0]["audit_event_id"] = "evt_" + "ee" * 8
    f.ledger.claims_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in forged),
        encoding="utf-8")
    check("I3 audit_event_id 被伪造 → TAMPER_DETECTED",
          "TAMPER_DETECTED" in f.ledger.audit().codes, str(f.ledger.audit().codes))

with tempfile.TemporaryDirectory(prefix="m1-i2-") as td:
    f = Fixture(Path(td))
    f.append(f.result_card(cid(101)), now=1001.0)
    check("I4 row_seq 被占用后提交新行 → ROW_CONFLICT",
          code_of(lambda: f.ledger._commit({"row_id": "row_" + "aa" * 8,
                                            "row": {"row_seq": 1}})) == "ROW_CONFLICT")

with tempfile.TemporaryDirectory(prefix="m1-i3-") as td:
    f = Fixture(Path(td))
    events_before = len(f.ledger.raw_events())
    card = f.result_card(cid(102))
    crashed = False
    try:
        f.append(card, crash_after="rawlog")
    except SimulatedCrash:
        crashed = True
    check("I5 rawlog 之后崩溃：账本 0 行、rawlog 多 1 条、WAL pending",
          crashed and len(f.ledger.rows()) == 0
          and len(f.ledger.raw_events()) == events_before + 1
          and len(list(f.ledger.wal_dir.glob("*.json"))) == 1,
          f"rows={len(f.ledger.rows())} events={len(f.ledger.raw_events())}/{events_before}")
    stats = f.ledger.recover()
    check("I6 pending 事务回滚（账本仍 0 行、WAL 清空）",
          stats["rolled_back"] == 1 and len(f.ledger.rows()) == 0
          and not list(f.ledger.wal_dir.glob("*.json")), str(stats))
    check("I7 回滚后对账全绿", f.ledger.audit().ok, str(f.ledger.audit().codes))

with tempfile.TemporaryDirectory(prefix="m1-i4-") as td:
    f = Fixture(Path(td))
    card = f.result_card(cid(103))
    try:
        f.append(card, crash_after="ledger")
    except SimulatedCrash:
        pass
    check("I8 账本已写 WAL 未清：数据可见且对账全绿",
          len(f.ledger.rows()) == 1 and f.ledger.audit().ok)
    f.ledger.recover()
    check("I9 恢复后重复 append 仍幂等（不产生第二行）",
          f.append(card).duplicate and len(f.ledger.rows()) == 1)

# --------------------------------------------------------------------------- #
# J. 六道 rail 集成
# --------------------------------------------------------------------------- #
print("\n-- J. 六道 rail 集成 --")
try:
    from m1 import rails  # noqa: E402

    RAIL_OK = True
except Exception as exc:  # pragma: no cover
    rails = None  # type: ignore[assignment]
    RAIL_OK = False
    rail_err = str(exc)

with tempfile.TemporaryDirectory(prefix="m1-j-") as td:
    f = Fixture(Path(td))
    if not RAIL_OK:
        check("J0 m1/rails.py 可导入", False, rail_err)
    else:
        def rail_ctx(**kw):
            base = dict(now=1000.0, allowed_claim_types=("result", "method", "context", "framing"),
                        forbidden_licenses=(), budget_tokens=1000, spent_tokens=0,
                        budget_cost=10.0, spent_cost=0.0, human_approver="hitl-01")
            base.update(kw)
            return rails.RailContext(**base)

        decisions = rails.evaluate(f.result_card(cid(110)), manifest=f.manifest, context=rail_ctx())
        check("J1 evaluate 恒返回六条决策且覆盖 RAIL_NAMES",
              len(decisions) == 6 and {d.rail for d in decisions} == set(rails.RAIL_NAMES),
              str([d.rail for d in decisions]))
        check("J2 正常卡六道 rail 全部 ALLOW", not rails.blocked(decisions),
              str(rails.codes(decisions)))

        budget = rails.evaluate(f.result_card(cid(111)), manifest=f.manifest,
                                context=rail_ctx(budget_tokens=100, spent_tokens=150))
        check("J3 超出 token 预算 → Budget rail 拦截", bool(rails.blocked(budget)),
              str(rails.codes(budget)))

        scope = rails.evaluate(f.result_card(cid(112)), manifest=f.manifest,
                               context=rail_ctx(allowed_claim_types=("method",)))
        check("J4 claim_type 不在本轮范围 → InferenceScope rail 拦截", bool(rails.blocked(scope)),
              str(rails.codes(scope)))

        lic = rails.evaluate(f.context_card(cid(113)), manifest=f.manifest,
                             context=rail_ctx(forbidden_licenses=("cc-by",)))
        check("J5 引用落在禁用许可 → Compliance rail 拦截", bool(rails.blocked(lic)),
              str(rails.codes(lic)))

        check("J6 rail 全 ALLOW 时经 ledger.append(context=...) 可落账",
              code_of(lambda: f.ledger.append(f.result_card(cid(114)), manifest=f.manifest,
                                              run_context=f.context,
                                              context=rail_ctx())) == "NO-RAISE")

        blocked_card = f.result_card(cid(115))
        before = len(f.ledger.rows())
        code = code_of(lambda: f.ledger.append(blocked_card, manifest=f.manifest,
                                               run_context=f.context,
                                               context=rail_ctx(budget_tokens=1, spent_tokens=99)))
        check("J7 rail 拦截时 append 拒绝且不落账",
              code != "NO-RAISE" and len(f.ledger.rows()) == before, f"code={code}")

# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
print()
if FAILURES:
    print(f"M1 行为验收：{len(FAILURES)}/{CHECKS} 项失败 → 不可发布")
    for name in FAILURES:
        print(f"  - {name}")
    raise SystemExit(1)
print(f"M1 行为验收：全绿（{CHECKS} 项断言；A 幂等 / B 步1 / C 步2 / D 步3 / E 步4 / "
      "F 步5 / G 步6 / H 步7 / I 步8 / J rail）")
raise SystemExit(0)
