#!/usr/bin/env python3
"""check_docs_consistency.py — 文档机检（D27）：计数/枚举/版本/口径一致性。

动机（P1-6）：v25/v1.6.0 有 12 处文档漂移，全靠人眼发现。本检查把这些口径
变成可执行断言，任何一处回退都会让门禁变红。

判据：
  C1 版本锚：每件 schema 的 {名称, 版本} 与文档声明一致；非变更史区域不得出现旧版本；
  C2 禁止词表：五文件/五个 schema/七步/十角色/十例十三断言/T5a–e/D1–D24 等旧口径清零；
  C3 必需词表：六件/八步/十一角色/T5a–f/G1–G4 存在；
  C4 实测数：文档里的「N 项断言」必须等于 validate_freeze.py 的实际输出；
  C5 错误码：反引号内的大写码必须来自 tools/freeze_codes.py 的码表（禁止自造码）；
  C6 八步链覆盖：§1.3 章节内出现全部链层错误码；
  C7 视图：gen_docs_views.py --check 必须全绿（三块 = 权威源投影）；
  C8 结构：交付物 §一–§十一 与 1.1–1.9 齐全；总纲 D 表连续且标题范围与表一致。
退出码：0 全绿；1 有失败；2 结构/依赖异常。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
S = ROOT / "schemas"
DOC = ROOT / "阶段1交付物-声明卡Schema与反例测试规格.md"
MASTER = ROOT / "科研智能体总体方案.md"
sys.path.insert(0, str(TOOLS))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from freeze_codes import STEP_CODES, all_codes
except ImportError:
    print("FATAL: tools/freeze_codes.py 缺失")
    sys.exit(2)

FAILS: list[str] = []
N = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global N
    N += 1
    if not ok:
        FAILS.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))


def read(p: pathlib.Path) -> str:
    if not p.exists():
        print(f"FATAL: 缺少 {p.name}")
        sys.exit(2)
    return p.read_text(encoding="utf-8")


def body(text: str, changelog_heading: str) -> str:
    """去掉变更史区域（旧值对照合法存在的地方）。"""
    i = text.find(changelog_heading)
    return text if i < 0 else text[:i]


def strip_fences(text: str) -> str:
    """去掉 ``` 围栏块（视图内容由 C7 机检，不参与文字口径检查）。"""
    out: list[str] = []
    infence = False
    for ln in text.split("\n"):
        if ln.strip().startswith("```"):
            infence = not infence
            continue
        if not infence:
            out.append(ln)
    return "\n".join(out)


doc = read(DOC)
master = read(MASTER)
doc_body = strip_fences(body(doc, "## 十一、修订对照表"))
master_body = strip_fences(body(master, "变更史"))

# ---------- C1 版本锚 ----------
LABEL = {
    "claimcard": "ClaimCard", "claimrow": "ClaimRow", "planitem": "PlanItem",
    "manifestentry": "ManifestEntry", "contracts": "Contracts",
    "exclusionlist": "ExclusionList",
}
versions: dict[str, str] = {}
bad = []
for p in sorted(S.glob("*.json")):
    stem = p.name.rsplit("-", 1)[0]
    label = LABEL.get(stem)
    if not label:
        bad.append(f"未知 schema 文件 {p.name}")
        continue
    v = json.loads(p.read_text(encoding="utf-8"))["version"]
    versions[label] = v
    anchored = re.search(rf"{label}\s*\*\*{re.escape(v)}\*\*", doc)
    check(f"C1 交付物版本锚 {label} {v}", bool(anchored))
    if label in ("ClaimCard", "ClaimRow"):
        check(f"C1 总纲引用 {label} {v}", bool(re.search(rf"{label}[^\n]{{0,12}}{re.escape(v)}", master_body)),
              f"总纲未引用 {label} {v}")
check("C1 schema 清单六件（无未知文件）", len(versions) == 6 and not bad, str(bad))

# 旧版声明：只认「名字紧跟版本」（ClaimCard **1.3.0** / ClaimCard 1.3.0）；
# 正文里作对照示例的「claimcard_schema_version=1.3.0」「…ClaimCard 1.3.0 全文…占位符」不算。
STALE_DOC = {"ClaimCard": ["1.3.0"], "ClaimRow": ["1.1.0"]}
for label, stale in STALE_DOC.items():
    for v in stale:
        hits = [ln for ln in doc_body.split("\n")
                if re.search(rf"{label}[\s*]*{re.escape(v)}", ln)]
        check(f"C1 交付物非变更史区无旧版 {label} {v}", not hits, hits[:2])

# ---------- C2 禁止词表 ----------
FORBID = [
    (r"五文件|五个\s*schema|五个 schema 文件", "应为六件"),
    (r"七步", "应为八步"),
    (r"十角色", "应为十一角色"),
    (r"十例十三断言", "实例数已改按门禁实测"),
    (r"T5a\s*[–-]\s*e(?!\s*f)", "应为 T5a–f"),
    (r"D1\s*[–-]\s*D24", "应为 D1–D27"),
    (r"66\s*[–-]\s*69\s*%", "D26 P1-12 已判定构念错位"),
    (r"较从零缩短\s*40\s*[–-]\s*45\s*%", "D26③ 已校准"),
    (r"`(?:tamper_detected|phantom_event)`", "错误码须全大写"),
]
for patname, (pat, why) in zip([p for p, _ in FORBID], FORBID):
    for label, text in (("交付物", doc_body), ("总纲", master_body)):
        hits = [f"{i+1}: {ln.strip()[:60]}" for i, ln in enumerate(text.split("\n"))
                if re.search(pat, ln)]
        check(f"C2 {label} 禁止口径 {patname}", not hits, f"{why}; {hits[:2]}")

# ---------- C3 必需词表 ----------
REQUIRE = [("六件", doc_body, "五→六件"), ("八步", doc_body, "七→八步"),
           ("十一角色", doc_body, "十→十一角色"), ("T5a–f", doc_body, "T5a–e→f")]
for word, text, why in REQUIRE:
    check(f"C3 交付物必需口径「{word}」", word in text, why)
for layer in ("G1", "G2", "G3", "G4"):
    check(f"C3 交付物冻结判据 {layer}", layer in doc_body)

# ---------- C4 实测断言数 ----------
def run_tool(filename: str, call_main: bool = False, argv: list[str] | None = None):
    """进程内执行工具脚本并捕获 stdout。

    本环境沙箱禁止 subprocess 的管道式 stdio（WinError 5 / EPERM），
    因此不能用 subprocess.run(capture_output=True)。"""
    buf = io.StringIO()
    rc = 0
    spec = importlib.util.spec_from_file_location(TOOLS.joinpath(filename).stem,
                                                  TOOLS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(TOOLS))
    try:
        with contextlib.redirect_stdout(buf):
            spec.loader.exec_module(mod)
            if call_main:
                rc = mod.main(argv or ["prog"])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        if str(TOOLS) in sys.path:
            sys.path.remove(str(TOOLS))
    return rc, buf.getvalue()


rc_gate, gate_out = run_tool("validate_freeze.py")
m = re.search(r"全绿（(\d+) 项断言", gate_out)
actual = int(m.group(1)) if m else None
check("C4 门禁可运行并输出断言总数", actual is not None and rc_gate == 0,
      f"rc={rc_gate}; {gate_out.strip().splitlines()[-1] if gate_out.strip() else 'no output'}")
if actual is not None:
    claimed = [int(x) for x in re.findall(r"(\d+)\s*项断言", doc_body)]
    check(f"C4 交付物断言数 == 门禁实测 {actual}", set(claimed) == {actual}, f"文档出现 {sorted(set(claimed))}")
    # C4b：总纲同样只允许登记实测断言数（D27③「文档计数由机器复核」对两份文档一致生效）
    m_claimed = [int(x) for x in re.findall(r"(\d+)\s*(?:项)?断言", master_body)]
    check(f"C4b 总纲断言数 ⊆ {{门禁实测 {actual}}}", set(m_claimed) <= {actual},
          f"总纲出现 {sorted(set(m_claimed))}")

# ---------- C5 错误码来源 ----------
KNOWN = all_codes() | {"JSON", "JSONL", "RFC", "DOI", "TOST", "JCS", "SHA256", "YAML",
                       "CSV", "PDF", "HTTP", "HTTPS", "API", "UUID", "CLI", "CI",
                       "M1", "M2", "M3", "M4", "I01", "R01", "MIT", "QA", "OK"}
CODE_TOKEN = re.compile(r"`([A-Z][A-Z0-9_]{2,})`")
for label, text in (("交付物", doc_body), ("总纲", master_body)):
    unknown = sorted({m.group(1) for m in CODE_TOKEN.finditer(text)} - KNOWN)
    check(f"C5 {label} 无自造错误码", not unknown, str(unknown))

# ---------- C6 八步链码覆盖 ----------
try:
    hs = doc.index("### 1.3")
    he = doc.index("### 1.4")
    chain_region = doc[hs:he]
except ValueError:
    chain_region = ""
    check("C6 交付物 §1.3 章节存在", False)
missing = sorted(c for c in STEP_CODES if c not in chain_region)
check("C6 §1.3 覆盖八步链全部错误码（20）", not missing, str(missing))

# ---------- C7 视图 ----------
rc_views, views_out = run_tool("gen_docs_views.py", call_main=True,
                               argv=["gen_docs_views.py", "--check"])
check("C7 内嵌 JSON 视图 == 权威源投影", rc_views == 0,
      views_out.strip().splitlines()[-1] if views_out.strip() else "no output")

# ---------- C8 结构 ----------
for sec in ("〇", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一"):
    check(f"C8 交付物章节 §{sec} 存在", re.search(rf"^##\s*{sec}[、.]", doc, re.M) is not None)
for sub in [f"1.{i}" for i in range(1, 10)]:
    check(f"C8 交付物小节 {sub}", re.search(rf"^###\s*{re.escape(sub)}[\s.]", doc, re.M) is not None)

d_nums = [int(m.group(1)) for m in re.finditer(r"^\|\s*D(\d+)\s*\|", master, re.M)]
if d_nums:
    check("C8 总纲 D 表连续无跳号", d_nums == list(range(d_nums[0], d_nums[-1] + 1)),
          f"表内 D 编号 {d_nums}")
    title = re.search(r"D1\s*[–-]\s*D(\d+)", master)
    check("C8 总纲标题范围 D1–Dmax 与表一致", bool(title) and int(title.group(1)) == d_nums[-1],
          f"标题 {title.group(1) if title else '未找到'} / 表尾 D{d_nums[-1]}")
else:
    check("C8 总纲 D 表可解析", False, "未匹配到 | D数字 | 行")

# ---------- 汇总 ----------
print()
if FAILS:
    print(f"文档一致性：{len(FAILS)}/{N} 项失败 → 不可冻结")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print(f"文档一致性：全绿（{N} 项；版本锚 {len(versions)} 件 / 码表 {len(all_codes())} / 视图 3 块）")
sys.exit(0)
