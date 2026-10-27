"""M1 最小闭环 v3：八步校验链参考实现（步 1–8 全部落地，rail 见 `m1/rails.py`）。

定位
----
阶段 1 冻结包冻结「schema + 契约 + 反例规格」。本模块把交付物 §1.3 的**八步校验链**做成
可运行、可反例测试的实现，落账对象就是真实 `ClaimRow 1.2.0`（内嵌 `ClaimCard 1.4.0`）。

| 步 | 本模块实现 | 失败码 |
|---|---|---|
| 1 | ClaimCard / ClaimRow 全量 schema（含 7 条 allOf 规则、11 角色词表、`date-time` 自实现） | `SCHEMA_FAIL` |
| 2 | 执行登记与**事件链验算**（checkpoint 每 1000 事件；execution 必须 completed 且审计可用） | `EXEC_UNRESOLVED` / `EXEC_REJECTED` / `EXEC_CHAIN_FAIL` |
| 3 | MANIFEST 上下文：`manifest_version` 必须等于本轮 RunContext；`data_refs` 必属数据条目且哈希一致 | `MANIFEST_CONTEXT_MISMATCH` / `TRANSPORTIVITY_FAIL` |
| 4 | hash 一致：脚本库 / 产物库重算；`plan_ref` 解析到 PlanItem 且 `expected_script_hash` 相符 | `HASH_MISMATCH` / `ARTIFACT_UNREACHABLE` / `PLAN_UNBOUND` / `PLAN_MISMATCH` / `FIGURE_HASH_UNBOUND` |
| 5 | 产物按 pointer 定位取值并与声明值比较（exact 按 csv_cast 全等；float_rel 按容差） | `VALUE_LOCATOR_FAIL` / `OUTPUT_INDEX_OUT_OF_RANGE` |
| 6 | 引用一致性：DOI 属 MANIFEST 文献条目、locator 可解析、primary 带快照、转述的 survey 必为 backbone、framing 必为 backbone | `DOI_NOT_IN_MANIFEST` / `CITATION_LOCATOR_FAIL` / `BACKBONE_GRADE_VIOLATION` / `SNAPSHOT_MISSING` |
| 7 | `exploratory` 必带 `deviation_note` | `DEVIATION_UNNOTED` |
| 8 | 落账；`row_id` 幂等；序号被占且不同行 → 冲突 | `ROW_CONFLICT` |

`audit_event_id` 由 **HMAC 签发**（密钥持久化在 `root/audit_key`，同密钥下确定⇒幂等）：
既能防伪造，又保证重放得到同一 id。

目录布局
--------
    root/claims/CLAIMS.jsonl          只追加账本（ClaimRow 1.2.0）
    root/rawlog/rawlog-0000.jsonl     事件链（第二证据源；含 execution 事件）
    root/rawlog/checkpoint.json       事件链 checkpoint（步 2 验算起点）
    root/artifacts/<sha:2>/<:14>      产物内容寻址库
    root/scripts/<sha:2>/<:14>        脚本内容寻址库
    root/snapshots/<sha:2>/<:14>      正文快照库（步 6）
    root/audit_key                    事件签发密钥
    root/wal/<row_id>.json            事务 WAL

未实现（M3 之后的 ledger-mcp 生产件）：多写并发仲裁、远端对象存储、MCP 服务面、rail 的策略热更新。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import jcs  # noqa: E402  RFC 8785 canonical / digest16

from m1.manifest import Manifest, ManifestError, RunContext, SnapshotStore, sha256_text  # noqa: E402

try:  # jsonschema 是硬依赖（与冻结门禁一致）
    import jsonschema  # noqa: F401
    from jsonschema import Draft7Validator, FormatChecker
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"m1.ledger: 缺少依赖 jsonschema（{exc}）") from exc

__all__ = [
    "Ledger", "AppendResult", "AuditReport", "LedgerError", "SchemaFail", "HashMismatch",
    "ArtifactUnreachable", "SimulatedCrash", "ExecutionUnresolved", "ExecutionRejected",
    "EventChainFail", "ManifestContextMismatch", "TransitivityFail", "PlanUnbound",
    "PlanMismatch", "FigureHashUnbound", "ValueLocatorFail", "OutputIndexOutOfRange",
    "CitationLocatorFail", "RowConflict", "DeviationUnnoted", "derive_row_id",
    "stable_projection", "chain_digest", "sha256_bytes", "sha256_file",
    "CLAIMCARD_VERSION", "CLAIMROW_VERSION",
]

CLAIMCARD_VERSION = "1.4.0"
CLAIMROW_VERSION = "1.2.0"
SCHEMAS_DIR = ROOT / "schemas"

#: 不参与 row_id 派生的易变字段（row_id 是派生结果而非输入；*_hash 由前序行决定）。
VOLATILE = ("row_id", "row_seq", "appended_at", "audit_event_id",
            "prev_row_hash", "row_hash")


# --------------------------------------------------------------------------- #
# 错误码（与冻结八步链同名，便于门禁 G3 对偶）
# --------------------------------------------------------------------------- #
class LedgerError(Exception):
    code = "LEDGER_ERROR"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.code)
        if code:
            self.code = code

    def __str__(self) -> str:
        return f"{self.code}: {super().__str__() if super().__str__() != self.code else ''}".rstrip(": ")


class SchemaFail(LedgerError):
    code = "SCHEMA_FAIL"


class ExecutionUnresolved(LedgerError):
    code = "EXEC_UNRESOLVED"


class ExecutionRejected(LedgerError):
    code = "EXEC_REJECTED"


class EventChainFail(LedgerError):
    code = "EXEC_CHAIN_FAIL"


class ManifestContextMismatch(LedgerError):
    code = "MANIFEST_CONTEXT_MISMATCH"


class TransitivityFail(LedgerError):
    code = "TRANSPORTIVITY_FAIL"


class HashMismatch(LedgerError):
    code = "HASH_MISMATCH"


class ArtifactUnreachable(LedgerError):
    code = "ARTIFACT_UNREACHABLE"


class PlanUnbound(LedgerError):
    code = "PLAN_UNBOUND"


class PlanMismatch(LedgerError):
    code = "PLAN_MISMATCH"


class FigureHashUnbound(LedgerError):
    code = "FIGURE_HASH_UNBOUND"


class ValueLocatorFail(LedgerError):
    code = "VALUE_LOCATOR_FAIL"


class OutputIndexOutOfRange(LedgerError):
    code = "OUTPUT_INDEX_OUT_OF_RANGE"


class CitationLocatorFail(LedgerError):
    code = "CITATION_LOCATOR_FAIL"


class RowConflict(LedgerError):
    code = "ROW_CONFLICT"


class DeviationUnnoted(LedgerError):
    code = "DEVIATION_UNNOTED"


class SimulatedCrash(LedgerError):
    code = "SIMULATED_CRASH"


#: ManifestError 的冻结码 → 本模块异常类（步 3/6 抛出）
_MANIFEST_ERRORS = {
    "MANIFEST_CONTEXT_MISMATCH": ManifestContextMismatch,
    "TRANSPORTIVITY_FAIL": TransitivityFail,
    "DOI_NOT_IN_MANIFEST": LedgerError,
    "CITATION_LOCATOR_FAIL": CitationLocatorFail,
    "BACKBONE_GRADE_VIOLATION": LedgerError,
    "SNAPSHOT_MISSING": LedgerError,
}

#: 冻结码（用于文档/门禁对偶，见 tools/freeze_codes.py::STEP_CODES）
STEP_CODES_IMPLEMENTED = (
    "SCHEMA_FAIL", "EXEC_UNRESOLVED", "EXEC_REJECTED", "EXEC_CHAIN_FAIL",
    "MANIFEST_CONTEXT_MISMATCH", "TRANSPORTIVITY_FAIL",
    "HASH_MISMATCH", "ARTIFACT_UNREACHABLE", "PLAN_UNBOUND", "PLAN_MISMATCH",
    "FIGURE_HASH_UNBOUND", "VALUE_LOCATOR_FAIL", "OUTPUT_INDEX_OUT_OF_RANGE",
    "DOI_NOT_IN_MANIFEST", "CITATION_LOCATOR_FAIL", "BACKBONE_GRADE_VIOLATION",
    "SNAPSHOT_MISSING", "DEVIATION_UNNOTED", "ROW_CONFLICT",
)


def _as_ledger_error(exc: ManifestError) -> LedgerError:
    cls = _MANIFEST_ERRORS.get(exc.code, LedgerError)
    return cls(str(exc).split(":", 1)[-1].strip(), code=exc.code)


# --------------------------------------------------------------------------- #
# 哈希 / 投影 / 时间 / 签名
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


def event_digest(event: dict[str, Any]) -> str:
    body = {k: v for k, v in event.items() if k != "event_hash"}
    return "sha256:" + hashlib.sha256(jcs.canonical(body).encode("utf-8")).hexdigest()


def _iso(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
# schema 校验器
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
_CLAIMROW_PROPS = set(
    json.loads((SCHEMAS_DIR / f"claimrow-{CLAIMROW_VERSION}.json").read_text(encoding="utf-8"))["properties"]
)


def validate_card(card: dict[str, Any]) -> None:
    errors = sorted(_VALIDATORS["claimcard"].iter_errors(card), key=lambda e: e.path)
    if errors:
        first = errors[0]
        raise SchemaFail(f"ClaimCard 校验失败：{first.message}（{list(first.path)}）")


def validate_row(row: dict[str, Any]) -> None:
    """行按冻结字段视图校验（`prev_row_hash`/`row_hash` 是 M1 扩展，不进冻结 schema）。"""
    view = {k: v for k, v in row.items() if k in _CLAIMROW_PROPS}
    errors = sorted(_VALIDATORS["claimrow"].iter_errors(view), key=lambda e: e.path)
    if errors:
        first = errors[0]
        raise SchemaFail(f"ClaimRow 校验失败：{first.message}（{list(first.path)}）")


# --------------------------------------------------------------------------- #
# 原子写 / JSONL
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
    appended: bool
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
# 值定位（步 5）
# --------------------------------------------------------------------------- #
def _csv_cast(text: str) -> Any:
    """把产物里的文本按最保守规则转型：整数→int、浮点→float、true/false→bool、其余→str。"""
    stripped = text.strip()
    for caster in (int, float):
        try:
            return caster(stripped)
        except ValueError:
            continue
    if stripped.lower() in ("true", "false"):
        return stripped.lower() == "true"
    return stripped


def _resolve_pointer(payload: bytes, pointer: str) -> Any:
    """支持 RFC 6901 JSON pointer（`/a/b/0`）与 CSV 定位（`csv:<列名>[:<行号>]`，行号默认 0）。"""
    if pointer.startswith("csv:"):
        parts = pointer[4:].split(":")
        column = parts[0]
        row_index = int(parts[1]) if len(parts) > 1 else 0
        lines = [ln for ln in payload.decode("utf-8").splitlines() if ln.strip()]
        if not lines:
            raise ValueLocatorFail(f"CSV 产物为空：{pointer}")
        header = [cell.strip() for cell in lines[0].split(",")]
        if column not in header:
            raise ValueLocatorFail(f"CSV 列 {column} 不存在（表头 {header}）")
        body = lines[1:]
        if row_index >= len(body):
            raise ValueLocatorFail(f"CSV 行 {row_index} 越界（共 {len(body)} 行）")
        cells = [cell.strip() for cell in body[row_index].split(",")]
        return _csv_cast(cells[header.index(column)])

    data = json.loads(payload.decode("utf-8"))
    node = data
    if pointer in ("", "/"):
        return node
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict):
            node = node[token]
        else:  # pragma: no cover - 指针穿到标量
            raise ValueLocatorFail(f"指针 {pointer} 穿过标量")
    return node


def _compare(declared: Any, found: Any, comparison: str, tolerance: float | None) -> bool:
    if comparison == "exact":
        return declared == found
    if comparison == "float_rel":
        if tolerance is None:
            return False
        a, b = float(declared), float(found)
        if not all(map(_is_finite, (a, b))):
            return False
        return abs(a - b) <= tolerance * max(1.0, abs(b))
    return False


def _is_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


# --------------------------------------------------------------------------- #
# 账本
# --------------------------------------------------------------------------- #
class Ledger:
    """append-only 账本 + 事件链 + 八步校验链的最小实现（单进程）。"""

    CHECKPOINT_EVERY = 1000

    def __init__(self, root: str | os.PathLike[str], *, fsync: bool = True) -> None:
        self.root = Path(root)
        self.claims_path = self.root / "claims" / "CLAIMS.jsonl"
        self.rawlog_path = self.root / "rawlog" / "rawlog-0000.jsonl"
        self.checkpoint_path = self.root / "rawlog" / "checkpoint.json"
        self.artifacts_dir = self.root / "artifacts"
        self.scripts_dir = self.root / "scripts"
        self.wal_dir = self.root / "wal"
        self.plans_path = self.root / "plans.json"
        self.snapshots = SnapshotStore(self.root / "snapshots")
        for d in (self.claims_path.parent, self.rawlog_path.parent,
                  self.artifacts_dir, self.scripts_dir, self.wal_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._fsync = fsync
        self.audit_key = self._load_or_create_key()

    # ---------------- 签发密钥（audit_event_id / event_id）----------------
    def _load_or_create_key(self) -> bytes:
        path = self.root / "audit_key"
        if path.exists():
            return bytes.fromhex(path.read_text(encoding="ascii").strip())
        key = os.urandom(32)
        _atomic_write(path, key.hex().encode("ascii"))
        return key

    def _sign(self, purpose: str, subject: str) -> str:
        """HMAC 签发 16 位十六进制事件 id：防伪造，且同密钥下确定 ⇒ 重放幂等。"""
        mac = hmac.new(self.audit_key, f"{purpose}|{subject}".encode("utf-8"), hashlib.sha256)
        return "evt_" + mac.hexdigest()[:16]

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

    def _put_blob(self, base: Path, digest: str, data: bytes) -> None:
        target = self._blob_path(base, digest)
        if target.exists() and sha256_file(target) == digest:
            return
        _atomic_write(target, data)

    def store_artifact(self, data: bytes) -> str:
        digest = sha256_bytes(data)
        self._put_blob(self.artifacts_dir, digest, data)
        return digest

    def store_script(self, data: bytes) -> str:
        digest = sha256_bytes(data)
        self._put_blob(self.scripts_dir, digest, data)
        return digest

    def store_snapshot(self, text: str) -> str:
        return self.snapshots.put(text)

    def artifact_path(self, digest: str) -> Path:
        return self._blob_path(self.artifacts_dir, digest)

    def script_path(self, digest: str) -> Path:
        return self._blob_path(self.scripts_dir, digest)

    # ---------------- 计划（步 4 的 plan_ref）----------------
    def register_plan(self, plan_item_id: str, expected_script_hash: str) -> None:
        plans = self._plans()
        plans[plan_item_id] = expected_script_hash
        _atomic_write(self.plans_path,
                      json.dumps(plans, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"))

    def _plans(self) -> dict[str, str]:
        if not self.plans_path.exists():
            return {}
        return json.loads(self.plans_path.read_text(encoding="utf-8"))

    # ---------------- 事件链（步 2）----------------
    def _last_event_hash(self) -> str:
        events = self.raw_events()
        return events[-1]["event_hash"] if events else ""

    def record_execution(self, execution_id: str, *, status: str = "completed",
                         audit_status: str = "available", now: float | None = None) -> dict[str, Any]:
        """登记一次执行（步 2 的权威源）。同一 execution_id 重复登记返回已有事件（幂等）。"""
        for event in self.raw_events():
            if event.get("event_type") == "execution" and event.get("execution_id") == execution_id:
                return event
        ts = now if now is not None else time.time()
        event = {
            "event_type": "execution",
            "event_id": self._sign("execution", execution_id),
            "execution_id": execution_id,
            "status": status,
            "audit_status": audit_status,
            "recorded_at": ts,
            "prev_event_hash": self._last_event_hash(),
        }
        event["event_hash"] = event_digest(event)
        _append_line(self.rawlog_path, event)
        self._maybe_checkpoint()
        return event

    def _maybe_checkpoint(self) -> None:
        events = self.raw_events()
        if len(events) and len(events) % self.CHECKPOINT_EVERY == 0:
            _atomic_write(self.checkpoint_path, json.dumps(
                {"count": len(events), "last_hash": events[-1]["event_hash"]},
                ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def verify_event_chain(self) -> None:
        """从最近 checkpoint 验到链尾（修 P1「全链 O(N²)」）。失败抛 `EXEC_CHAIN_FAIL`。"""
        events = self.raw_events()
        start, prev = 0, ""
        if self.checkpoint_path.exists():
            cp = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            start, prev = int(cp["count"]), cp["last_hash"]
            if start > len(events):
                raise EventChainFail("checkpoint 计数超过事件总数（原始日志被截断）")
        for idx in range(start, len(events)):
            event = events[idx]
            if event.get("prev_event_hash", "") != prev:
                raise EventChainFail(f"第 {idx + 1} 个事件 prev_event_hash 断链")
            if event_digest(event) != event.get("event_hash"):
                raise EventChainFail(f"第 {idx + 1} 个事件内容与 event_hash 不符（疑似被改写）")
            expected = self._sign(event["event_type"], event.get("execution_id") or event.get("row_id", ""))
            if event.get("event_id") != expected:
                raise EventChainFail(f"第 {idx + 1} 个事件签发不符（event_id 非本账本签发）")
            prev = event["event_hash"]

    # ---------------- 步 2：执行溯源 ----------------
    def _step2_execution(self, card: dict[str, Any]) -> None:
        if card.get("claim_type") not in ("result", "method"):
            return  # 只有数值/方法类声明才需要执行溯源（schema 亦只对这两类强制 evidence）
        evidence = card.get("evidence") or {}
        execution_id = evidence.get("sandbox_execution_id")
        if not execution_id:
            raise ExecutionUnresolved("result/method 卡缺 sandbox_execution_id")
        self.verify_event_chain()
        for event in self.raw_events():
            if event.get("event_type") != "execution" or event.get("execution_id") != execution_id:
                continue
            if event.get("status") != "completed":
                raise ExecutionRejected(f"{execution_id} 状态为 {event.get('status')}")
            if event.get("audit_status") not in ("available", "ok"):
                raise ExecutionRejected(f"{execution_id} 审计状态不可用：{event.get('audit_status')}")
            return
        raise ExecutionUnresolved(f"{execution_id} 未在事件链登记")

    # ---------------- 步 3：MANIFEST 上下文 ----------------
    @staticmethod
    def _step3_context(card: dict[str, Any], manifest: Manifest | None,
                       run_context: RunContext | None, row_manifest_version: str) -> None:
        if run_context is not None and row_manifest_version != run_context.manifest_version:
            raise ManifestContextMismatch(
                f"行 manifest_version={row_manifest_version} ≠ RunContext {run_context.manifest_version}")
        data_refs = (card.get("evidence") or {}).get("data_refs") or []
        if not data_refs:
            return
        if manifest is None:
            raise ManifestContextMismatch("带 data_refs 但未挂载 MANIFEST")
        for ref in data_refs:
            try:
                manifest.require_data_ref(ref["manifest_entry_id"], ref["data_hash"])
            except ManifestError as exc:
                raise _as_ledger_error(exc) from exc

    # ---------------- 步 4：hash 绑定 ----------------
    def verify_binding(self, card: dict[str, Any]) -> None:
        evidence = card.get("evidence")
        if not evidence:
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
        figure_hashes = evidence.get("figure_hashes") or []
        output_hashes = set(evidence.get("output_hashes") or [])
        for digest in figure_hashes:
            if digest not in output_hashes:
                raise FigureHashUnbound(f"figure_hash {digest} 不在 output_hashes")
        plan_ref = evidence.get("plan_ref")
        if plan_ref:
            plans = self._plans()
            if plan_ref not in plans:
                raise PlanUnbound(f"{plan_ref} 未登记为 PlanItem")
            expected = plans[plan_ref]
            if expected and expected != script_hash:
                lineage = card.get("lineage") or {}
                if not (card.get("confidence") == "exploratory" and lineage.get("deviation_note")):
                    raise PlanMismatch(
                        f"PlanItem {plan_ref} 期望 script_hash={expected}，实际 {script_hash}")

    # ---------------- 步 5：数值定位 ----------------
    def _step5_values(self, card: dict[str, Any]) -> None:
        evidence = card.get("evidence") or {}
        hashes = evidence.get("output_hashes") or []
        for value in evidence.get("values") or []:
            index = value.get("output_index", 0)
            if not isinstance(index, int) or index < 0 or index >= len(hashes):
                raise OutputIndexOutOfRange(f"output_index={index} 界外（共 {len(hashes)} 个产物）")
            payload_path = self.artifact_path(hashes[index])
            if not payload_path.exists():
                raise ArtifactUnreachable(f"产物不可达：{hashes[index]}")
            try:
                found = _resolve_pointer(payload_path.read_bytes(), str(value.get("pointer", "")))
            except ValueLocatorFail:
                raise
            except Exception as exc:  # 解析失败一律按定位失败处理
                raise ValueLocatorFail(f"pointer {value.get('pointer')!r} 无法定位：{exc}") from exc
            if not _compare(value.get("value"), found, str(value.get("comparison", "")),
                            value.get("tolerance")):
                raise ValueLocatorFail(
                    f"pointer {value.get('pointer')!r} 声明 {value.get('value')!r} ≠ 产物 {found!r}")

    # ---------------- 步 6：引用一致性 ----------------
    def _step6_citations(self, card: dict[str, Any], manifest: Manifest | None) -> None:
        citation_refs = card.get("citation_refs") or []
        framing_ref = card.get("framing_ref")
        if not citation_refs and not framing_ref:
            return
        if manifest is None:
            raise ManifestContextMismatch("带 citation_refs/framing_ref 但未挂载 MANIFEST")
        for ref in citation_refs:
            try:
                entry = manifest.require_citation(ref, self.snapshots)
            except ManifestError as exc:
                raise _as_ledger_error(exc) from exc
            if ref.get("manifest_entry_id") and entry.entry_id != ref["manifest_entry_id"]:
                raise ManifestContextMismatch(
                    f"citation manifest_entry_id={ref['manifest_entry_id']} ≠ 条目 {entry.entry_id}")
        if framing_ref is not None:
            try:
                entry = manifest.require_framing(framing_ref)
            except ManifestError as exc:
                raise _as_ledger_error(exc) from exc
            if framing_ref.get("manifest_entry_id") and entry.entry_id != framing_ref["manifest_entry_id"]:
                raise ManifestContextMismatch(
                    f"framing manifest_entry_id={framing_ref['manifest_entry_id']} ≠ 条目 {entry.entry_id}")

    # ---------------- 步 7：偏差标注 ----------------
    @staticmethod
    def _step7_deviation(card: dict[str, Any]) -> None:
        lineage = card.get("lineage") or {}
        if card.get("confidence") == "exploratory" and not lineage.get("deviation_note"):
            raise DeviationUnnoted("exploratory 卡必须带 lineage.deviation_note")

    # ---------------- 步 0：六道 rail（上下文装配前拦截）----------------
    @staticmethod
    def _pre_rails(card: dict[str, Any], manifest: Manifest | None, context: Any | None) -> None:
        """上下文装配前的 rail 预检：任一 rail 返回 BLOCK 即拒绝（`m1/rails.py`）。"""
        if context is None:
            return
        from m1 import rails

        blocked = rails.blocked(rails.evaluate(card, manifest=manifest, context=context))
        if blocked:
            first = blocked[0]
            raise LedgerError(f"{first.rail} 拦截：{first.detail}", code=first.code)

    # ---------------- 落账 ----------------
    def append(
        self,
        card: dict[str, Any],
        *,
        manifest: Manifest | None = None,
        run_context: RunContext | None = None,
        venue_profile_version: str = "vp-2026.10",
        now: float | None = None,
        crash_after: str | None = None,
        context: Any | None = None,
    ) -> AppendResult:
        """按八步链校验后幂等落账。任一步失败不产生任何痕迹（reject_log 属 M3）。"""
        manifest_version = (manifest.manifest_version if manifest is not None
                            else (run_context.manifest_version if run_context is not None else "MANIFEST#0"))
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

        self._pre_rails(card, manifest, context)                # 步 0：六道 rail
        validate_card(card)                                     # 步 1
        self._step2_execution(card)                             # 步 2
        self._step3_context(card, manifest, run_context, manifest_version)  # 步 3
        self.verify_binding(card)                               # 步 4
        self._step5_values(card)                                # 步 5
        self._step6_citations(card, manifest)                   # 步 6
        self._step7_deviation(card)                             # 步 7

        ts = now if now is not None else time.time()
        rows = self.rows()
        row: dict[str, Any] = dict(stub)
        row.update({
            "row_id": row_id,
            "row_seq": len(rows) + 1,
            "appended_at": _iso(ts),
            "audit_event_id": self._sign("claim.append", row_id),
            "prev_row_hash": rows[-1]["row_hash"] if rows else "",
        })
        row["row_hash"] = chain_digest(row)
        validate_row(row)

        txn = {"row_id": row_id, "stage": "pending", "row": row, "created_at": ts}
        wal_path = self.wal_dir / f"{row_id}.json"
        _atomic_write(wal_path, json.dumps(txn, ensure_ascii=False, sort_keys=True).encode("utf-8"))

        # ① rawlog（第二证据源）：同一 row_id 只记一条
        if not any(e.get("row_id") == row_id for e in self.raw_events()):
            evidence = card.get("evidence") or {}
            event = {
                "event_type": "claim.append",
                "event_id": self._sign("claim.append", row_id),
                "row_id": row_id,
                "claim_id": card.get("claim_id"),
                "claim_type": card.get("claim_type"),
                "script_hash": evidence.get("script_hash"),
                "output_hashes": evidence.get("output_hashes") or [],
                "recorded_at": ts,
                "prev_event_hash": self._last_event_hash(),
            }
            event["event_hash"] = event_digest(event)
            _append_line(self.rawlog_path, event)
            self._maybe_checkpoint()
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
        """把事务落到账本（步 8：row_seq 冲突 → ROW_CONFLICT；同 row_id 幂等）。"""
        rows = self.rows()
        for row in rows:
            if row["row_id"] == txn["row_id"]:
                return AppendResult(row_id=txn["row_id"], appended=False, duplicate=True)
        wanted = txn["row"]["row_seq"]
        for row in rows:
            if row["row_seq"] == wanted:
                raise RowConflict(f"row_seq={wanted} 已被 {row['row_id']} 占用")
        _append_line(self.claims_path, txn["row"])
        return AppendResult(row_id=txn["row_id"], appended=True, row_seq=txn["row"]["row_seq"])

    # ---------------- 崩溃恢复 ----------------
    def recover(self) -> dict[str, int]:
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
            else:
                kept = [e for e in self.raw_events() if e.get("row_id") != txn["row_id"]]
                if len(kept) != len(self.raw_events()):
                    _rewrite_jsonl(self.rawlog_path, kept)
                wal_path.unlink(missing_ok=True)
                stats["rolled_back"] += 1
        return stats

    # ---------------- 双源对账 ----------------
    def audit(self) -> AuditReport:
        rows = self.rows()
        events = self.raw_events()
        findings: list[dict[str, str]] = []

        try:
            self.verify_event_chain()
        except EventChainFail as exc:
            findings.append({"code": "TAMPER_DETECTED", "detail": f"事件链验算失败：{exc}"})

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
            if row.get("audit_event_id") != self._sign("claim.append", row.get("row_id", "")):
                findings.append({"code": "TAMPER_DETECTED",
                                 "detail": f"第 {idx} 行 audit_event_id 非本账本签发"})
            prev_hash = row.get("row_hash", "")

        ledger_ids = {r["row_id"] for r in rows}
        raw_ids = {e["row_id"] for e in events if e.get("row_id")}
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
        rows = sorted(self.rows(), key=lambda r: int(r.get("row_seq", 0)))
        return [stable_projection(r) for r in rows]
