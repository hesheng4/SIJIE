"""M1 最小闭环（`m1/` 包）。

阶段 1 冻结包冻结的是「规格 + 判据」；本包是 M1 的参考实现，落账对象就是 **ClaimRow 1.2.0**
（内嵌 ClaimCard 1.4.0），做五件事：步 1 schema 校验、步 4 hash 绑定（子集）、行级幂等、
双写 + WAL 先行、双源对账。行为验收见 `tools/m1_acceptance.py`（门禁 GATE 6）。

未实现（M3）：八步链其余步骤（步 2/3/5/6/7/8）、六道 rail、快照/DOI 校验、audit_event_id 签发。
"""

from m1.ledger import (  # noqa: F401
    CLAIMCARD_VERSION,
    CLAIMROW_VERSION,
    AppendResult,
    ArtifactUnreachable,
    AuditReport,
    HashMismatch,
    Ledger,
    LedgerError,
    SchemaFail,
    SimulatedCrash,
    chain_digest,
    derive_row_id,
    sha256_bytes,
    sha256_file,
    stable_projection,
    validate_card,
    validate_row,
)

__all__ = [
    "Ledger",
    "AppendResult",
    "AuditReport",
    "LedgerError",
    "SchemaFail",
    "HashMismatch",
    "ArtifactUnreachable",
    "SimulatedCrash",
    "derive_row_id",
    "stable_projection",
    "sha256_bytes",
    "sha256_file",
    "chain_digest",
    "validate_card",
    "validate_row",
    "CLAIMCARD_VERSION",
    "CLAIMROW_VERSION",
]
