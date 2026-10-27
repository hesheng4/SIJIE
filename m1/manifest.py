"""MANIFEST 注册表与快照库：八步链步 3（上下文）与步 6（引用一致性）的权威源。

为什么要这一层
--------------
数值侧的绑定（步 4/5）只证明「论文里的数字等于产物里的数字」；要证明「这个数字来自本轮
冻结的那份数据、这条引用真在文献清单里」，就必须有一份**本轮只读的 MANIFEST 注册表**：

* `data` 条目：`entry_id` + 内容哈希 `sha256`（步 3 校验 `data_refs[].data_hash` 是否等于条目哈希，
  防「换了数据集还声称同一结论」的上下文漂移）。
* `literature` 条目：`doi` + `role`（`backbone` / `supporting`）+ `snapshot_ref`（primary 引用的正文快照）。
  步 6 用 role 拦「综述转述冒充一手证据」，用 `snapshot_ref` 拦「原文半年后消失、无法回溯」。

设计约束
--------
* 注册表在本轮内**只读**：M1 只提供 `Manifest.add()` 建表 + 查询/断言方法；落账流程只读它。
* 快照库内容寻址（`snapshots/<hex[:2]>/<hex[2:14]>`），与 artifacts/scripts 同构。
* 所有失败都抛带冻结错误码的 `ManifestError`，错误码与 `tools/freeze_codes.py` 的八步链码同名。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "Entry",
    "Manifest",
    "ManifestError",
    "RunContext",
    "SnapshotStore",
    "sha256_text",
]

#: 文献档位：只有 backbone 条目允许承载 framing，survey_transfer 的 survey 也必须是 backbone。
ROLES = ("backbone", "supporting")
KINDS = ("data", "literature")


class ManifestError(Exception):
    """带冻结错误码的 MANIFEST 失败（码名与八步链一致）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Entry:
    """MANIFEST 条目（数据或文献）。"""

    entry_id: str                      # mfe_<12 hex>
    kind: str                          # data | literature
    sha256: str | None = None          # data：内容哈希
    doi: str | None = None             # literature
    role: str | None = None            # literature：backbone | supporting
    snapshot_ref: str | None = None    # literature：一手正文快照 sha256
    locators: tuple[str, ...] = ()     # literature：可解析的 locator 白名单（"p.12"/"sec 3"…）
    license: str | None = None         # literature：许可（Compliance rail 用）
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = {"entry_id": self.entry_id, "kind": self.kind}
        for key in ("sha256", "doi", "role", "snapshot_ref", "license"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        if self.locators:
            out["locators"] = list(self.locators)
        if self.provenance:
            out["provenance"] = dict(self.provenance)
        return out


class SnapshotStore:
    """正文快照内容寻址库（无命中即 `SNAPSHOT_MISSING` 的证据）。"""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        hexpart = digest.split(":", 1)[1]
        return self.root / hexpart[:2] / hexpart[2:14]

    def put(self, text: str) -> str:
        digest = sha256_text(text)
        target = self._path(digest)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return digest

    def has(self, digest: str | None) -> bool:
        if not digest or not digest.startswith("sha256:"):
            return False
        path = self._path(digest)
        return path.exists() and sha256_text(path.read_text(encoding="utf-8")) == digest

    def get(self, digest: str) -> str:
        if not self.has(digest):
            raise ManifestError("SNAPSHOT_MISSING", f"快照不存在或已变：{digest}")
        return self._path(digest).read_text(encoding="utf-8")


class Manifest:
    """本轮冻结的 MANIFEST 注册表（intake 生成后只读挂载）。"""

    def __init__(self, manifest_version: str, *, entries: list[Entry] | None = None) -> None:
        self.manifest_version = manifest_version
        self._entries: dict[str, Entry] = {}
        self._doi: dict[str, Entry] = {}
        for entry in entries or []:
            self.add(entry)

    # ---------------- 建表 ----------------
    def add(self, entry: Entry) -> None:
        if entry.kind not in KINDS:
            raise ValueError(f"未登记条目类型：{entry.kind}")
        if entry.kind == "literature" and entry.role not in ROLES:
            raise ValueError(f"文献条目 role 必须是 {ROLES}：{entry.entry_id}")
        self._entries[entry.entry_id] = entry
        if entry.doi:
            self._doi[entry.doi] = entry

    # ---------------- 查询 ----------------
    def get(self, entry_id: str) -> Entry | None:
        return self._entries.get(entry_id)

    def data(self, entry_id: str) -> Entry | None:
        entry = self._entries.get(entry_id)
        return entry if entry and entry.kind == "data" else None

    def literature(self, doi: str) -> Entry | None:
        return self._doi.get(doi)

    def has_snapshot(self, doi: str, snapshots: SnapshotStore | None = None) -> bool:
        entry = self._doi.get(doi)
        if not entry or not entry.snapshot_ref:
            return False
        if snapshots is None:
            return True  # 只查声明（步 6 的 SNAPSHOT_MISSING 由调用方带快照库复核）
        return snapshots.has(entry.snapshot_ref)

    def entries(self) -> list[Entry]:
        return list(self._entries.values())

    def to_dict(self) -> dict[str, Any]:
        return {"manifest_version": self.manifest_version,
                "entries": [e.to_dict() for e in self._entries.values()]}

    def save(self, path: str | os.PathLike[str]) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "Manifest":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = [Entry(entry_id=e["entry_id"], kind=e["kind"], sha256=e.get("sha256"),
                         doi=e.get("doi"), role=e.get("role"),
                         snapshot_ref=e.get("snapshot_ref"),
                         locators=tuple(e.get("locators", ())),
                         license=e.get("license"), provenance=e.get("provenance", {}))
                   for e in raw["entries"]]
        return cls(raw["manifest_version"], entries=entries)

    # ---------------- 步 3：数据引用（上下文 / 传递性）----------------
    def require_data_ref(self, entry_id: str, data_hash: str) -> Entry:
        entry = self.data(entry_id)
        if entry is None:
            raise ManifestError("MANIFEST_CONTEXT_MISMATCH",
                                f"{entry_id} 不是当前 MANIFEST 的数据条目")
        if entry.sha256 != data_hash:
            raise ManifestError("TRANSPORTIVITY_FAIL",
                                f"{entry_id} 条目哈希 {entry.sha256} ≠ data_refs 的 {data_hash}")
        return entry

    # ---------------- 步 6：引用一致性 ----------------
    def require_citation(self, ref: dict[str, Any], snapshots: SnapshotStore | None = None) -> Entry:
        doi = ref.get("doi", "")
        entry = self.literature(doi)
        if entry is None:
            raise ManifestError("DOI_NOT_IN_MANIFEST", f"{doi} 不在当前 MANIFEST 文献条目中")
        verification = ref.get("verification")
        if verification == "primary" and not ref.get("snapshot_ref"):
            raise ManifestError("SNAPSHOT_MISSING", f"{doi} 声明为 primary 但未带 snapshot_ref")
        if ref.get("snapshot_ref") and snapshots is not None and not snapshots.has(ref["snapshot_ref"]):
            raise ManifestError("SNAPSHOT_MISSING", f"{doi} 的快照 {ref['snapshot_ref']} 不在快照库")
        if verification == "survey_transfer":
            survey_doi = ref.get("survey_doi", "")
            survey = self.literature(survey_doi)
            if survey is None:
                raise ManifestError("DOI_NOT_IN_MANIFEST", f"survey_doi {survey_doi} 不在 MANIFEST")
            if survey.role != "backbone":
                raise ManifestError("BACKBONE_GRADE_VIOLATION",
                                    f"survey {survey_doi} 的条目档位是 {survey.role}，不能承载转述")
        locator = ref.get("locator", "")
        if not locator:
            raise ManifestError("CITATION_LOCATOR_FAIL", f"{doi} 缺 locator")
        if entry.locators and locator not in entry.locators:
            raise ManifestError("CITATION_LOCATOR_FAIL",
                                f"{doi} 的 locator {locator!r} 不在可解析白名单 {entry.locators}")
        return entry

    def require_framing(self, ref: dict[str, Any]) -> Entry:
        """framing 只能挂 backbone 条目（T3 禁承载 framing）。"""
        doi = ref.get("survey_doi", "")
        entry = self.literature(doi)
        if entry is None:
            raise ManifestError("DOI_NOT_IN_MANIFEST", f"framing survey_doi {doi} 不在 MANIFEST")
        if entry.role != "backbone":
            raise ManifestError("BACKBONE_GRADE_VIOLATION",
                                f"framing 指向 {doi}，其档位是 {entry.role}（须 backbone）")
        if not ref.get("locator"):
            raise ManifestError("CITATION_LOCATOR_FAIL", f"framing {doi} 缺 locator")
        return entry


@dataclass(frozen=True)
class RunContext:
    """本轮 RunContext：`manifest_version` 必须与行上的 `manifest_version` 一致（步 3）。"""

    run_id: str
    manifest_version: str
    run_context_ref: str
    manifest: Manifest | None = None
    venue_profile_version: str = "vp-2026.10"

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "manifest_version": self.manifest_version,
                "run_context_ref": self.run_context_ref,
                "venue_profile_version": self.venue_profile_version}
