"""freeze_codes.py — 门禁与文档一致性检查共用的单一事实源。

被 tools/validate_freeze.py（G3 一致性层）与 tools/check_docs_consistency.py（文档机检）
同时引用，避免「码表改一处、文档改另一处」二源分裂。
"""
from __future__ import annotations

# 15 个反例子例（一正九反 + T5a–f）；T5e 为恢复判据，不绑定单一错误码。
MATRIX: list[tuple[str, str | None]] = [
    ("T1a", "CALLER_DENIED"),
    ("T1b1", "SCHEMA_FAIL"),
    ("T1b2", "EXEC_UNRESOLVED"),
    ("T1b3", "EXEC_CHAIN_FAIL"),
    ("T2", "TRANSPORTIVITY_FAIL|MANIFEST_CONTEXT_MISMATCH"),
    ("T3", "VALUE_LOCATOR_FAIL|OUTPUT_INDEX_OUT_OF_RANGE"),
    ("T4a", "TAMPER_DETECTED"),
    ("T4b", "PHANTOM_EVENT"),
    ("T4c", "EACCES"),
    ("T5a", "PLAN_UNBOUND|PLAN_MISMATCH"),
    ("T5b", "EXEC_REJECTED"),
    ("T5c", "TRANSITION_INVALID"),
    ("T5d", "ROW_CONFLICT"),
    ("T5e", None),
    ("T5f", "EXCLUDED_CLAIM_REFERENCE"),
]

# 八步校验链（交付物 §1.3）用到的全部错误码；其中 8 个无 T 子例，登记为链层专有码。
STEP_CODES: set[str] = {
    "SCHEMA_FAIL", "EXEC_UNRESOLVED", "EXEC_REJECTED", "EXEC_CHAIN_FAIL",
    "MANIFEST_CONTEXT_MISMATCH", "TRANSPORTIVITY_FAIL", "HASH_MISMATCH",
    "ARTIFACT_UNREACHABLE", "PLAN_UNBOUND", "PLAN_MISMATCH", "TRANSITION_INVALID",
    "FIGURE_HASH_UNBOUND", "VALUE_LOCATOR_FAIL", "OUTPUT_INDEX_OUT_OF_RANGE",
    "DOI_NOT_IN_MANIFEST", "CITATION_LOCATOR_FAIL", "BACKBONE_GRADE_VIOLATION",
    "SNAPSHOT_MISSING", "DEVIATION_UNNOTED", "ROW_CONFLICT",
}

# schema 层判定不了、须由 ledger-mcp 实现并在 M3 验收的链层用例契约。
CHAIN_CASES: list[str] = [
    "method 拒B·plan_ref 不可解析 → 步4 PLAN_UNBOUND",
    "context 拒B·条目不属当前轮 → 步6 DOI_NOT_IN_MANIFEST",
    "framing 拒B·指向 T3 条目 → 步6 BACKBONE_GRADE_VIOLATION",
    "transition 拒·缺 on_behalf_of_role → 步1 SCHEMA_FAIL（1.4.0 起 schema 可判定）",
    "首行 created_by_role ≠ 凭证 on_behalf_of_role → 步4 TRANSITION_INVALID（R-08）",
]


def sub_codes() -> set[str]:
    return {c for _, g in MATRIX if g for c in g.split("|")}


def all_codes() -> set[str]:
    return sub_codes() | STEP_CODES
