"""M1 最小闭环（`m1/` 包）。

阶段 1 冻结包冻结的是「规格 + 判据」；本包是 M1 的参考实现，只做四件事：
hash 绑定、行级幂等、双写 + WAL 先行、双源对账。行为验收见 `tools/m1_acceptance.py`（门禁 GATE 6）。

未实现（M3）：ClaimCard 全量 schema 校验、八步链其余步骤、六道 rail、快照/DOI 校验、audit_event_id 签发。
"""

from m1.ledger import (  # noqa: F401
    AppendResult,
    ArtifactUnreachable,
    AuditReport,
    HashMismatch,
    Ledger,
    LedgerError,
    SimulatedCrash,
    chain_digest,
    derive_row_id,
    sha256_bytes,
    sha256_file,
    stable_projection,
)

__all__ = [
    "Ledger",
    "AppendResult",
    "AuditReport",
    "LedgerError",
    "HashMismatch",
    "ArtifactUnreachable",
    "SimulatedCrash",
    "derive_row_id",
    "stable_projection",
    "sha256_bytes",
    "sha256_file",
    "chain_digest",
]
