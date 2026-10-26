#!/usr/bin/env python3
"""gen_docs_views.py — 交付物内嵌 JSON 视图的唯一生成器与守护者（D27 / P0-1）。

问题：v1.6.0 的 §1.2/§1.6/§1.7 三个 ```json 视图是手写压缩副本，一处尾逗号
不可解析、一处含「…省略…」、一处与权威 schema 不相等——「视图由门禁守护」是假命题。

方案：视图 = 权威 schema 的确定性投影（投影规则固定、可复算）：
  1) 删除 $schema（视图不承载元 schema 声明）；
  2) 递归删除全部 description（说明文字归正文，视图只留结构）；
  3) ClaimRow 的内嵌 definitions.ClaimCard 替换为固定占位符（全文见 §1.2，
     避免同一份 schema 在文档里维护两遍）。
投影结果用 json.dumps(..., ensure_ascii=False, indent=2) 渲染。

用法：
  python tools/gen_docs_views.py --check   # 只读比对（CI/门禁用，默认）
  python tools/gen_docs_views.py --write   # 重写三个视图块
退出码：0 一致；1 不一致；2 结构异常（找不到章节/围栏/成对反引号）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "阶段1交付物-声明卡Schema与反例测试规格.md"
S = ROOT / "schemas"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CARD_PLACEHOLDER = "…ClaimCard 1.4.0 全文见 §1.2（权威源 schemas/claimcard-1.4.0.json）…"

# (视图名, 章节号, 权威源文件, 投影种类)
SECTIONS = [
    ("§1.2 ClaimCard", "1.2", "claimcard-1.4.0.json", "card"),
    ("§1.6 ManifestEntry", "1.6", "manifestentry-1.0.0.json", "plain"),
    ("§1.7 ClaimRow", "1.7", "claimrow-1.2.0.json", "row"),
]


def strip_descriptions(node):
    if isinstance(node, dict):
        return {k: strip_descriptions(v) for k, v in node.items() if k != "description"}
    if isinstance(node, list):
        return [strip_descriptions(v) for v in node]
    return node


def project(fn: str, kind: str) -> dict:
    with open(S / fn, encoding="utf-8") as f:
        src = json.load(f)
    src.pop("$schema", None)
    proj = strip_descriptions(src)
    if kind == "row":
        defs = proj.get("definitions", {})
        if "ClaimCard" in defs:
            defs["ClaimCard"] = CARD_PLACEHOLDER
    return proj


def find_section_bounds(lines: list[str], sec: str) -> tuple[int, int]:
    """返回 (标题行 idx, 节末行 idx 不含)。标题匹配 ^#{1,6}\\s*<sec>[.、\\s]。"""
    pat = re.compile(rf"^(#{{1,6}})\s*{re.escape(sec)}[.、\s]")
    head = None
    level = None
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if m:
            head, level = i, len(m.group(1))
            break
    if head is None:
        raise LookupError(f"找不到章节 {sec} 的标题")
    for j in range(head + 1, len(lines)):
        m = re.match(r"^(#{1,6})\s", lines[j])
        if m and len(m.group(1)) <= level:
            return head, j
    return head, len(lines)


def find_fence(lines: list[str], start: int, end: int) -> tuple[int, int]:
    """在 [start,end) 内找第一个 ```json 围栏，返回 (围栏起始行, 结束围栏行)。"""
    open_i = None
    for i in range(start, end):
        if lines[i].strip() == "```json":
            open_i = i
            break
    if open_i is None:
        raise LookupError("章节内找不到 ```json 围栏")
    for j in range(open_i + 1, end):
        if lines[j].strip() == "```":
            return open_i, j
    raise LookupError("```json 围栏未闭合")


def render(proj: dict) -> list[str]:
    return json.dumps(proj, ensure_ascii=False, indent=2).split("\n")


def main(argv: list[str]) -> int:
    write = "--write" in argv[1:]
    if not write and "--check" not in argv[1:]:
        print(__doc__.strip().split("\n")[-1])
        print("用法: python tools/gen_docs_views.py [--check|--write]")
    text = DOC.read_text(encoding="utf-8")
    lines = text.split("\n")
    fails: list[str] = []
    plans: list[tuple[str, int, int, list[str]]] = []

    for name, sec, fn, kind in SECTIONS:
        try:
            hs, he = find_section_bounds(lines, sec)
            a, b = find_fence(lines, hs, he)
        except LookupError as e:
            print(f"[FAIL] {name}: {e}")
            fails.append(name)
            continue
        expected = render(project(fn, kind))
        actual_text = "\n".join(lines[a + 1:b])
        try:
            actual = json.loads(actual_text)
            parse_err = None
        except json.JSONDecodeError as e:
            actual, parse_err = None, f"第 {a + 1 + e.lineno} 行: {e.msg}"
        if parse_err:
            ok = False
            detail = f"不可解析（{parse_err}）"
        else:
            ok = actual == project(fn, kind)
            detail = "与权威源投影不等" if not ok else ""
        print(f"[{'PASS' if ok else 'FAIL'}] {name} ← {fn}" + (f" — {detail}" if detail else ""))
        if not ok:
            fails.append(name)
        plans.append((name, a, b, expected))

    if write and plans:
        # 自下而上替换，避免行号漂移
        for name, a, b, expected in sorted(plans, key=lambda p: p[1], reverse=True):
            lines[a + 1:b] = expected
            print(f"[WRITE] {name}")
        DOC.write_text("\n".join(lines), encoding="utf-8")
        print("视图已重写；请复跑 --check 确认")
        return 0

    if fails:
        print(f"视图校验：{len(fails)}/{len(SECTIONS)} 块不一致 → 需 --write 或修 schema 投影")
        return 1
    print(f"视图校验：全绿（{len(SECTIONS)} 块 = 权威源确定性投影）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except FileNotFoundError as e:
        print(f"FATAL: 缺少文件 {e.filename}")
        sys.exit(2)
