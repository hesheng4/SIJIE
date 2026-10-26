#!/usr/bin/env python3
"""validate_freeze.py — 阶段 1 冻结门禁 v2（交付物 §五 5.1；D27 分层判据）。

四层判据（每层失败互不掩盖）：
  G1 语义层：六件 schema 通过 draft-07 meta-schema；$ref 全部本地可解析；
             六件各自有实例 fixture（含 ExclusionList oneOf / Contracts payload oneOf /
             date-time format / C4 白名单断言）——修 P0-4；
  G2 规则层：ClaimCard 1.4.0 的三条机器可判定规则（首行仅 active、by_role↔credential
             配对、superseded 必带 on_behalf_of_role）+ 角色词汇统一——修 P0-3；
  G3 一致性层：错误码矩阵（子例↔错误码一一对应、全大写、八步链码全覆盖）
              ——修 P0-4 后半；
  G4 确定性层：JCS 按 RFC 8785 实测（tools/jcs.py 官方向量 + row_id 派生幂等）
              ——修 P0-2。

退出码：0 = 全绿；1 = 存在失败；2 = 依赖缺失（jsonschema）。
用法：python tools/validate_freeze.py [-q]
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import re
import sys
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
S = ROOT / "schemas"
sys.path.insert(0, str(ROOT / "tools"))

for _stream in (sys.stdout, sys.stderr):  # cp936 控制台乱码修复（P2）
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover - 非 TTY / 老版本
        pass

try:
    import jsonschema
    from jsonschema import Draft7Validator, FormatChecker
except ImportError:
    print("FATAL: jsonschema 未安装（pip install jsonschema）")
    sys.exit(2)

try:
    from freeze_codes import CHAIN_CASES, CHAIN_CONTRACTS, MATRIX, STEP_CODES  # 错误码单一事实源
    import jcs
except ImportError:
    print("FATAL: tools/jcs.py 缺失——JCS 判据无法执行")
    sys.exit(2)

FMT = FormatChecker()


def _self_check_datetime(value: str) -> bool:
    """自实现 date-time 断言：jsonschema 的 RFC3339 checker 依赖可选包
    rfc3339-validator，未安装时静默失效（格式断言变摆设）。此处强制生效。"""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("date-time 必须带时区")
    return True


FMT.checkers["date-time"] = (_self_check_datetime, (ValueError,))  # 强制生效（内置依赖缺失时静默失效）

FAILURES: list[str] = []
CHECKS = 0
GROUPS: dict[str, list[int]] = {}
CURRENT = ["?"]  # 当前判据层（用于分组计数）


def group(key: str, title: str) -> None:
    print(f"\n--- {key} {title} ---")
    GROUPS[key] = [0, 0]
    CURRENT[0] = key


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    key = CURRENT[0]
    GROUPS[key][0] += 1
    if not ok:
        GROUPS[key][1] += 1
        FAILURES.append(name)
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail and not ok else ""))
    return ok


def load(fn: str) -> dict:
    with open(S / fn, encoding="utf-8") as f:
        return json.load(f)


# ============ G1 语义层 ============
group("G1", "语义层（meta-schema / $ref / 六件 fixture）")

# 六件清单从目录派生：文档里写死「五文件/六件」这类计数漂移从此不可发生。
SCHEMA_FILES = sorted(p.name for p in S.glob("*.json"))
check(f"schemas/ 目录清单可枚举（{len(SCHEMA_FILES)} 件）", len(SCHEMA_FILES) > 0,
      f"实际 {SCHEMA_FILES}")

loaded: dict[str, dict] = {}
for fn in SCHEMA_FILES:
    sch = load(fn)
    loaded[fn] = sch
    stem_ver = fn.rsplit("-", 1)[-1].removesuffix(".json")
    try:
        Draft7Validator.check_schema(sch)
        ok_meta = True
    except jsonschema.SchemaError as e:
        ok_meta = False
    check(f"G1a meta-schema: {fn}", ok_meta, "" if ok_meta else "见上")
    check(f"G1a 文件名版本 == 文件内 version: {fn}", stem_ver == sch.get("version"),
          f"file={stem_ver} version={sch.get('version')}")


# ---------- G1b $ref 全解析 ----------
def walk_refs(node, defs, path="$"):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                if not v.startswith("#/definitions/"):
                    yield path, f"非本地 definitions 引用: {v}"
                    continue
                name = v.split("/")[-1]
                if name not in defs:
                    yield path, f"未定义目标: {v}"
            else:
                yield from walk_refs(v, defs, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk_refs(v, defs, f"{path}/{i}")


for fn in SCHEMA_FILES:
    bad = list(walk_refs(loaded[fn], loaded[fn].get("definitions", {})))
    check(f"G1b $ref 全解析: {fn}", not bad,
          "; ".join(f"{p}: {m}" for p, m in bad[:3]))

# ---------- G1c 六件实例 fixture ----------
H16 = "a1b2c3d4e5f60718"
SHA = "sha256:" + "ab" * 32
MFE = "mfe_" + "0f1e2d3c4b5a"
PLN = "pln_" + "0f1e2d3c4b5a"
EVT = "evt_" + H16

plan_item_ok = {"plan_item_id": PLN, "description": "预注册：稳健性检查脚本",
                "frozen_at": "2026-10-25T00:00:00Z",
                "expected_script_hash": SHA, "allowed_outputs": ["/accuracy"]}
manif_data_ok = {"manifest_entry_id": MFE, "kind": "data", "curation_grade": "T1",
                 "sha256": SHA, "role": "backbone"}
manif_lit_ok = {"manifest_entry_id": MFE, "kind": "literature", "curation_grade": "T2",
                "doi": "10.1234/abc", "role": "primary",
                "snapshot_ref": SHA, "semantics_handle": "sem1",
                "provenance": {"query_path_ref": "q1", "retriever_version": "r1",
                               "exclusion_reason": "none"}}
excl_ok = {"source_run_id": "run_freeze01", "generated_at": "2026-10-25T00:00:00Z",
           "rejected_claims": ["clm_" + H16], "tainted_executions": [],
           "phantom_events": [], "orphans": [], "vetoed_directions": [],
           "manifest_decision": {"reused": "man_v1"}}
excl_rich = copy.deepcopy(excl_ok)
excl_rich["manifest_decision"] = {"created": "man_v2", "reason": "数据源刷新",
                                  "triggered_by": "data_changed", "hitl_confirmed": True}
excl_rich["vetoed_directions"] = [{"kind": "analysis", "ref": "dir_1",
                                   "reason": "预注册外分支", "veto_by": "auditor"}]
excl_rich["revival_permits"] = ["clm_" + H16]


def build_contract(payload: dict) -> dict:
    return {"contract_id": "ctr_" + "abcdef012345", "schema_version": "1.1.0",
            "from_role": "analyst", "to_role": "writing", "stage": 1,
            "run_id": "run_freeze01", "created_at": "2026-10-25T00:00:00Z",
            "payload": payload}


C_PAYLOADS = {
    "C1": {"manifest_version": "man_v1", "semantics_handle": "sem1",
           "knowledge_map_handle": "km1", "venue_profile_version": "vp_stage1"},
    "C2": {"claim_ids": ["clm_" + H16], "figure_refs": ["fig1"],
           "citation_requests": ["10.1234/abc"]},
    "C3": {"citation_cards": [{"doi": "10.1234/abc", "manifest_entry_id": MFE,
                               "verification": "primary", "locator": "p.12",
                               "snapshot_ref": SHA}]},
    "C4": {"manuscript_ref": "ms_v1", "claim_ids": ["clm_" + H16],
           "figure_refs": ["fig1"], "venue_profile_version": "vp_stage1"},
    "C5": {"review_form": {"any": "venue-specific"}, "reviewer_model": "rev_model_1"},
    "C6": {"manuscript_ref": "ms_v1", "claims_snapshot_version": "cs_1"},
    "C7": {"report_ref": "rep_1",
           "conclusions": {"passed": ["clm_" + H16], "failed": [], "undetermined": []},
           "exclusion_list": excl_ok},
    "C8": {"lesson": "预注册缺失导致重跑", "scope": "venue",
           "evidence_run_id": "run_freeze01", "source_run_status": "success"},
}

C4_INJECTED = copy.deepcopy(C_PAYLOADS["C4"])  # C4 白名单断言（交付物 §三）
C4_INJECTED["rawlog_path"] = "/var/raw/run.log"

FIXTURE_GROUPS = [
    ("PlanItem", "planitem-1.0.1.json", [
        ("正例", plan_item_ok, True),
        ("拒·未知字段（封闭）", dict(plan_item_ok, rogue=1), False),
        ("拒·date-time 格式（format 断言）", dict(plan_item_ok, frozen_at="2026-13-01"), False),
        ("拒·plan_item_id pattern", dict(plan_item_ok, plan_item_id="pln_X"), False),
    ]),
    ("ManifestEntry", "manifestentry-1.0.0.json", [
        ("正例·data", manif_data_ok, True),
        ("正例·literature+T2 provenance", manif_lit_ok, True),
        ("拒·未知字段", dict(manif_data_ok, rogue=1), False),
        ("拒·kind 枚举", dict(manif_data_ok, kind="artifact"), False),
    ]),
    ("ExclusionList", "exclusionlist-1.0.2.json", [
        ("正例·reused 分支", excl_ok, True),
        ("正例·created 分支 + vetoed + revival_permits", excl_rich, True),
        ("拒·manifest_decision 两分支皆不匹配", dict(excl_ok, manifest_decision={"created": "man_v2"}), False),
        ("拒·vetoed_directions.kind 枚举", dict(excl_ok, vetoed_directions=[
            {"kind": "figure", "ref": "x", "reason": "r", "veto_by": "hitl"}]), False),
        ("拒·未知顶层字段", dict(excl_ok, rogue=1), False),
    ]),
    ("Contracts", "contracts-1.1.0.json", [
        *[(f"正例·payload {k}", build_contract(v), True) for k, v in C_PAYLOADS.items()],
        ("拒·C4 白名单注入 rawlog_path → SCHEMA_FAIL（交付物 §三 C4 断言入门禁）",
         build_contract(C4_INJECTED), False),
        ("拒·payload 不属 C1–C8", build_contract({"foo": 1}), False),
    ]),
]

VALIDATORS = {fn: Draft7Validator(sch, format_checker=FMT) for fn, sch in loaded.items()}

for label, fn, cases in FIXTURE_GROUPS:
    v = VALIDATORS[fn]
    for cname, inst, expect_valid in cases:
        errs = sorted(v.iter_errors(inst), key=lambda e: list(e.path))
        ok = (not errs) == expect_valid
        detail = "" if ok else (errs[0].message[:160] if errs else "预期失败但通过")
        check(f"G1c {label} {cname}", ok, detail)


# ============ G2 规则层（ClaimCard 1.4.0 实例）============
group("G2", "规则层（ClaimCard 1.4.0 三条机器可判定规则 + 角色词汇）")

base_lineage = {"created_by_role": "analyst", "credential_kind": "rail",
                "created_at": "2026-10-25T00:00:00Z", "run_id": "run_freeze01"}

result_card = {
    "claim_id": "clm_" + H16, "claim_type": "result",
    "claim_text": "accuracy improves by 4.2 points on the held-out set",
    "status": "active", "confidence": "confirmatory",
    "evidence": {
        "sandbox_execution_id": "exec_" + H16, "script_hash": SHA, "plan_ref": PLN,
        "data_refs": [{"data_hash": SHA, "manifest_entry_id": MFE}],
        "output_hashes": [SHA],
        "values": [{"output_index": 0, "pointer": "/accuracy", "value": 0.92,
                    "comparison": "float_rel", "tolerance": 1e-9}]},
    "lineage": dict(base_lineage)}

method_card = {
    "claim_id": "clm_" + "b" * 16, "claim_type": "method",
    "claim_text": "we pre-process missing values by median imputation",
    "status": "active", "confidence": "confirmatory",
    "evidence": {"sandbox_execution_id": "exec_" + H16, "script_hash": SHA,
                 "plan_ref": PLN, "output_hashes": [SHA]},
    "lineage": dict(base_lineage)}

context_card = {
    "claim_id": "clm_" + "c" * 16, "claim_type": "context",
    "claim_text": "prior work reports similar gains on related benchmarks",
    "status": "active", "confidence": "confirmatory",
    "citation_refs": [{"doi": "10.1234/abc", "manifest_entry_id": MFE,
                       "verification": "primary", "locator": "p.12", "snapshot_ref": SHA}],
    "lineage": dict(base_lineage)}

framing_card = {
    "claim_id": "clm_" + "d" * 16, "claim_type": "framing",
    "claim_text": "the field commonly organizes methods into three families",
    "status": "active", "confidence": "confirmatory",
    "framing_ref": {"survey_doi": "10.1234/survey", "manifest_entry_id": MFE,
                    "locator": "sec 3"},
    "lineage": dict(base_lineage)}


def with_transition(card: dict, **over) -> dict:
    c = copy.deepcopy(card)
    tr = {"from": "active", "to": "superseded", "by_role": "gate_rail",
          "on_behalf_of_role": "analyst", "reason": "replaced by newer run",
          "credential_kind": "rail", "audit_event_id": EVT}
    tr.update(over)
    c["lineage"]["transition"] = tr
    return c


transition_ok = with_transition(method_card)
transition_ok["status"] = "superseded"
transition_owner_banned = with_transition(method_card, by_role="owner")
transition_owner_banned["status"] = "superseded"

revival_bad = copy.deepcopy(result_card)
revival_bad["lineage"]["is_revival"] = True
revival_bad["lineage"]["derived_from"] = ["clm_" + "e" * 16]

revival_ok = copy.deepcopy(result_card)
revival_ok["lineage"]["is_revival"] = True
revival_ok["lineage"]["derived_from"] = ["clm_" + "e" * 16]
revival_ok["lineage"]["revival_reason"] = "upstream data error fixed, evidence re-run"
revival_ok["lineage"]["credential_kind"] = "hitl"

result_no_values = copy.deepcopy(result_card)
del result_no_values["evidence"]["values"]

result_exact_with_tol = copy.deepcopy(result_card)
result_exact_with_tol["evidence"]["values"][0] = {
    "output_index": 0, "pointer": "/accuracy", "value": 0.92,
    "comparison": "exact", "tolerance": 1e-9}

method_no_plan = copy.deepcopy(method_card)
del method_no_plan["evidence"]["plan_ref"]

context_all_transfer = copy.deepcopy(context_card)
context_all_transfer["citation_refs"] = [{
    "doi": "10.1234/abc", "manifest_entry_id": MFE,
    "verification": "survey_transfer", "survey_doi": "10.1234/survey", "locator": "p.3"}]

framing_with_evidence = copy.deepcopy(framing_card)
framing_with_evidence["evidence"] = dict(method_card["evidence"])

# 1.4.0 新规则反例：首行仅 active / by_role↔credential / superseded 必带代签
first_row_superseded = copy.deepcopy(method_card)
first_row_superseded["status"] = "superseded"
first_row_orphan = copy.deepcopy(method_card)
first_row_orphan["status"] = "compression_orphan"
hitl_with_rail = with_transition(method_card, to="rejected", by_role="hitl",
                                 credential_kind="rail", reason="hitl rejection")
gate_rail_with_hitl = with_transition(method_card, to="rejected", by_role="gate_rail",
                                      credential_kind="hitl", reason="rail rejection")
superseded_no_proxy = with_transition(method_card)
superseded_no_proxy["status"] = "superseded"
del superseded_no_proxy["lineage"]["transition"]["on_behalf_of_role"]

legacy_role = copy.deepcopy(method_card)
legacy_role["lineage"] = dict(base_lineage, created_by_role="reviewer")
valid_role = copy.deepcopy(method_card)
valid_role["lineage"] = dict(base_lineage, created_by_role="reviewer-1")

card_schema = loaded["claimcard-1.4.0.json"]
card_v = VALIDATORS["claimcard-1.4.0.json"]

INSTANCES = [
    ("I01 result 正例（schema+链）", result_card, True),
    ("I02 result 拒·缺 values → 步1 SCHEMA_FAIL", result_no_values, False),
    ("I03 result 拒·exact 带 tolerance → 步1 SCHEMA_FAIL", result_exact_with_tol, False),
    ("I04 method 正例（schema+链）", method_card, True),
    ("I05 method 拒A·plan_ref 缺失 → 步1 SCHEMA_FAIL（D26 拆分）", method_no_plan, False),
    ("I06 context 正例", context_card, True),
    ("I07 context 拒A·全 survey_transfer → 步1 SCHEMA_FAIL（contains+required）", context_all_transfer, False),
    ("I08 framing 正例", framing_card, True),
    ("I09 framing 拒A·含 evidence → 步1 SCHEMA_FAIL", framing_with_evidence, False),
    ("I10 transition 正例·superseded/gate_rail/on_behalf_of", transition_ok, True),
    ("I11 transition 拒·by_role=owner（已废除）→ 步1 SCHEMA_FAIL", transition_owner_banned, False),
    ("I12 revival 拒·缺 hitl 凭证/理由 → SCHEMA_FAIL", revival_bad, False),
    ("I13 revival 正例·hitl+理由+谱系", revival_ok, True),
    ("I14 1.4.0 拒·首行 superseded（无 transition）→ 只允许 active", first_row_superseded, False),
    ("I15 1.4.0 拒·首行 compression_orphan", first_row_orphan, False),
    ("I16 1.4.0 拒·by_role=hitl 用 rail 凭证（凭证映射表落 schema）", hitl_with_rail, False),
    ("I17 1.4.0 拒·by_role=gate_rail 用 hitl 凭证", gate_rail_with_hitl, False),
    ("I18 1.4.0 拒·superseded 缺 on_behalf_of_role", superseded_no_proxy, False),
    ("I19 1.4.0 拒·未登记角色 reviewer（词表统一）", legacy_role, False),
    ("I20 1.4.0 正例·登记角色 reviewer-1", valid_role, True),
]
for name, inst, expect_valid in INSTANCES:
    errs = sorted(card_v.iter_errors(inst), key=lambda e: list(e.path))
    ok = (not errs) == expect_valid
    detail = "" if ok else (errs[0].message[:160] if errs else "预期失败但通过")
    check(f"G2 {name}", ok, detail)

# 链层用例契约登记（schema 层无法判定，交 ledger-mcp 实现；M3 验收）
print(f"[REG ] G2 链层用例契约 ×{len(CHAIN_CASES)}（ledger-mcp 实现后由 M3 验收）")

# ClaimRow 包装：claimcard_schema_version 与内嵌 card 版本绑定（修 P1 漂移 #12）
row_schema = loaded["claimrow-1.2.0.json"]
row_v = VALIDATORS["claimrow-1.2.0.json"]
valid_row = {"row_id": "row_" + H16, "row_seq": 0, "claimcard_schema_version": "1.4.0",
             "card": copy.deepcopy(result_card), "appended_at": "2026-10-25T00:00:00Z",
             "audit_event_id": EVT, "manifest_version": "man_v1",
             "venue_profile_version": "vp_fixture_stage1"}
row_cases = [
    ("ClaimRow 正例（内嵌 card $ref 生效）", valid_row, True),
    ("ClaimRow 拒·未知字段（行级封闭）", dict(valid_row, rogue_field=1), False),
    ("ClaimRow 拒·claimcard_schema_version 与内嵌 card 版本不符", dict(valid_row, claimcard_schema_version="1.3.0"), False),
]
for name, inst, expect_valid in row_cases:
    errs = sorted(row_v.iter_errors(inst), key=lambda e: list(e.path))
    ok = (not errs) == expect_valid
    detail = "" if ok else (errs[0].message[:160] if errs else "预期失败但通过")
    check("G2 " + name, ok, detail)


# ============ G3 一致性层（错误码矩阵）============
group("G3", "一致性层（错误码矩阵 / 八步链码覆盖）")

CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

sub_codes = {c for _, group_ in MATRIX if group_ for c in group_.split("|")}
all_codes = set(sub_codes) | STEP_CODES

dups = {}
for sub, codes_ in MATRIX:
    for c in (codes_.split("|") if codes_ else []):
        dups.setdefault(c, []).append(sub)
check("G3a 15 子例 ↔ 错误码一一对应（无跨例双属）",
      not [c for c, subs in dups.items() if len(subs) > 1],
      str({c: s for c, s in dups.items() if len(s) > 1}))
check("G3b 错误码全大写且符合 ^[A-Z][A-Z0-9_]*$",
      all(CODE_RE.match(c) for c in all_codes),
      str(sorted(c for c in all_codes if not CODE_RE.match(c))))
check("G3c 八步链码全覆盖（§1.3 表 ×20）", STEP_CODES <= all_codes, str(STEP_CODES - all_codes))
check(f"G3d 码表规模：子例码 {len(sub_codes)} + 链层专有码 {len(STEP_CODES - sub_codes)} = {len(all_codes)}",
      len(all_codes) == len(sub_codes | STEP_CODES))
print(f"[REG ] G3 链层专有码 ×{len(STEP_CODES - sub_codes)}（无 T 子例，由 M3 链层用例覆盖）")

# --- 链层用例契约登记完整性（L1–L5）：登记即契约，执行仍待 M3 ---
chain_ids = [c["id"] for c in CHAIN_CONTRACTS]
check("G3e 链层用例契约登记连续（L1–L{n}）",
      chain_ids == [f"L{i}" for i in range(1, len(chain_ids) + 1)], str(chain_ids))
check("G3f 链层契约错误码均属八步链码表",
      all(c["code"] in STEP_CODES for c in CHAIN_CONTRACTS),
      str(sorted({c["code"] for c in CHAIN_CONTRACTS} - STEP_CODES)))
REQUIRED_CHAIN = {"PLAN_UNBOUND", "DOI_NOT_IN_MANIFEST", "BACKBONE_GRADE_VIOLATION",
                  "SCHEMA_FAIL", "TRANSITION_INVALID"}
chain_codes = {c["code"] for c in CHAIN_CONTRACTS}
missing_chain = sorted(REQUIRED_CHAIN - chain_codes)
check("G3g 链层契约覆盖三通道（method/context/framing）+ 两条凭证规则",
      chain_codes == REQUIRED_CHAIN, f"缺 {missing_chain} / 多 {sorted(chain_codes - REQUIRED_CHAIN)}")
for c in CHAIN_CONTRACTS:
    print(f"[REG ] G3 链层契约 {c['id']}：{c['name']} → {c['step']} {c['code']}")


# ============ G4 确定性层（JCS = RFC 8785）============
group("G4", "确定性层（RFC 8785 / row_id 派生幂等）")

selftest = jcs.selftest()
bad_jcs = [n for n, ok_ in selftest if not ok_]
check(f"G4a jcs.py 官方向量自测（{len(selftest)} 项）", not bad_jcs, str(bad_jcs))
check("G4b 数字规范化：1.0→1 / -0.0→0 / 1e-7 / 1e20 / 1e21",
      jcs.canonical({"n": [1.0, -0.0, 1e-7, 1e20, 1e21]})
      == '{"n":[1,0,1e-7,100000000000000000000,1e+21]}')
check("G4c 键排序按 UTF-16 码元（非码点）",
      jcs.canonical({"\u20ac": 1, "\U0001f600": 2, "\ufffd": 3})
      == jcs.canonical({"\u20ac": 1, "\U0001f600": 2, "\ufffd": 3})
      and jcs.sort_key("\U0001f600") < jcs.sort_key("\ufffd"))
check("G4d 字符串转义（U+000F / 引号 / 反斜杠）",
      jcs.canonical({"s": "\u000f\"\\"}) == '{"s":"\\u000f\\"\\\\"}')
for bad in (float("nan"), float("inf")):
    try:
        jcs.canonical({"x": bad})
        check(f"G4e 拒绝非有限值 {bad!r}", False, "未抛错")
    except ValueError:
        check(f"G4e 拒绝非有限值 {bad!r}", True)

VOLATILE = ("appended_at", "audit_event_id", "row_seq")


def stable_projection(row: dict) -> dict:
    return {k: copy.deepcopy(v) for k, v in row.items() if k not in VOLATILE}


def derive_row_id(row: dict) -> str:
    return "row_" + jcs.digest16(stable_projection(row))


r1 = copy.deepcopy(valid_row)
r2 = copy.deepcopy(valid_row)
r2["appended_at"] = "2027-01-01T00:00:00Z"   # 崩溃重试：时间不同
r2["row_seq"] = 42
r2["audit_event_id"] = "evt_" + "f" * 16
check("G4f 崩溃重试派生同一 row_id", derive_row_id(r1) == derive_row_id(r2))
check("G4g 重放基准 hash 稳定（replay_normalized_hash）",
      hashlib.sha256(jcs.canonical(stable_projection(r1)).encode()).hexdigest()
      == hashlib.sha256(jcs.canonical(stable_projection(r2)).encode()).hexdigest())
r3 = copy.deepcopy(valid_row)
r3["card"]["claim_text"] = "modified text changes the projection"
check("G4h 内容变化必得新 row_id", derive_row_id(r1) != derive_row_id(r3))
check("G4i row_id 字节级可复算（独立实现等价）",
      derive_row_id(r1) == "row_" + hashlib.sha256(
          jcs.canonical(stable_projection(r1)).encode()).hexdigest()[:16])


# ============ 汇总 ============
print()
total_fail = len(FAILURES)
if total_fail:
    print(f"冻结门禁：{total_fail}/{CHECKS} 项失败 → 不可冻结")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
per = " / ".join(f"{k}: {v[0]}" for k, v in GROUPS.items())
print(f"冻结门禁：全绿（{CHECKS} 项断言；{per}；链层用例契约 {len(CHAIN_CASES)} 项待 M3）")
sys.exit(0)
