#!/usr/bin/env python3
"""build_submission_pkg.py — 打包初赛提交件（演示稿 + 参考文档）。

把 `projects/sijie_20261028/思解-openJiuwen创意大赛.pptx` 与仓库内的参考文档
（总体方案 / 阶段 1 规格 / CHANGELOG / README / RFC 8785 副本与取证记录 / 六件 schema）
打成一个 zip，目录规整、可直接提交或发给评审。

用法:
    python tools/build_submission_pkg.py            # 生成 dist/思解-openJiuwen创意大赛-初赛提交包.zip
    python tools/build_submission_pkg.py --out X.zip
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG_NAME = "思解-初赛提交包"
DECK = ROOT / "projects/sijie_20261028/思解-openJiuwen创意大赛.pptx"

DOCS: list[tuple[str, str]] = [
    ("科研智能体总体方案.md", "参考文档/01_科研智能体总体方案_v27.md"),
    ("阶段1交付物-声明卡Schema与反例测试规格.md", "参考文档/02_阶段1交付物_声明卡Schema与反例测试规格_v1.7.0.md"),
    ("CHANGELOG-v26-v1.7.0.md", "参考文档/03_CHANGELOG_v26-v1.7.0.md"),
    ("README.md", "参考文档/04_README_仓库说明.md"),
    ("demo/data/rfc8785.txt", "参考文档/05_RFC8785_正文副本.txt"),
    ("demo/data/RETRIEVAL.json", "参考文档/06_RFC8785_取证记录.json"),
]

README = """# 思解 · openJiuwen 智能体创意大赛（初赛）提交包

作品名称：**思解 SIJIE** —— 可被验证的科研论文生成系统
所属主题：科研赛道（科研写作 / 论文生成与验证）

## 包内容

```
思解-openJiuwen创意大赛.pptx     初赛提交稿（11 页，基于官方模板原生编辑，DrawingML 可编辑）
参考文档/
  01_科研智能体总体方案_v27.md                总体方案：八层架构、D1–D28 决策记录
  02_阶段1交付物_声明卡Schema与反例测试规格_v1.7.0.md  阶段 1 规格：六件 schema、八步校验链、反例矩阵
  03_CHANGELOG_v26-v1.7.0.md                版本变更说明（含各轮修复与复算口径）
  04_README_仓库说明.md                      仓库说明：门禁、复跑方式、目录结构
  05_RFC8785_正文副本.txt                    规范原文（候选"一手证据"示例）
  06_RFC8785_取证记录.json                   取回记录：URL / 时间 / 字节数 / sha256
  schemas/                                 六件冻结 schema（claimcard-1.4.0 等）
```

## 与演示稿的对应关系

| 演示稿位置 | 参考文档 |
|---|---|
| 第 4 页 架构图 | `01_科研智能体总体方案_v27.md` §2 八层架构 |
| 第 3 页 六项核心能力 | `02_...规格_v1.7.0.md` §1 |
| 第 6 页 证据管道端到端 | 仓库 `demo/run_e2e.py`（48 项检查）、`m1/` |
| 第 8 页 四层判据与七道门禁 | 仓库 `tools/`、`run_gates.sh`、`.github/workflows/gates.yml` |
| 第 10 页 参考文档 | 本目录 |

## 自查方式（可选）

仓库：https://github.com/hesheng4/SIJIE
一条命令复跑全部门禁（需 Python 3.12+ 与 jsonschema 4.26.0，离线可跑）：

```bash
bash run_gates.sh      # 七道门禁，退出码 0=全绿
```

## 边界说明

第 6 页的端到端演示验证的是**证据管道**（哈希绑定 → 指针取值 → 引用核对 → 落账 → 双源对账），
检索环节使用固定快照，agent 编排在生产化阶段落地（见第 9 页 M3 计划）。
"""


def build(out: pathlib.Path) -> pathlib.Path:
    if not DECK.exists():
        raise SystemExit(f"缺少演示稿：{DECK}")
    stage = out.parent / PKG_NAME
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "参考文档" / "schemas").mkdir(parents=True)

    shutil.copy2(DECK, stage / DECK.name)
    for src_rel, dst_rel in DOCS:
        src = ROOT / src_rel
        if not src.exists():
            raise SystemExit(f"缺少参考文档：{src}")
        shutil.copy2(src, stage / dst_rel)
    for f in sorted((ROOT / "schemas").glob("*.json")):
        shutil.copy2(f, stage / "参考文档" / "schemas" / f.name)
    (stage / "README-提交说明.md").write_text(README, encoding="utf-8")

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                z.write(p, pathlib.Path(PKG_NAME) / p.relative_to(stage))
    shutil.rmtree(stage)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="打包初赛提交件（演示稿 + 参考文档）")
    ap.add_argument("--out", default="dist/思解-openJiuwen创意大赛-初赛提交包.zip")
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    zp = build(out)
    with zipfile.ZipFile(zp) as z:
        files = [i for i in z.infolist() if not i.is_dir()]
    print(f"提交包：{zp}（{zp.stat().st_size:,} bytes，{len(files)} 个文件）")
    for i in files:
        print(f"  {i.file_size:>9,}  {i.filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
