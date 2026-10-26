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
# 结构化登记：id 连续（L1–L5），每条绑定「适用通道/规则 → 拦截步 → 错误码 → M3 验收点」。
# 门禁 G3 只校验登记完整性（id 连续、码属八步链、五个典型通道/规则各一），
# 真正的链层执行由 M3 的 ledger-mcp 实现验收——登记即契约，不占 PASS 计数。
CHAIN_CONTRACTS: list[dict[str, str]] = [
    {
        "id": "L1",
        "name": "method 通道：plan_ref 不可解析",
        "rule": "method 卡必须绑定 plan_ref（schema 只判非空，不判可解析）",
        "step": "步4",
        "code": "PLAN_UNBOUND",
        "m3": "ledger-mcp 计划注册表查无该 plan_ref → 拒绝合并并落 PLAN_UNBOUND",
    },
    {
        "id": "L2",
        "name": "context 通道：条目不属当前轮",
        "rule": "context 卡 citation_refs 的 manifest_entry_id 须属本轮 MANIFEST（schema 只判必填）",
        "step": "步6",
        "code": "DOI_NOT_IN_MANIFEST",
        "m3": "本轮 MANIFEST 无该条目 → 拒绝并落 DOI_NOT_IN_MANIFEST",
    },
    {
        "id": "L3",
        "name": "framing 通道：指向 T3 档位条目",
        "rule": "framing 卡 framing_ref 须为 backbone 档（schema 只判必填）",
        "step": "步6",
        "code": "BACKBONE_GRADE_VIOLATION",
        "m3": "档位矩阵校验 framing_ref.curation_grade 非 backbone 档 → 拒绝并落该码",
    },
    {
        "id": "L4",
        "name": "凭证规则：transition 缺 on_behalf_of_role",
        "rule": "to=superseded 必带 on_behalf_of_role（1.4.0 起 schema 已可判定）",
        "step": "步1",
        "code": "SCHEMA_FAIL",
        "m3": "schema 已拦截；M3 只需回归确认链层不复判、不产生第二来源",
    },
    {
        "id": "L5",
        "name": "凭证规则：首行 created_by_role ≠ 凭证 on_behalf_of_role",
        "rule": "R-08 代签一致性（需比对签发凭证，schema 不可判定）",
        "step": "步4",
        "code": "TRANSITION_INVALID",
        "m3": "凭证 rail 的 on_behalf_of_role 与行 lineage.created_by_role 不符 → 落该码",
    },
]

# 供门禁打印与文档口径复用的摘要行（由 CHAIN_CONTRACTS 派生，不手写第二份）。
CHAIN_CASES: list[str] = [
    f"{c['id']} {c['name']} → {c['step']} {c['code']}" for c in CHAIN_CONTRACTS
]


def sub_codes() -> set[str]:
    return {c for _, g in MATRIX if g for c in g.split("|")}


def all_codes() -> set[str]:
    return sub_codes() | STEP_CODES
