"""M1 最小闭环 v2：声明落账的参考实现（步 1 schema + 步 4 hash + 幂等 + WAL + 双源对账）。

定位
----
阶段 1 冻结包冻结「schema + 契约 + 反例规格」；本模块是 **M1 的最小可运行参考实现**，
用真实 schema 把规格变成可测行为。落账对象就是 **ClaimRow 1.2.0**（内嵌 ClaimCard 1.4.0），
不再自造简化结构。

已实现（对齐交付物 §1.3 八步链的两个节点）
-------------------------------------------
1. **步 1 · schema**：ClaimCard 1.4.0 与 ClaimRow 1.2.0 全量校验（含 7 条 allOf 规则、11 角色词表、
   `date-time` 自实现格式断言），失败 → `SCHEMA_FAIL`。
2. **步 4 · hash 绑定（子集）**：`card.evidence.script_hash` 必须命中脚本库且内容一致；
   `card.evidence.output_hashes[]` 必须命中产物库且内容一致 → 否则 `HASH_MISMATCH` / `ARTIFACT_UNREACHABLE`。
3. **行级幂等**：`row_id = "row_" + JCS(stable_projection).digest16`，
   稳定投影 = 去掉 `row_id / row_seq / appended_at / audit_event_id / row_hash` 后的行。
4. **双写 + WAL 先行**：写序 rawlog → artifacts → 账本；每步前落 `wal/<row_id>.json`，
   `recover()` 回滚 pending、补齐 rawlog_done。
5. **双源对账**：`audit()` 校验链式 `row_hash`、`row_seq` 连续、`row_id` 可重新派生、
   账本 ↔ rawlog 双射、产物仍在。

未实现（M3）
------------
步 2（执行溯源/EXEC_*）、步 3（MANIFEST 上下文/传递性）、步 5（数值 locator）、步 6（DOI/CITATION/
BACKBONE/SNAPSHOT）、步 7（偏差）、步 8（ROW_CONFLICT 的多写并发仲裁）、六道 rail 运行时、`audit_event_id` 签发。
本模块的 `UNCOMMITTED_EVENT` / `ARTIFACT_MISSING` 是 M1 局部对账码，未登记进 `freeze_codes.py`，
故不写入冻结文档（避免文档与码表漂移）。

目录布局（root 任意，测试用临时目录）
-------------------------------------
    root/claims/CLAIMS.jsonl          # 只追加账本（ClaimRow 1.2.0）
    root/rawlog/rawlog-0000.jsonl     # 执行事件（第二证据源）
    root/artifacts/<sha256:2>/<:14>   # 产物内容寻址存储
    root/scripts/<sha256:2>/<:14>     # 脚本内容寻址存储
    root/wal/<row_id>.json            # 事务 WAL（committed 后删除）
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import jcs  # noqa: E402  RFC 8785 canonical / digest16（单一事实源）

try:  # jsonschema 是硬依赖（与冻结门禁一致）
    import jsonschema
    from jsonschema import Draft7Validator, FormatChecker
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"m1.ledger: 缺少依赖 jsonschema（{exc}）") from exc

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
    "chain_digest",
    "sha256_bytes",
    "sha256_file",
    "CLAIMCARD_VERSION",
    "CLAIMROW_VERSION",
]

CLAIMCARD_VERSION = "1.4.0"
CLAIMROW_VERSION = "1.2.0"
SCHEMAS_DIR = ROOT / "schemas"

#: 不参与 row_id 派生的易变字段。`row_id` 自身是派生结果而非输入，必须排除，
#: 否则「落账前的行」与「读回的行」算不出同一个 id。
VOLATILE = ("row_id", "row_seq", "appended_at", "audit_event_id",
            "prev_row_hash", "row_hash")


# --------------------------------------------------------------------------- #
# 错误码
# --------------------------------------------------------------------------- #
class LedgerError(Exception):
    code = "LEDGER_ERROR"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.code)
        if code:
            self.code = code

    def __str__(self) -> str:
        return f"{self.code}: {super().__str__()}"


class SchemaFail(LedgerError):
    code = "SCHEMA_FAIL"


class HashMismatch(LedgerError):
    code = "HASH_MISMATCH"


class ArtifactUnreachable(LedgerError):
    code = "ARTIFACT_UNREACHABLE"


class SimulatedCrash(LedgerError):
    code = "SIMULATED_CRASH"


# --------------------------------------------------------------------------- #
# 哈希 / 投影 / 时间
# --------------------------------------------------------------------------- #
def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def stable_projection(row: dict[str, Any]) -> dict[str, Any]:
    """去掉易变字段后的稳定投影：同内容的两次落账得到同一个 row_id。"""
    return {k: v for k, v in row.items() if k not in VOLATILE}


def derive_row_id(row: dict[str, Any]) -> str:
    """`row_id = "row_" + digest16(JCS(stable_projection))`（冻结规格 §1.8 同口径）。"""
    return "row_" + jcs.digest16(stable_projection(row))


def chain_digest(row: dict[str, Any]) -> str:
    """行级链哈希：覆盖行内全部字段（含 row_seq / prev_row_hash），但不含 row_hash 自身。"""
    body = {k: v for k, v in row.items() if k != "row_hash"}
    return "sha256:" + hashlib.sha256(jcs.canonical(body).encode("utf-8")).hexdigest()


def _iso(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _audit_event_id(row_id: str) -> str:
    """确定性事件 id（幂等重放得到同一个）；M3 改为 ledger-mcp 签发。"""
    return "evt_" + jcs.digest16({"row_id": row_id, "kind": "claim.append"})


def _self_check_datetime(value: str) -> bool:
    """本机常缺 rfc3339-validator，`date-time` 断言会静默失效，故自实现并强制注入。

    注意：jsonschema 的 FormatChecker 以「返回真值」判定通过，返回 None 会被当作失败。
    """
    if not isinstance(value, str):
        raise ValueError("date-time 必须是字符串")
    dt = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))  # 非法值抛 ValueError
    if dt.tzinfo is None:
        raise ValueError("date-time 必须带时区")
    return True


# --------------------------------------------------------------------------- #
# schema 校验器（进程内单例，只读 schemas/）
# --------------------------------------------------------------------------- #
_FMT = FormatChecker()
_FMT.checkers["date-time"] = (_self_check_datetime, (ValueError,))


def _load_validator(filename: str):
    path = SCHEMAS_DIR / filename
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema, format_checker=_FMT)


_VALIDATORS = {
    "claimcard": _load_validator(f"claimcard-{CLAIMCARD_VERSION}.json"),
    "claimrow": _load_validator(f"claimrow-{CLAIMROW_VERSION}.json"),
}

#: ClaimRow 1.2.0 的冻结字段集（用于把 M1 扩展字段隔离在 schema 校验之外）
_CLAIMROW_PROPS = set(
    json.loads((SCHEMAS_DIR / f"claimrow-{CLAIMROW_VERSION}.json").read_text(encoding="utf-8"))["properties"]
)


def validate_card(card: dict[str, Any]) -> None:
    """步 1（ClaimCard）：全量 schema + 三条 1.4.0 规则。"""
    errors = sorted(_VALIDATORS["claimcard"].iter_errors(card), key=lambda e: e.path)
    if errors:
        first = errors[0]
        raise SchemaFail(f"ClaimCard 校验失败：{first.message}（{list(first.path)}）")


def validate_row(row: dict[str, Any]) -> None:
    """步 1（ClaimRow）：复合 schema（内嵌 ClaimCard 全文）+ 版本绑定。

    冻结的 ClaimRow 1.2.0 没有链式完整性字段，M1 只把它当作**扩展**（`prev_row_hash` /
    `row_hash`）而不是改冻结版本，因此校验时按冻结字段视图校验，扩展字段由 `audit()` 复算。
    """
    view = {k: v for k, v in row.items() if k in _CLAIMROW_PROPS}
    errors = sorted(_VALIDATORS["claimrow"].iter_errors(view), key=lambda e: e.path)
    if errors:
        first = errors[0]
        raise SchemaFail(f"ClaimRow 校验失败：{first.message}（{list(first.path)}）")


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
    return [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]


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
    """append-only 账本 + rawlog + 产物/脚本库 + WAL 的最小实现（单进程）。"""

    def __init__(self, root: str | os.PathLike[str], *, fsync: bool = True) -> None:
        self.root = Path(root)
        self.claims_path = self.root / "claims" / "CLAIMS.jsonl"
        self.rawlog_path = self.root / "rawlog" / "rawlog-0000.jsonl"
        self.artifacts_dir = self.root / "artifacts"
        self.scripts_dir = self.root / "scripts"
        self.wal_dir = self.root / "wal"
        for d in (self.claims_path.parent, self.rawlog_path.parent,
                  self.artifacts_dir, self.scripts_dir, self.wal_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._fsync = fsync

    # ---------------- 读 ----------------
    def rows(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.claims_path)

    def raw_events(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.rawlog_path)

    # ---------------- 内容寻址存储 ----------------
    @staticmethod
    def _blob_path(base: Path, digest: str) -> Path:
        hexpart = digest.split(":", 1)[1]
        return base / hexpart[:2] / hexpart[2:14]

    def store_artifact(self, data: bytes) -> str:
        """产物落盘（内容寻址），返回 `sha256:…`。"""
        digest = sha256_bytes(data)
        self._put_blob(self.artifacts_dir, digest, data)
        return digest

    def store_script(self, data: bytes) -> str:
        """脚本落盘（内容寻址），返回 `sha256:…`。"""
        digest = sha256_bytes(data)
        self._put_blob(self.scripts_dir, digest, data)
        return digest

    def _put_blob(self, base: Path, digest: str, data: bytes) -> None:
        target = self._blob_path(base, digest)
        if target.exists() and sha256_file(target) == digest:
            return
        _atomic_write(target, data)

    def artifact_path(self, digest: str) -> Path:
        return self._blob_path(self.artifacts_dir, digest)

    def script_path(self, digest: str) -> Path:
        return self._blob_path(self.scripts_dir, digest)

    # ---------------- 步 4：hash 绑定（子集）----------------
    def verify_binding(self, card: dict[str, Any]) -> None:
        """重算脚本哈希与产物哈希；不一致即拒绝（不改动任何状态）。"""
        evidence = card.get("evidence")
        if not evidence:  # context / framing 卡按 schema 不允许 evidence
            return
        script_hash = evidence.get("script_hash")
        if script_hash:
            path = self.script_path(script_hash)
            if not path.exists():
                raise ArtifactUnreachable(f"脚本不可达：{script_hash}")
            if sha256_file(path) != script_hash:
                raise HashMismatch(f"脚本哈希不匹配：{script_hash}")
        for digest in evidence.get("output_hashes") or []:
            path = self.artifact_path(digest)
            if not path.exists():
                raise ArtifactUnreachable(f"产物不可达：{digest}")
            if sha256_file(path) != digest:
                raise HashMismatch(f"产物哈希不匹配：{digest}")

    # ---------------- 落账 ----------------
    def append(
        self,
        card: dict[str, Any],
        *,
        manifest_version: str = "MANIFEST#0",
        venue_profile_version: str = "vp-2026.10",
        now: float | None = None,
        crash_after: str | None = None,
    ) -> AppendResult:
        """幂等落账。`crash_after` ∈ {None, "rawlog", "ledger"} 供故障注入测试使用。"""
        stub = {
            "claimcard_schema_version": CLAIMCARD_VERSION,
            "card": card,
            "manifest_version": manifest_version,
            "venue_profile_version": venue_profile_version,
        }
        row_id = derive_row_id(stub)
        existing = {r["row_id"]: r for r in self.rows()}
        if row_id in existing:
            return AppendResult(row_id=row_id, appended=False,
                                row_seq=int(existing[row_id].get("row_seq", 0)), duplicate=True)

        # 步 1 schema → 步 4 hash：先校验后落盘，失败不留痕迹
        validate_card(card)
        self.verify_binding(card)

        ts = now if now is not None else time.time()
        rows = self.rows()
        row: dict[str, Any] = dict(stub)
        row.update({
            "row_id": row_id,
            "row_seq": len(rows) + 1,
            "appended_at": _iso(ts),
            "audit_event_id": _audit_event_id(row_id),
            "prev_row_hash": rows[-1]["row_hash"] if rows else "",
        })
        row["row_hash"] = chain_digest(row)
        validate_row(row)  # 落账前再按 ClaimRow 复合 schema 复核一次

        txn = {"row_id": row_id, "stage": "pending", "row": row, "created_at": ts}
        wal_path = self.wal_dir / f"{row_id}.json"
        _atomic_write(wal_path, json.dumps(txn, ensure_ascii=False, sort_keys=True).encode("utf-8"))

        # ① rawlog（第二证据源）：同一 row_id 只记一条
        if not any(e.get("row_id") == row_id for e in self.raw_events()):
            evidence = card.get("evidence") or {}
            _append_line(self.rawlog_path, {
                "event_type": "claim.append",
                "row_id": row_id,
                "claim_id": card.get("claim_id"),
                "claim_type": card.get("claim_type"),
                "script_hash": evidence.get("script_hash"),
                "output_hashes": evidence.get("output_hashes") or [],
                "recorded_at": ts,
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
        if any(r["row_id"] == txn["row_id"] for r in self.rows()):
            return AppendResult(row_id=txn["row_id"], appended=False, duplicate=True)
        _append_line(self.claims_path, txn["row"])
        return AppendResult(row_id=txn["row_id"], appended=True, row_seq=txn["row"]["row_seq"])

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
                wal_path.unlink(missing_ok=True)
                stats["finished"] += 1
            else:  # pending：账本没有该行，rawlog 若有残留需回滚
                events = self.raw_events()
                kept = [e for e in events if e.get("row_id") != txn["row_id"]]
                if len(kept) != len(events):
                    _rewrite_jsonl(self.rawlog_path, kept)
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
            evidence = (row.get("card") or {}).get("evidence") or {}
            digests = list(evidence.get("output_hashes") or [])
            if evidence.get("script_hash"):
                digests.append(evidence["script_hash"])
            for digest in digests:
                base = self.scripts_dir if digest == evidence.get("script_hash") else self.artifacts_dir
                path = self._blob_path(base, digest)
                if not path.exists() or sha256_file(path) != digest:
                    findings.append({"code": "ARTIFACT_MISSING",
                                     "detail": f"行 {row['row_id']} 的产物/脚本缺失或已变：{digest}"})

        return AuditReport(ok=not findings, rows=len(rows), findings=findings, checked_at=time.time())

    # ---------------- 只读重放 ----------------
    def replay(self) -> list[dict[str, Any]]:
        """按 row_seq 顺序返回稳定投影（可独立复算，验证确定性）。"""
        rows = sorted(self.rows(), key=lambda r: int(r.get("row_seq", 0)))
        return [stable_projection(r) for r in rows]
