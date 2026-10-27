"""M1 最小闭环（`m1/` 包）：八步校验链 + 六道 rail 的参考实现。

阶段 1 冻结包冻结的是「规格 + 判据」；本包把交付物 §1.3 的**八步校验链**与总体方案 §2
可信门层的**六道 rail**做成可运行、可反例测试的实现，落账对象就是 **ClaimRow 1.2.0**
（内嵌 ClaimCard 1.4.0）。行为验收见 `tools/m1_acceptance.py`（门禁 GATE 6，76 项断言）。

模块划分
--------
* `m1.manifest` —— MANIFEST 注册表 + 正文快照库（步 3 上下文 / 步 6 引用一致性的权威源）。
* `m1.rails`    —— 六道 rail（CitationGate / Provenance / InferenceScope / Compliance / Budget / HITL）。
* `m1.ledger`   —— 账本 + 事件链 + 八步链 + 签发 + WAL 恢复 + 双源对账。

仍未实现（M3 之后的 ledger-mcp 生产件）：多写并发仲裁、远端对象存储、MCP 服务面、
rail 策略热更新、reject_log 落盘。
"""

from m1.ledger import (  # noqa: F401
    CLAIMCARD_VERSION,
    CLAIMROW_VERSION,
    AppendResult,
    ArtifactUnreachable,
    AuditReport,
    CitationLocatorFail,
    DeviationUnnoted,
    EventChainFail,
    ExecutionRejected,
    ExecutionUnresolved,
    FigureHashUnbound,
    HashMismatch,
    Ledger,
    LedgerError,
    ManifestContextMismatch,
    OutputIndexOutOfRange,
    PlanMismatch,
    PlanUnbound,
    RowConflict,
    SchemaFail,
    SimulatedCrash,
    TransitivityFail,
    ValueLocatorFail,
    chain_digest,
    derive_row_id,
    sha256_bytes,
    sha256_file,
    stable_projection,
    validate_card,
    validate_row,
)
from m1.manifest import Entry, Manifest, ManifestError, RunContext, SnapshotStore  # noqa: F401
from m1.rails import (  # noqa: F401
    ALLOW,
    BLOCK,
    RAIL_NAMES,
    WARN,
    RailContext,
    RailDecision,
    blocked,
    codes,
    evaluate,
)

__all__ = [
    "Ledger",
    "Manifest",
    "Entry",
    "RunContext",
    "SnapshotStore",
    "ManifestError",
    "AppendResult",
    "AuditReport",
    "LedgerError",
    "SchemaFail",
    "HashMismatch",
    "ArtifactUnreachable",
    "SimulatedCrash",
    "ExecutionUnresolved",
    "ExecutionRejected",
    "EventChainFail",
    "ManifestContextMismatch",
    "TransitivityFail",
    "PlanUnbound",
    "PlanMismatch",
    "FigureHashUnbound",
    "ValueLocatorFail",
    "OutputIndexOutOfRange",
    "CitationLocatorFail",
    "RowConflict",
    "DeviationUnnoted",
    "derive_row_id",
    "stable_projection",
    "sha256_bytes",
    "sha256_file",
    "chain_digest",
    "validate_card",
    "validate_row",
    "CLAIMCARD_VERSION",
    "CLAIMROW_VERSION",
    "RAIL_NAMES",
    "RailContext",
    "RailDecision",
    "evaluate",
    "blocked",
    "codes",
    "ALLOW",
    "WARN",
    "BLOCK",
]
