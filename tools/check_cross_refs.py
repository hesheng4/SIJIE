#!/usr/bin/env python3
"""check_cross_refs.py — 版本对偶绑定校验（D26，修 P0-2）。

机械校验三处一致（任一不一致即冻结失败）：
  ① 交付物抬头「依据《科研智能体总体方案 vN》」 == 总纲标题版本；
  ② 总纲 §12 验收基线中的交付物版本 == 交付物版本记录的「当前」版本；
  ③ 两侧基线 schema 清单 == schemas/ 目录实际文件版本。
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MASTER = ROOT / "科研智能体总体方案.md"
DELIV = ROOT / "阶段1交付物-声明卡Schema与反例测试规格.md"
S = ROOT / "schemas"

failures = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


master = MASTER.read_text(encoding="utf-8")
deliv = DELIV.read_text(encoding="utf-8")

# ① 总纲版本一致
m_master_title = re.search(r"总体方案（v(\d+)", master)
m_deliv_ref = re.search(r"依据《科研智能体总体方案 \*\*v(\d+)\*\*》", deliv)
check("① 交付物抬头引用的总纲版本 == 总纲标题版本",
      bool(m_master_title and m_deliv_ref
           and m_master_title.group(1) == m_deliv_ref.group(1)),
      f"master=v{m_master_title.group(1) if m_master_title else '?'}, "
      f"deliverable 引用=v{m_deliv_ref.group(1) if m_deliv_ref else '?'}")

# ② 交付物当前版本 == 总纲基线登记版本
m_deliv_cur = re.search(r"\*\*v(\d+\.\d+\.\d+)（当前）", deliv)
baselines = re.findall(r"交付物 v(\d+\.\d+\.\d+)", master)
check("② 总纲基线登记的交付物版本 == 交付物当前版本",
      bool(m_deliv_cur and m_deliv_cur.group(1) in baselines),
      f"deliverable 当前=v{m_deliv_cur.group(1) if m_deliv_cur else '?'}, "
      f"master 基线={baselines}")

# ③ 基线 schema 清单 == schemas/ 实际文件版本
EXPECT = ["ClaimCard **1.3.0**", "ClaimRow **1.1.0**", "PlanItem **1.0.1**",
          "ManifestEntry **1.0.0**", "Contracts **1.1.0**", "ExclusionList **1.0.2**"]
actual_versions = {}
for p in sorted(S.glob("*.json")):
    with open(p, encoding="utf-8") as f:
        sch = json.load(f)
    actual_versions[p.stem] = sch.get("version")
check("③a schemas/ 文件名版本 == 文件内 version 字段",
      all(p.split("-")[-1] == v for p, v in actual_versions.items()),
      str(actual_versions))
baseline_text = master.split("验收基线")[-1][:400] if "验收基线" in master else ""
baseline_text = baseline_text.replace("*", "")
missing = [s for s in EXPECT if s.replace("**", "") not in baseline_text]
check("③b 总纲基线枚举全部六件 schema", not missing, f"缺失: {missing}")
deliv_baseline = deliv.split("阶段验收基线")[-1][:400] if "阶段验收基线" in deliv else ""
deliv_baseline = deliv_baseline.replace("*", "")
missing_d = [s for s in EXPECT if s.replace("**", "") not in deliv_baseline]
check("③c 交付物基线枚举全部六件 schema", not missing_d, f"缺失: {missing_d}")

# 复合文件与基础文件同步（definitions 内嵌的版本一致）
row = json.loads((S / "claimrow-1.1.0.json").read_text(encoding="utf-8"))
check("③d ClaimRow 内嵌 ClaimCard 版本 == 1.3.0",
      row["definitions"]["ClaimCard"].get("version") == "1.3.0")
ct = json.loads((S / "contracts-1.1.0.json").read_text(encoding="utf-8"))
check("③e Contracts 内嵌 ExclusionList 版本 == 1.0.2",
      ct["definitions"]["ExclusionList"].get("version") == "1.0.2")

print()
if failures:
    print(f"版本对偶校验：{len(failures)} 项失败 → 不可冻结")
    sys.exit(1)
print("版本对偶校验：全绿")
