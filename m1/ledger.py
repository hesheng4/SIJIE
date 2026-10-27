"""M1 最小闭环：声明落账的参考实现（hash 绑定 + WAL 先行 + 行级幂等 + 双源对账）。

定位
----
阶段 1 冻结包只冻结「schema + 契约 + 反例规格」，本模块是 **M1 的最小可运行参考实现**，
用于把规格里的四件事变成可测行为：

1. **hash 绑定**：声明卡必须携带脚本哈希与产物哈希，落账前逐一重算比对，
   不一致 → `HASH_MISMATCH`；产物缺失 → `ARTIFACT_UNREACHABLE`。
2. **行级幂等**：`row_id = "row_" + JCS(stable_projection).digest16`，
   同一内容重复 append 只落一行、只记一条 rawlog 事件（RFC 8785 canonical 保证跨平台一致）。
3. **双写 + WAL 先行**：写序固定 rawlog → artifacts → 账本；每步前落 WAL，
   进程在任意一步中断后 `recover()` 能把事务补齐或回滚到一致状态。
4. **双源对账**：`audit()` 只读重放，检查链式哈希、序号连续、账本 ↔ rawlog 一一对应、
   产物仍在且哈希未变；不一致分别报 `TAMPER_DETECTED` / `PHANTOM_EVENT` / `UNCOMMITTED_EVENT` /
   `ARTIFACT_MISSING`。

**不是 ledger-mcp**：八步校验链只实现了第 1/4/5 步的 hash 子集，ClaimCard 全量 schema 校验、
六道 rail、快照与 DOI 校验、`audit_event_id` 签发均属 M3；本模块的 `UNCOMMITTED_EVENT`
是 M1 局部码，未登记进 `tools/freeze_codes.py`（M3 前不写入冻结文档）。

目录布局（root 可放在任意路径，测试用临时目录）
-------------------------------------------------
    root/claims/CLAIMS.jsonl         # 只追加账本（唯一写入口的替身）
    root/rawlog/rawlog-0000.jsonl    # 执行事件（原始日志，第二证据源）
    root/artifacts/<sha256 前 2 位>/<12 位>  # 产物内容寻址存储
    root/wal/<row_id>.json           # 事务 WAL（committed 后删除）

退出码约定与其它门禁一致：正常返回 0，断言失败由调用方（tools/m1_acceptance.py）汇总。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import jcs  # noqa: E402  RFC 8785 canonical / digest16（单一事实源）

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

#: 不参与 row_id 派生的易变字段（重放/重算时必须投影掉）。
#: `row_id` 自身是派生结果而非输入，必须排除，否则「读回的行」与「落账前的记录」算不出同一个 id。
VOLATILE = ("row_id", "appended_at", "audit_event_id", "row_seq", "prev_row_hash", "row_hash")


# --------------------------------------------------------------------------- #
# 错误码
# --------------------------------------------------------------------------- #
class LedgerError(Exception):
    """落账失败，`code` 为八步链已登记的错误码或 M1 局部码。"""

    code = "LEDGER_ERROR"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.code)
        if code:
            self.code = code

    def __str__(self) -> str:  # pragma: no cover - 仅用于展示
        return f"{self.code}: {super().__str__()}"


class HashMismatch(LedgerError):
    code = "HASH_MISMATCH"


class ArtifactUnreachable(LedgerError):
    code = "ARTIFACT_UNREACHABLE"


class SimulatedCrash(LedgerError):
    """测试用：在指定阶段中断事务，验证 WAL 恢复。"""

    code = "SIMULATED_CRASH"


# --------------------------------------------------------------------------- #
# 哈希与投影
# --------------------------------------------------------------------------- #
def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def stable_projection(record: dict[str, Any]) -> dict[str, Any]:
    """去掉易变字段后的稳定投影：同内容的两次落账得到同一个 row_id。"""
    return {k: v for k, v in record.items() if k not in VOLATILE}


def derive_row_id(record: dict[str, Any]) -> str:
    """`row_id = "row_" + digest16(JCS(stable_projection))`，与冻结规格 §1.8 同口径。"""
    return "row_" + jcs.digest16(stable_projection(record))


def chain_digest(row: dict[str, Any]) -> str:
    """行级链哈希：覆盖行内全部字段（含 row_seq / prev_row_hash），但不含 row_hash 自身。"""
    body = {k: v for k, v in row.items() if k != "row_hash"}
    return "sha256:" + hashlib.sha256(jcs.canonical(body).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# 原子写
# --------------------------------------------------------------------------- #
def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _append_line(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    with open(path, "ab") as fh:
        fh.write(line.encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw:
            out.append(json.loads(raw))
    return out


def _rewrite_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    data = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    _atomic_write(path, data.encode("utf-8"))


# --------------------------------------------------------------------------- #
# 结果类型
# --------------------------------------------------------------------------- #
@dataclass
class AppendResult:
    row_id: str
    appended: bool          # True = 本次真实落账；False = 命中幂等键
    row_seq: int = 0
    duplicate: bool = False


@dataclass
class AuditReport:
    ok: bool
    rows: int
    findings: list[dict[str, str]] = field(default_factory=list)
    checked_at: float = 0.0

    @property
    def codes(self) -> list[str]:
        return [f["code"] for f in self.findings]


# --------------------------------------------------------------------------- #
# 账本
# --------------------------------------------------------------------------- #
class Ledger:
    """append-only 账本 + rawlog + 产物库 + WAL 的最小实现（单进程）。"""

    def __init__(self, root: str | os.PathLike[str], *, fsync: bool = True) -> None:
        self.root = Path(root)
        self.claims_path = self.root / "claims" / "CLAIMS.jsonl"
        self.rawlog_path = self.root / "rawlog" / "rawlog-0000.jsonl"
        self.artifacts_dir = self.root / "artifacts"
        self.wal_dir = self.root / "wal"
        for d in (self.claims_path.parent, self.rawlog_path.parent, self.artifacts_dir, self.wal_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._fsync = fsync

    # ---------------- 读 ----------------
    def rows(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.claims_path)

    def raw_events(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.rawlog_path)

    def row_ids(self) -> set[str]:
        return {r["row_id"] for r in self.rows()}

    # ---------------- 产物 ----------------
    def store_artifact(self, data: bytes) -> str:
        """内容寻址落盘，返回 `sha256:…` 哈希。"""
        digest = sha256_bytes(data)
        hexpart = digest.split(":", 1)[1]
        target = self.artifacts_dir / hexpart[:2] / hexpart[2:14]
        if target.exists() and sha256_file(target) == digest:
            return digest
        _atomic_write(target, data)
        return digest

    def artifact_path(self, digest: str) -> Path:
        hexpart = digest.split(":", 1)[1]
        return self.artifacts_dir / hexpart[:2] / hexpart[2:14]

    # ---------------- 校验（第 4/5 步 hash 子集）----------------
    def verify(self, record: dict[str, Any]) -> None:
        """重算脚本哈希与产物哈希；不一致即拒绝（不改动任何状态）。"""
        script = record.get("script") or {}
        spath, sdigest = script.get("path"), script.get("sha256")
        if not spath or not sdigest:
            raise HashMismatch("声明卡缺少 script.path / script.sha256")
        p = Path(spath)
        if not p.is_absolute():
            p = (self.root / p).resolve()
        if not p.exists():
            raise ArtifactUnreachable(f"脚本不可达：{p}", code="ARTIFACT_UNREACHABLE")
        if sha256_file(p) != sdigest:
            raise HashMismatch(f"脚本哈希不匹配：{p}")

        evidence = record.get("evidence") or {}
        adigest = evidence.get("artifact_sha256")
        if not adigest:
            raise HashMismatch("evidence.artifact_sha256 必填")
        apath = self.artifact_path(adigest)
        if not apath.exists():
            raise ArtifactUnreachable(f"产物不可达：{adigest}", code="ARTIFACT_UNREACHABLE")
        if sha256_file(apath) != adigest:
            raise HashMismatch(f"产物哈希不匹配：{adigest}")

    # ---------------- 落账 ----------------
    def append(
        self,
        record: dict[str, Any],
        *,
        now: float | None = None,
        crash_after: str | None = None,
    ) -> AppendResult:
        """幂等落账。`crash_after` ∈ {None, "rawlog", "ledger"} 供故障注入测试使用。"""
        row_id = derive_row_id(record)
        existing = {r["row_id"]: r for r in self.rows()}
        if row_id in existing:
            return AppendResult(row_id=row_id, appended=False,
                                row_seq=int(existing[row_id].get("row_seq", 0)), duplicate=True)

        self.verify(record)  # 先校验后落盘：失败不留任何痕迹

        txn = {
            "row_id": row_id,
            "stage": "pending",
            "record": record,
            "created_at": now if now is not None else time.time(),
        }
        wal_path = self.wal_dir / f"{row_id}.json"
        _atomic_write(wal_path, json.dumps(txn, ensure_ascii=False, sort_keys=True).encode("utf-8"))

        # ① rawlog（第二证据源）：同一 row_id 只记一条
        events = self.raw_events()
        if not any(e.get("row_id") == row_id for e in events):
            _append_line(self.rawlog_path, {
                "event_type": "claim.append",
                "row_id": row_id,
                "claim_id": record.get("claim_id"),
                "script_sha256": (record.get("script") or {}).get("sha256"),
                "artifact_sha256": (record.get("evidence") or {}).get("artifact_sha256"),
                "recorded_at": txn["created_at"],
            })
        if crash_after == "rawlog":
            raise SimulatedCrash("rawlog 已写、账本未写（模拟崩溃）")

        txn["stage"] = "rawlog_done"
        _atomic_write(wal_path, json.dumps(txn, ensure_ascii=False, sort_keys=True).encode("utf-8"))

        result = self._commit(txn)
        if crash_after == "ledger":
            raise SimulatedCrash("账本已写、WAL 未清（模拟崩溃）")
        wal_path.unlink(missing_ok=True)
        return result

    def _commit(self, txn: dict[str, Any]) -> AppendResult:
        """把事务落到账本（幂等：已存在同 row_id 直接返回）。"""
        rows = self.rows()
        if any(r["row_id"] == txn["row_id"] for r in rows):
            return AppendResult(row_id=txn["row_id"], appended=False, duplicate=True)
        seq = len(rows) + 1
        row = dict(txn["record"])
        row.update({
            "row_id": txn["row_id"],
            "row_seq": seq,
            "prev_row_hash": rows[-1]["row_hash"] if rows else "",
            "appended_at": txn["created_at"],
        })
        row["row_hash"] = chain_digest(row)
        _append_line(self.claims_path, row)
        return AppendResult(row_id=txn["row_id"], appended=True, row_seq=seq)

    # ---------------- 崩溃恢复 ----------------
    def recover(self) -> dict[str, int]:
        """重放 WAL：rawlog_done → 补账本；pending → 回滚 rawlog 残留；committed → 清 WAL。"""
        stats = {"finished": 0, "rolled_back": 0, "cleaned": 0}
        for wal_path in sorted(self.wal_dir.glob("*.json")):
            txn = json.loads(wal_path.read_text(encoding="utf-8"))
            stage = txn.get("stage")
            if stage == "committed":
                wal_path.unlink(missing_ok=True)
                stats["cleaned"] += 1
            elif stage == "rawlog_done":
                self._commit(txn)
                txn["stage"] = "committed"
                _atomic_write(wal_path, json.dumps(txn, ensure_ascii=False, sort_keys=True).encode("utf-8"))
                wal_path.unlink(missing_ok=True)
                stats["finished"] += 1
            else:  # pending：账本没有该行，rawlog 若有残留需回滚
                events = [e for e in self.raw_events() if e.get("row_id") != txn["row_id"]]
                if len(events) != len(self.raw_events()):
                    _rewrite_jsonl(self.rawlog_path, events)
                wal_path.unlink(missing_ok=True)
                stats["rolled_back"] += 1
        return stats

    # ---------------- 双源对账 ----------------
    def audit(self) -> AuditReport:
        rows = self.rows()
        events = self.raw_events()
        findings: list[dict[str, str]] = []

        prev_hash = ""
        for idx, row in enumerate(rows, start=1):
            if row.get("row_seq") != idx:
                findings.append({"code": "TAMPER_DETECTED",
                                 "detail": f"第 {idx} 行 row_seq={row.get('row_seq')} 不连续"})
            if row.get("prev_row_hash", "") != prev_hash:
                findings.append({"code": "TAMPER_DETECTED",
                                 "detail": f"第 {idx} 行 prev_row_hash 与上一行不衔接"})
            if row.get("row_hash") != chain_digest(row):
                findings.append({"code": "TAMPER_DETECTED",
                                 "detail": f"第 {idx} 行内容与 row_hash 不符（疑似被改写）"})
            if derive_row_id(row) != row.get("row_id"):
                findings.append({"code": "TAMPER_DETECTED",
                                 "detail": f"第 {idx} 行 row_id 与稳定投影不符"})
            prev_hash = row.get("row_hash", "")

        ledger_ids = {r["row_id"] for r in rows}
        raw_ids = {e["row_id"] for e in events}
        for rid in sorted(ledger_ids - raw_ids):
            findings.append({"code": "PHANTOM_EVENT",
                             "detail": f"账本行 {rid} 在 rawlog 中没有对应事件"})
        for rid in sorted(raw_ids - ledger_ids):
            findings.append({"code": "UNCOMMITTED_EVENT",
                             "detail": f"rawlog 事件 {rid} 未落账（疑似中断未恢复）"})

        for row in rows:
            adigest = (row.get("evidence") or {}).get("artifact_sha256")
            apath = self.artifact_path(adigest) if adigest else None
            if apath is None or not apath.exists() or sha256_file(apath) != adigest:
                findings.append({"code": "ARTIFACT_MISSING",
                                 "detail": f"行 {row['row_id']} 的产物缺失或已变"})

        return AuditReport(ok=not findings, rows=len(rows), findings=findings, checked_at=time.time())

    # ---------------- 只读重放 ----------------
    def replay(self) -> list[dict[str, Any]]:
        """按 row_seq 顺序返回稳定投影（可与非 JCS 实现对照，验证确定性）。"""
        rows = sorted(self.rows(), key=lambda r: int(r.get("row_seq", 0)))
        return [stable_projection(r) for r in rows]
