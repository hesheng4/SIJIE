#!/usr/bin/env python3
"""validate_freeze.py — 阶段 1 冻结门禁（D26）。

判据（交付物 §五 5.1）：
  1. 全部 schema 文件通过 draft-07 meta-schema 校验；
  2. 全部 $ref 可解析（本地 definitions 递归走查，占位/中文引用即失败）；
  3. 十三断言分层执行（schema 层实测 jsonschema；链层断言登记为 ledger-mcp 用例契约）；
  4. 错误码唯一性矩阵校验（子例→错误码 一一对应，无跨步双属）；
  5. JCS 确定性（稳定投影派生 row_id / replay_normalized_hash 的确定性验证）。

退出码 0 = 全绿（可冻结）；非 0 = 存在失败用例。
"""
import copy
import hashlib
import json
import pathlib
import sys

try:
    import jsonschema
    from jsonschema import Draft7Validator, FormatChecker
except ImportError:
    print("FATAL: jsonschema 未安装（pip install jsonschema）")
    sys.exit(2)

ROOT = pathlib.Path(__file__).resolve().parent.parent
S = ROOT / "schemas"

FAILURES = []


def check(name: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


# ---------- 1. meta-schema ----------
SCHEMA_FILES = ["claimcard-1.3.0.json", "claimrow-1.1.0.json", "planitem-1.0.1.json",
                "manifestentry-1.0.0.json", "contracts-1.1.0.json", "exclusionlist-1.0.2.json"]
loaded = {}
for fn in SCHEMA_FILES:
    with open(S / fn, encoding="utf-8") as f:
        sch = json.load(f)
    loaded[fn] = sch
    try:
        Draft7Validator.check_schema(sch)
        check(f"meta-schema: {fn}", True)
    except jsonschema.SchemaError as e:
        check(f"meta-schema: {fn}", False, str(e)[:200])


# ---------- 2. $ref 全解析 ----------
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
    check(f"$ref 全解析: {fn}", not bad, "; ".join(f"{p}: {m}" for p, m in bad[:3]))


# ---------- 3. 十三断言（schema 层实测） ----------
H16 = "a1b2c3d4e5f60718"
SHA = "sha256:" + "ab" * 32
MFE = "mfe_" + "0f1e2d3c4b5a"
PLN = "pln_" + "0f1e2d3c4b5a"

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

transition_ok = copy.deepcopy(method_card)
transition_ok["status"] = "superseded"
transition_ok["lineage"]["transition"] = {
    "from": "active", "to": "superseded", "by_role": "gate_rail",
    "on_behalf_of_role": "analyst", "reason": "replaced by newer run",
    "credential_kind": "rail", "audit_event_id": "evt_" + H16}

transition_owner_banned = copy.deepcopy(method_card)
transition_owner_banned["status"] = "superseded"
transition_owner_banned["lineage"]["transition"] = {
    "from": "active", "to": "superseded", "by_role": "owner",
    "reason": "legacy owner path", "audit_event_id": "evt_" + H16}

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

card_schema = loaded["claimcard-1.3.0.json"]
card_v = Draft7Validator(card_schema, format_checker=FormatChecker())

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
]
for name, inst, expect_valid in INSTANCES:
    errs = sorted(card_v.iter_errors(inst), key=lambda e: e.path)
    ok = (not errs) == expect_valid
    detail = "" if ok else errs[0].message[:160] if errs else "预期失败但通过"
    check(name, ok, detail)

# 链层用例契约登记（schema 层无法判定，交 ledger-mcp 实现）：
CHAIN_CASES = [
    "method 拒B·plan_ref 不可解析 → 步4 PLAN_UNBOUND",
    "context 拒B·条目不属当前轮 → 步6 DOI_NOT_IN_MANIFEST",
    "framing 拒B·指向 T3 条目 → 步6 BACKBONE_GRADE_VIOLATION",
    "transition 拒·缺 on_behalf_of_role → 步4 TRANSITION_INVALID",
]
print(f"[REG ] 链层用例契约 ×{len(CHAIN_CASES)}（ledger-mcp 实现后由 M3 验收）")

# ClaimRow 包装测试
row_schema = loaded["claimrow-1.1.0.json"]
row_v = Draft7Validator(row_schema, format_checker=FormatChecker())
valid_row = {"row_id": "row_" + H16, "row_seq": 0, "claimcard_schema_version": "1.3.0",
             "card": copy.deepcopy(result_card), "appended_at": "2026-10-25T00:00:00Z",
             "audit_event_id": "evt_" + H16, "manifest_version": "man_v1",
             "venue_profile_version": "vp_fixture_stage1"}
check("ClaimRow 正例（内嵌 card $ref 生效）", row_v.is_valid(valid_row),
      str(next(iter(row_v.iter_errors(valid_row)), ""))[:160])
bad_row = dict(valid_row, rogue_field=1)
check("ClaimRow 拒·未知字段（行级封闭）", not row_v.is_valid(bad_row))


# ---------- 4. 错误码唯一性矩阵 ----------
MATRIX = [
    ("T1a", "CALLER_DENIED"), ("T1b1", "SCHEMA_FAIL"), ("T1b2", "EXEC_UNRESOLVED"),
    ("T1b3", "EXEC_CHAIN_FAIL"), ("T2", "TRANSPORTIVITY_FAIL|MANIFEST_CONTEXT_MISMATCH"),
    ("T3", "VALUE_LOCATOR_FAIL|OUTPUT_INDEX_OUT_OF_RANGE"), ("T4a", "tamper_detected"),
    ("T4b", "phantom_event"), ("T4c", "EACCES"),
    ("T5a", "PLAN_UNBOUND|PLAN_MISMATCH"), ("T5b", "EXEC_REJECTED"),
    ("T5c", "TRANSITION_INVALID"), ("T5d", "ROW_CONFLICT"),
    ("T5e", "recovery-criteria"), ("T5f", "EXCLUDED_CLAIM_REFERENCE"),
]
codes = [c for _, c in MATRIX if c != "recovery-criteria"]
all_codes = [c for group in codes for c in group.split("|")]
dups = {c for c in all_codes if all_codes.count(c) > 1}
check("错误码唯一性矩阵（15 子例，无跨例重复码）", not dups, f"重复: {dups}")


# ---------- 5. JCS 确定性（稳定投影派生） ----------
VOLATILE = ("appended_at", "audit_event_id", "row_seq")


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def stable_projection(row: dict) -> dict:
    return {k: copy.deepcopy(v) for k, v in row.items() if k not in VOLATILE}


def derive_row_id(row: dict) -> str:
    return "row_" + hashlib.sha256(canonical(stable_projection(row)).encode()).hexdigest()[:16]


r1 = copy.deepcopy(valid_row)
r2 = copy.deepcopy(valid_row)
r2["appended_at"] = "2027-01-01T00:00:00Z"   # 崩溃重试：时间不同
r2["row_seq"] = 42
r2["audit_event_id"] = "evt_" + "f" * 16
check("JCS 确定性·崩溃重试派生同一 row_id", derive_row_id(r1) == derive_row_id(r2))
check("JCS 确定性·重放基准 hash 稳定",
      hashlib.sha256(canonical(stable_projection(r1)).encode()).hexdigest()
      == hashlib.sha256(canonical(stable_projection(r2)).encode()).hexdigest())
r3 = copy.deepcopy(valid_row)
r3["card"]["claim_text"] = "modified text changes the projection"
check("JCS 确定性·内容变化必得新 row_id", derive_row_id(r1) != derive_row_id(r3))

# Unicode / 数值样例（JCS 样例集最小版）
u1 = {"k": "中文测试", "n": 0.1}
check("JCS 样例·Unicode/数值序列化确定",
      canonical(json.loads(canonical(u1))) == canonical(u1))

# ---------- 汇总 ----------
print()
if FAILURES:
    print(f"冻结门禁：{len(FAILURES)} 项失败 → 不可冻结")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("冻结门禁：全绿（schema 层判据满足；链层用例契约已登记，M3 验收）")
