#!/usr/bin/env python
"""E2E 演示用脚本：对本仓库真实 git 历史做描述统计，输出可被账本定位的 JSON 产物。

输入：`git log --numstat --format='commit %H %aI'` 导出的 TSV（真实数据，由 run_e2e.py 生成）。
输出：JSON 产物，字段即步 5 将按 RFC 6901 指针定位的对象。

设计约束（与冻结规格一致）：
- 不读网络、不读当前工作树，只解析显式传入的 TSV，保证可重放；
- 产物中同时写入输入文件哈希，便于人工复核统计对象是否同一份；
- 数值只用 int/float，避免下游指针定位时的类型歧义。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path


def parse_tsv(text: str) -> list[dict]:
    """解析 `commit <sha> <iso>` 块 + `added\tdeleted\tpath` 行（二进制文件为 `-`）。"""
    commits: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("commit "):
            _, sha, iso = line.split()
            current = {"sha": sha, "committed_at": iso, "files": 0,
                       "added": 0, "deleted": 0, "binary": 0}
            commits.append(current)
            continue
        if current is None or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, _path = parts
        current["files"] += 1
        if added == "-" or deleted == "-":
            current["binary"] += 1
            continue
        current["added"] += int(added)
        current["deleted"] += int(deleted)
    return commits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="git 历史描述统计（E2E 演示脚本）")
    ap.add_argument("--data", required=True, help="git log --numstat 导出的 TSV")
    ap.add_argument("--out", required=True, help="JSON 产物输出路径")
    args = ap.parse_args(argv)

    data_path = Path(args.data)
    payload = data_path.read_bytes()
    commits = parse_tsv(payload.decode("utf-8"))
    if not commits:
        print("无提交记录", file=sys.stderr)
        return 2

    per_commit = [c["added"] + c["deleted"] for c in commits]
    stamps = [datetime.fromisoformat(c["committed_at"]) for c in commits]
    span_days = (max(stamps) - min(stamps)).total_seconds() / 86400.0

    stats = {
        "source": {
            "path": data_path.name,
            "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "rows": sum(1 for ln in payload.decode("utf-8").splitlines() if ln and not ln.startswith("commit ")),
        },
        "n_commits": len(commits),
        "files_touched": sum(c["files"] for c in commits),
        "binary_files": sum(c["binary"] for c in commits),
        "total_added": sum(c["added"] for c in commits),
        "total_deleted": sum(c["deleted"] for c in commits),
        "net_lines": sum(c["added"] - c["deleted"] for c in commits),
        "max_lines_commit": max(per_commit),
        "lines_per_commit_median": float(statistics.median(per_commit)),
        "lines_per_commit_mean": round(statistics.fmean(per_commit), 6),
        "span_days": round(span_days, 6),
        "commits_per_day": round(len(commits) / span_days, 6) if span_days else None,
        "first_commit_at": min(stamps).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_commit_at": max(stamps).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "demo/scripts/git_commit_stats.py v1",
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
