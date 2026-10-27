"""六道 rail：上下文装配与声明产出前的策略门（M1 参考实现）。

为什么要在八步链之外再加一层
----------------------------
八步链管的是**事实**（这段文字对应的数值/引用是否真的存在且可比对）；rail 管的是**权限与策略**
（这一轮允许产出哪类声明、这份文献的许可能不能引用、预算够不够、敏感动作是否需要人签）。
两者失败语义不同：八步链失败是「证据不成立」，rail 失败是「本轮不许这么做」。

六道门（与总体方案 §2 可信门层同名）
-----------------------------------
1. `CitationGate`  —— 引用必须落在本轮 MANIFEST；primary 必须有一手快照；framing 只能挂 backbone。
2. `Provenance`    —— result / method 卡必须有脚本哈希与一次可回溯的执行编号。
3. `InferenceScope`—— 声明类型必须在本轮范围内；exploratory 未标偏差给 WARN。
4. `Compliance`    —— 引用文献的许可不得落在禁用清单。
5. `Budget`        —— token / 成本不得超预算。
6. `HITL`          —— framing 类声明需要人类审批人在场。

设计约束
--------
* `evaluate()` **恒返回六条**决策（按 `RAIL_NAMES` 顺序），便于门禁断言「没有哪道门被悄悄跳过」。
* 只读：rail 不写任何存储，也不修改卡片。
* `BLOCK` 表示本轮拒绝；`WARN` 表示放行但要在审计报告里留痕；`ALLOW` 正常。
* 决策码与八步链错误码分开命名（rail 码是策略码，不进冻结的错误码矩阵）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

__all__ = [
    "ALLOW", "WARN", "BLOCK", "RAIL_NAMES", "RailDecision", "RailContext",
    "evaluate", "blocked", "codes",
]

ALLOW = "allow"
WARN = "warn"
BLOCK = "block"

#: 六道门的固定顺序（evaluate 的返回顺序、门禁对偶的基准）
RAIL_NAMES: tuple[str, ...] = (
    "CitationGate",
    "Provenance",
    "InferenceScope",
    "Compliance",
    "Budget",
    "HITL",
)

#: 需要脚本哈希 + 执行编号背书的声明类型
_PROVENANCE_TYPES = ("result", "method")

#: 需要人类审批人在场的声明类型
_HITL_TYPES = ("framing",)


@dataclass(frozen=True)
class RailDecision:
    """单道门的决策。`code` 为策略码（空串表示无问题）。"""

    rail: str
    decision: str
    code: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"rail": self.rail, "decision": self.decision,
                "code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class RailContext:
    """本轮策略上下文（由 RunContext 派生；M1 里由验收/调用方直接构造）。"""

    now: float = 0.0
    allowed_claim_types: tuple[str, ...] = ("result", "method", "context", "framing")
    forbidden_licenses: tuple[str, ...] = ()
    budget_tokens: int = 0          # 0 表示不限额
    spent_tokens: int = 0
    budget_cost: float = 0.0        # 0 表示不限额
    spent_cost: float = 0.0
    human_approver: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"now": self.now, "allowed_claim_types": list(self.allowed_claim_types),
                "forbidden_licenses": list(self.forbidden_licenses),
                "budget_tokens": self.budget_tokens, "spent_tokens": self.spent_tokens,
                "budget_cost": self.budget_cost, "spent_cost": self.spent_cost,
                "human_approver": self.human_approver}


# --------------------------------------------------------------------------- #
# 1. CitationGate
# --------------------------------------------------------------------------- #
def _citation_gate(card: dict[str, Any], manifest: Any | None) -> RailDecision:
    refs: Sequence[dict[str, Any]] = card.get("citation_refs") or []
    framing = card.get("framing_ref")
    if not refs and not framing:
        return RailDecision("CitationGate", ALLOW)

    if manifest is None:
        return RailDecision("CitationGate", BLOCK, "CITATION_GATE_NO_MANIFEST",
                            "带引用但未挂载本轮 MANIFEST")

    for ref in refs:
        doi = str(ref.get("doi", ""))
        entry = manifest.literature(doi)
        if entry is None:
            return RailDecision("CitationGate", BLOCK, "DOI_NOT_IN_MANIFEST",
                                f"{doi} 不在本轮 MANIFEST 文献条目中")
        if ref.get("verification") == "primary":
            if not ref.get("snapshot_ref"):
                return RailDecision("CitationGate", BLOCK, "SNAPSHOT_MISSING",
                                    f"{doi} 声明为 primary 但未带 snapshot_ref")
            if entry.snapshot_ref and ref["snapshot_ref"] != entry.snapshot_ref:
                return RailDecision("CitationGate", BLOCK, "SNAPSHOT_MISSING",
                                    f"{doi} 的快照与 MANIFEST 条目不一致")
        if ref.get("verification") == "survey_transfer":
            survey_doi = str(ref.get("survey_doi", ""))
            survey = manifest.literature(survey_doi)
            if survey is None:
                return RailDecision("CitationGate", BLOCK, "DOI_NOT_IN_MANIFEST",
                                    f"survey_doi {survey_doi} 不在 MANIFEST")
            if survey.role != "backbone":
                return RailDecision("CitationGate", BLOCK, "BACKBONE_GRADE_VIOLATION",
                                    f"survey {survey_doi} 档位为 {survey.role}，不能承载转述")

    if framing is not None:
        survey_doi = str(framing.get("survey_doi", ""))
        entry = manifest.literature(survey_doi)
        if entry is None:
            return RailDecision("CitationGate", BLOCK, "DOI_NOT_IN_MANIFEST",
                                f"framing survey_doi {survey_doi} 不在 MANIFEST")
        if entry.role != "backbone":
            return RailDecision("CitationGate", BLOCK, "BACKBONE_GRADE_VIOLATION",
                                f"framing 指向 {survey_doi}，档位为 {entry.role}（须 backbone）")

    return RailDecision("CitationGate", ALLOW)


# --------------------------------------------------------------------------- #
# 2. Provenance
# --------------------------------------------------------------------------- #
def _provenance(card: dict[str, Any]) -> RailDecision:
    if card.get("claim_type") not in _PROVENANCE_TYPES:
        return RailDecision("Provenance", ALLOW)
    evidence = card.get("evidence") or {}
    for field in ("sandbox_execution_id", "script_hash"):
        if not evidence.get(field):
            return RailDecision("Provenance", BLOCK, "PROVENANCE_UNBOUND",
                                f"{card.get('claim_type')} 卡缺少 {field}")
    return RailDecision("Provenance", ALLOW)


# --------------------------------------------------------------------------- #
# 3. InferenceScope
# --------------------------------------------------------------------------- #
def _inference_scope(card: dict[str, Any], context: RailContext | None) -> RailDecision:
    if context is not None and context.allowed_claim_types:
        if card.get("claim_type") not in context.allowed_claim_types:
            return RailDecision("InferenceScope", BLOCK, "INFERENCE_SCOPE_OUT_OF_SCOPE",
                                f"{card.get('claim_type')} 不在本轮允许范围 "
                                f"{list(context.allowed_claim_types)}")
    if card.get("confidence") == "exploratory":
        lineage = card.get("lineage") or {}
        if not lineage.get("deviation_note"):
            return RailDecision("InferenceScope", WARN, "INFERENCE_SCOPE_UNNOTED",
                                "exploratory 卡未标注 deviation_note")
    return RailDecision("InferenceScope", ALLOW)


# --------------------------------------------------------------------------- #
# 4. Compliance
# --------------------------------------------------------------------------- #
def _compliance(card: dict[str, Any], manifest: Any | None,
                context: RailContext | None) -> RailDecision:
    forbidden: Iterable[str] = (context.forbidden_licenses if context is not None else ())
    forbidden = tuple(forbidden)
    if not forbidden or manifest is None:
        return RailDecision("Compliance", ALLOW)
    dois: list[str] = [str(ref.get("doi", "")) for ref in card.get("citation_refs") or []]
    framing = card.get("framing_ref")
    if framing is not None:
        dois.append(str(framing.get("survey_doi", "")))
    for doi in dois:
        entry = manifest.literature(doi)
        if entry is None or not entry.license:
            continue
        if entry.license in forbidden:
            return RailDecision("Compliance", BLOCK, "COMPLIANCE_LICENSE_FORBIDDEN",
                                f"{doi} 的许可 {entry.license} 在本轮禁用清单")
    return RailDecision("Compliance", ALLOW)


# --------------------------------------------------------------------------- #
# 5. Budget
# --------------------------------------------------------------------------- #
def _budget(context: RailContext | None) -> RailDecision:
    if context is None:
        return RailDecision("Budget", ALLOW)
    if context.budget_tokens and context.spent_tokens > context.budget_tokens:
        return RailDecision("Budget", BLOCK, "BUDGET_EXCEEDED",
                            f"token 已用 {context.spent_tokens} > 预算 {context.budget_tokens}")
    if context.budget_cost and context.spent_cost > context.budget_cost:
        return RailDecision("Budget", BLOCK, "BUDGET_EXCEEDED",
                            f"成本已用 {context.spent_cost} > 预算 {context.budget_cost}")
    return RailDecision("Budget", ALLOW)


# --------------------------------------------------------------------------- #
# 6. HITL
# --------------------------------------------------------------------------- #
def _hitl(card: dict[str, Any], context: RailContext | None) -> RailDecision:
    if card.get("claim_type") in _HITL_TYPES:
        approver = context.human_approver if context is not None else None
        if not approver:
            return RailDecision("HITL", BLOCK, "HITL_APPROVER_MISSING",
                                f"{card.get('claim_type')} 卡需要人类审批人")
    return RailDecision("HITL", ALLOW)


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def evaluate(card: dict[str, Any], *, manifest: Any | None = None,
             context: RailContext | None = None) -> list[RailDecision]:
    """跑六道门，恒返回六条决策（顺序同 `RAIL_NAMES`）。"""
    return [
        _citation_gate(card, manifest),
        _provenance(card),
        _inference_scope(card, context),
        _compliance(card, manifest, context),
        _budget(context),
        _hitl(card, context),
    ]


def blocked(decisions: Iterable[RailDecision]) -> list[RailDecision]:
    """返回 BLOCK 决策（空列表表示放行）。"""
    return [d for d in decisions if d.decision == BLOCK]


def codes(decisions: Iterable[RailDecision]) -> list[str]:
    """返回非空决策码（便于断言与审计留痕）。"""
    return [d.code for d in decisions if d.code]
