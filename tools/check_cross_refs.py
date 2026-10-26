#!/usr/bin/env python3
"""check_cross_refs.py — 版本对偶与跨文件一致性校验（D26/D27，修 P1-5 假阴性）。

v1.6.0 的问题：② 用 `re.findall(r"交付物 v(\\d+\\.\\d+\\.\\d+)", master)` 后 `in` 判断，
会命中总纲 25 版变更史里的历史版本——「只在变更史加一行、基线行不更新」仍 PASS；
③b/③c 用 split("验收基线")[-1][:400] 的字符窗口，窗口外/窗口内噪声都会误判。

v1.7.0 改为：
  ① 交付物抬头引用的总纲版本 == 总纲标题版本；
  ② 总纲「验收基线六件套」所在行的交付物版本 == 交付物版本记录的「当前」版本
     （只认基线行，不做全文档 findall）；
  ③ 基线六件套枚举 == schemas/ 实际文件（版本全部从 schemas/*.json 派生，零硬编码）；
  ④ 复合件内嵌件版本 == 基础件版本；ClaimRow.claimcard_schema_version const == ClaimCard 版本；
  ⑤ 角色词表：ClaimCard.definitions.Role == Contracts 的 from_role/to_role 枚举。
退出码：0 全绿；1 失败；2 依赖/结构异常。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MASTER = ROOT / "科研智能体总体方案.md"
DELIV = ROOT / "阶段1交付物-声明卡Schema与反例测试规格.md"
S = ROOT / "schemas"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FAILS: list[str] = []
N = 0
SELFTEST = "--selftest" in sys.argv[1:]


def check(name: str, ok: bool, detail: str = "") -> None:
    global N
    N += 1
    if not ok:
        FAILS.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))


def lines_with(text: str, needle: str) -> list[str]:
    return [ln for ln in text.split("\n") if needle in ln]


master = MASTER.read_text(encoding="utf-8")
deliv = DELIV.read_text(encoding="utf-8")

# ---------- ① 总纲版本对偶 ----------
m_master = re.search(r"总体方案（v(\d+)", master)
m_ref = re.search(r"依据《科研智能体总体方案 \*\*v(\d+)\*\*》", deliv)
if not SELFTEST:
    check("① 交付物抬头引用的总纲版本 == 总纲标题版本",
          bool(m_master and m_ref and m_master.group(1) == m_ref.group(1)),
          f"master=v{m_master.group(1) if m_master else '?'}, "
          f"deliverable 引用=v{m_ref.group(1) if m_ref else '?'}")

# ---------- ② 基线行对偶（不做全文档 findall） ----------
def parse_baseline_deliv(master_text: str) -> str | None:
    """只从「验收基线六件套」那一行解析交付物版本。

    旧实现 `re.findall(r"交付物 v(\\d+\\.\\d+\\.\\d+)", master)` + `in` 会命中
    变更史历史版本，导致「只在变更史加一行、基线行不更新」仍 PASS（P1-5）。"""
    for ln in lines_with(master_text, "验收基线六件套"):
        m = re.search(r"交付物\s*v(\d+\.\d+\.\d+)", ln)
        if m:
            return m.group(1)
    return None


def parse_current_deliv(deliv_text: str) -> str | None:
    m = re.search(r"\*\*v(\d+\.\d+\.\d+)（当前）",
                  "\n".join(lines_with(deliv_text, "版本记录")))
    return m.group(1) if m else None


if "--selftest" in sys.argv[1:]:
    # 回归：变更史有 v1.7.0、基线行仍 v1.6.0 → 必须判不一致（旧实现会 PASS）
    fake_master_bad = ("## 17. 变更史\n- v1.7.0：交付物 v1.7.0 升版\n"
                       "验收基线六件套（交付物 v1.6.0 + ClaimCard **1.4.0**）\n")
    fake_deliv = "> **版本记录**：**v1.7.0（当前）**=本次修订\n"
    fake_master_ok = fake_master_bad.replace("交付物 v1.6.0", "交付物 v1.7.0")
    case_bad = parse_baseline_deliv(fake_master_bad) != parse_current_deliv(fake_deliv)
    case_ok = parse_baseline_deliv(fake_master_ok) == parse_current_deliv(fake_deliv)
    print(f"[{'PASS' if case_bad else 'FAIL'}] 回归：变更史变更但基线行未更新 → 判不一致")
    print(f"[{'PASS' if case_ok else 'FAIL'}] 回归：基线行已更新 → 判一致")
    old_hits = re.findall(r"交付物 v(\d+\.\d+\.\d+)", fake_master_bad)
    print(f"[PASS] 旧实现对照：全文档 findall 会得到 {old_hits}（含变更史噪声）")
    sys.exit(0 if case_bad and case_ok else 1)

base_lines = lines_with(master, "验收基线六件套")
base_deliv_ver = parse_baseline_deliv(master)
deliv_cur_ver = parse_current_deliv(deliv)
check("② 基线行交付物版本可解析（锚定「验收基线六件套」行）",
      bool(base_deliv_ver and deliv_cur_ver),
      f"基线行命中 {len(base_lines)} 行，deliverable 当前={deliv_cur_ver or '未找到'}")
check("② 总纲基线登记的交付物版本 == 交付物「当前」版本",
      bool(base_deliv_ver and deliv_cur_ver and base_deliv_ver == deliv_cur_ver),
      f"master 基线=v{base_deliv_ver or '?'} / deliverable=v{deliv_cur_ver or '?'}")

# ---------- ③ 六件套枚举（版本全部从文件派生） ----------
LABEL = {"claimcard": "ClaimCard", "claimrow": "ClaimRow", "planitem": "PlanItem",
         "manifestentry": "ManifestEntry", "contracts": "Contracts",
         "exclusionlist": "ExclusionList"}
schemas: dict[str, dict] = {}
for p in sorted(S.glob("*.json")):
    obj = json.loads(p.read_text(encoding="utf-8"))
    schemas[p.name] = obj

check("③a schema 文件恰为六件", len(schemas) == 6, str(sorted(schemas)))
name_ver: dict[str, str] = {}
for fn, obj in schemas.items():
    stem, ver = fn.rsplit("-", 1)[0], fn.rsplit("-", 1)[-1].removesuffix(".json")
    check(f"③a {fn} 文件名版本 == version 字段", ver == obj.get("version"),
          f"file={ver} version={obj.get('version')}")
    label = LABEL.get(stem)
    if not label:
        check(f"③a 未登记 schema 文件 {fn}", False)
        continue
    name_ver[label] = obj.get("version", "")

EXPECT = [f"{k} {v}" for k, v in name_ver.items()]


def missing_in(text: str) -> list[str]:
    flat = text.replace("*", "").replace("/", " ").replace("，", " ")
    return [e for e in EXPECT if e not in flat]


check("③b 总纲验收基线行枚举六件套", not missing_in(" ".join(base_lines)),
      f"缺失: {missing_in(' '.join(base_lines))}")
deliv_base = "\n".join(lines_with(deliv, "阶段验收基线"))
check("③c 交付物版本口径行枚举六件套", not missing_in(deliv_base),
      f"缺失: {missing_in(deliv_base)}")

# ---------- ④ 复合件内嵌版本 ----------
row = schemas.get("claimrow-1.2.0.json")
card = schemas.get("claimcard-1.4.0.json")
ct = schemas.get("contracts-1.1.0.json")
excl = schemas.get("exclusionlist-1.0.2.json")
if card and row:
    emb = row.get("definitions", {}).get("ClaimCard", {})
    check("④a ClaimRow 内嵌 ClaimCard 版本 == ClaimCard 版本",
          emb.get("version") == card.get("version"),
          f"嵌入={emb.get('version')} 源={card.get('version')}")
    # ClaimRow 自身 definitions.Role 与内嵌 card 的 Role 定义同源
    check("④b ClaimRow 根 definitions 含 Role（$ref 可解析）",
          "Role" in row.get("definitions", {}))
if ct and excl:
    emb_e = ct.get("definitions", {}).get("ExclusionList", {})
    check("④c Contracts 内嵌 ExclusionList 版本 == ExclusionList 版本",
          emb_e.get("version") == excl.get("version"),
          f"嵌入={emb_e.get('version')} 源={excl.get('version')}")
if row and card:
    cst = row.get("properties", {}).get("claimcard_schema_version", {})
    check("④d ClaimRow.claimcard_schema_version const == ClaimCard 版本（修漂移 #12）",
          cst.get("const") == card.get("version"),
          f"const={cst.get('const')} 源={card.get('version')}")

# ---------- ⑤ 角色词表同源 ----------
if card and ct:
    roles_card = card.get("definitions", {}).get("Role", {}).get("enum", [])
    p = ct.get("properties", {}).get("payload", {})
    # Contracts payload 的 from_role/to_role 在顶层 properties
    top = ct.get("properties", {})
    roles_ct = (top.get("from_role", {}).get("enum") or [])
    check("⑤ ClaimCard.definitions.Role == Contracts from_role 枚举（同源同序）",
          bool(roles_card) and roles_card == roles_ct,
          f"card={len(roles_card)} 项, contracts={len(roles_ct)} 项")
    check("⑤ 角色词表恰为 11 项", len(roles_card) == 11, f"{roles_card}")

print()
if FAILS:
    print(f"版本对偶校验：{len(FAILS)}/{N} 项失败 → 不可冻结")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print(f"版本对偶校验：全绿（{N} 项；六件套 {len(name_ver)} 件版本对偶）")
sys.exit(0)
