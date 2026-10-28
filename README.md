# 科研智能体系统 · 阶段 1 冻结候选包

基于 [WorkSwarm（jiuwenswarm）](科研智能体总体方案.md) 蜂群平台的**证据来源可插拔、可审计、可自演进**科研论文生成系统的**阶段 1 规格冻结候选包**。

本仓库当前交付的是**可证伪的规格与门禁**，不是可运行的系统：

- 两份 Markdown 规格：[总纲](科研智能体总体方案.md)（设计决策 D1–D27、8 层架构、路线图、验收）+ [阶段 1 交付物](阶段1交付物-声明卡Schema与反例测试规格.md)（schema 族、八步校验链、反例矩阵、交接契约、阈值口径）；
- 六件 JSON Schema（`schemas/`）：ClaimCard / ClaimRow / PlanItem / ManifestEntry / Contracts / ExclusionList；
- 四层机检门禁（`tools/`，G1 语义 / G2 规则 / G3 一致性 / G4 确定性），以及一个统一入口 [run_gates.sh](run_gates.sh)。

核心命题是**声明级（claim-level）证据绑定**：任何进正文的数字都必须挂在沙箱执行 + 脚本哈希 + 产物定位 + MANIFEST 条目上；结构约束只证明「无执行记录的数值不能入账」，不证明计算正确性（计算正确性由预注册三方绑定 + Auditor 重放 + 评审共保）。

---

## 目录结构

```
.
├── 科研智能体总体方案.md                  # 总纲（设计决策 / 架构 / 路线图 / 验收）
├── 阶段1交付物-声明卡Schema与反例测试规格.md # 阶段 1 交付物（schema 族 / 八步链 / 反例矩阵 / 契约）
├── schemas/
│   ├── claimcard-1.4.0.json              # 声明卡：三类规则 + 11 角色词表（definitions.Role）
│   ├── claimrow-1.2.0.json               # 复合权威源：ClaimRow 结构 + 内嵌 ClaimCard 全文
│   ├── contracts-1.1.0.json              # 复合权威源：契约信封 + C1–C8 + 内嵌 ExclusionList
│   ├── exclusionlist-1.0.2.json          # 排除清单（reused / created 双分支）
│   ├── manifestentry-1.0.0.json          # MANIFEST 条目（data / literature 两 kind）
│   └── planitem-1.0.1.json               # 预注册计划项
├── tools/
│   ├── jcs.py                            # RFC 8785 JCS（确定性序列化，35 官方向量自测）
│   ├── gen_composites.py                 # 复合件生成器（--check / --write）
│   ├── validate_freeze.py                # 冻结门禁 G1–G4（82 项断言，退出码 0/1/2）
│   ├── check_cross_refs.py               # 版本对偶绑定校验（文档 ↔ 文档 ↔ schemas/）
│   ├── check_docs_consistency.py         # 文档口径机检（计数/枚举/版本/错误码/视图）
│   ├── gen_docs_views.py                 # 交付物内嵌 JSON 视图生成/校验（--check / --write）
│   ├── freeze_codes.py                   # 错误码单一码表
│   └── m1_acceptance.py                  # M1 行为验收（76 项断言，GATE 6）
├── m1/
│   ├── __init__.py                       # M1 包导出
│   ├── manifest.py                       # MANIFEST 注册表 + 正文快照库（步 3 / 步 6 的权威源）
│   ├── rails.py                           # 六道 rail：CitationGate/Provenance/InferenceScope/Compliance/Budget/HITL
│   └── ledger.py                          # 账本 + 事件链 + 八步链 + 签发 + WAL 恢复 + 双源对账
├── run_gates.sh                          # 门禁统一入口（bash；git-bash / WSL / Ubuntu）
├── .github/workflows/gates.yml           # CI：ubuntu + windows × Python 3.12
├── pyproject.toml                        # 依赖元数据（jsonschema==4.26.0；非发行包）
└── .gitignore                            # 忽略 __pycache__ / *.pyc / .dsh-ops/ 等
```

`schemas/claimrow-1.2.0.json` 与 `schemas/contracts-1.1.0.json` 是**复合权威源**：它们内嵌基础 schema 的全文，保证 `$ref` 全部本地可解析、可被 `jsonschema` 直接加载。基础文件变更后必须运行 `python tools/gen_composites.py --write` 重新生成，`--check` 在门禁中守护两者一致。

## 版本对照表

| 产物 | 权威文件 | 版本 |
|---|---|---|
| 总纲 | [科研智能体总体方案.md](科研智能体总体方案.md) | **v26** |
| 阶段 1 交付物 | [阶段1交付物-声明卡Schema与反例测试规格.md](阶段1交付物-声明卡Schema与反例测试规格.md) | **v1.7.0** |
| ClaimCard | [schemas/claimcard-1.4.0.json](schemas/claimcard-1.4.0.json) | **1.4.0** |
| ClaimRow | [schemas/claimrow-1.2.0.json](schemas/claimrow-1.2.0.json) | **1.2.0** |
| PlanItem | [schemas/planitem-1.0.1.json](schemas/planitem-1.0.1.json) | **1.0.1** |
| ManifestEntry | [schemas/manifestentry-1.0.0.json](schemas/manifestentry-1.0.0.json) | **1.0.0** |
| Contracts | [schemas/contracts-1.1.0.json](schemas/contracts-1.1.0.json) | **1.1.0** |
| ExclusionList | [schemas/exclusionlist-1.0.2.json](schemas/exclusionlist-1.0.2.json) | **1.0.2** |

版本对偶绑定规则（D26）：文档族任一侧修订必须同轮双向更新三处——①交付物抬头「依据总纲 vN」；②总纲「阶段验收基线六件套」行；③两侧基线 schema 清单。`tools/check_cross_refs.py` 机械校验，任一不一致即冻结失败。

## 四层门禁 G1–G4

`python tools/validate_freeze.py` 一次跑完四层，共 **82 项断言**（G1: 42 / G2: 23 / G3: 7 / G4: 10）；链层契约 L1–L5 按结构化登记校验完整性（G3e–G3g，契约本体 `tools/freeze_codes.py::CHAIN_CONTRACTS`），行为验收待 M3 回填，不参与断言计数。

| 层 | 判据（含义） | 覆盖要点 | 实测 |
|---|---|---|---|
| **G1 语义层** | 六件 schema 通过 draft-07 meta-schema；`$ref` 全部本地可解析；每件都有正/反例实例 fixture | 文件名版本 == 文件内 `version`；ExclusionList `oneOf`、Contracts `payload` `oneOf`、`date-time` 格式断言；C4 白名单注入 `rawlog_path` 必须拒绝（SCHEMA_FAIL） | 42 PASS |
| **G2 规则层** | ClaimCard 1.4.0 三条 draft-07 可判定的机器规则 + 角色词汇统一 | ①首行无 transition 时 `status` 仅 `active`（D23②）；②`by_role` ↔ `credential_kind` 配对；③`superseded` 必带 `on_behalf_of_role`；11 角色词表与 Contracts 枚举一致；ClaimRow 行级封闭 + `claimcard_schema_version` 与内嵌 card 版本绑定 | 23 PASS + 5 REG |
| **G3 一致性层** | 错误码矩阵一致性 | 15 子例 ↔ 错误码一一对应（无跨例双属）；码全大写且匹配 `^[A-Z][A-Z0-9_]*$`；八步校验链错误码全覆盖；码表规模 17 + 8 = 25 | 4 PASS + 8 REG |
| **G4 确定性层** | RFC 8785（JCS）实测 + `row_id` 派生幂等 | 35 官方数字/字符串/排序向量；`1.0→1`、`-0.0→0`、`1e20`、UTF-16 码元排序；拒绝 NaN/Infinity；崩溃重试同一 `row_id`、重放 hash 稳定、字节级可复算 | 10 PASS |

### 门禁入口与退出码

| 步骤 | 命令 | 校验对象 |
|---|---|---|
| 1 | `python tools/jcs.py --selftest` | RFC 8785 实现（35 向量，35/35） |
| 2 | `python tools/gen_composites.py --check` | 复合件与生成结果一致（2 件） |
| 3 | `python tools/validate_freeze.py` | 四层判据 G1–G4（82 断言） |
| 4 | `python tools/check_cross_refs.py` | 版本对偶绑定（文档 ↔ 文档 ↔ schemas/） |
| 5 | `python tools/check_docs_consistency.py` | 文档口径一致性（计数/枚举/旧版本残留/错误码/内嵌视图，依赖 `gen_docs_views.py --check`） |
| 6 | `python tools/m1_acceptance.py` | M1 行为验收（八步链正反例 / 事件链与签发 / 六道 rail 集成 / WAL 恢复 / 双源对账） |

统一入口：

```bash
bash run_gates.sh
echo "exit=$?"
```

- 退出码 **0** = 全绿（`check_docs_consistency.py` 尚未落地时该项降级为 WARN，不计失败）；
- 退出码 **1** = 至少一项门禁真实失败（`run_gates.sh` 逐项执行后汇总，不因首项失败中断）；
- 退出码 **2** = 依赖缺失（找不到 `python` / 缺 `jsonschema` / 某门禁自报依赖异常）；
- 每一步打印 `[GATE] 名称`、实际命令、`rc` 与 `PASS/FAIL/MISSING-DEP`，末尾给出汇总表。

> 门禁输出为 UTF-8 中文。`run_gates.sh` 会 `export PYTHONIOENCODING=utf-8`（Windows cp936 控制台必需），并设 `PYTHONDONTWRITEBYTECODE=1` 避免往仓库落 `__pycache__`。手工单跑门禁时请自行设置 `PYTHONIOENCODING=utf-8`。

## M1 行为实现（`m1/`，可运行参考实现）

规格说「每项声明都要能追溯到数据、执行与产物」，而「能追溯到」只有做出来才成立。`m1/` 把交付物 §1.3 的**八步校验链**与总体方案 §2 可信门层的**六道 rail**做成可运行实现；落账对象是真实的 `ClaimRow 1.2.0`（内嵌 `ClaimCard 1.4.0`），供 M3 的 ledger-mcp 直接演化（`m1/manifest.py` 是步 3/6 的权威源，`m1/rails.py` 是六道门，`m1/ledger.py` 是账本与八步链）。

| 步 / 门 | 实现 | 行为证据（GATE 6） |
|---|---|---|
| **步 1 · schema** | `schemas/claimcard-1.4.0.json` + `claimrow-1.2.0.json` 全量校验（含 7 条 `allOf`、11 角色词表、`date-time` 自实现），行按冻结字段视图校验（`prev_row_hash` / `row_hash` 为 M1 扩展字段，不进 schema） | result 缺 `values`、framing 带 `evidence`、首行 `superseded`、未登记角色、非法 `audit_event_id`、版本不符 → `SCHEMA_FAIL`，失败不落账 |
| **步 2 · 执行溯源** | `record_execution()` 把执行写进 rawlog **事件链**（每步带 `prev_event_hash`、`event_id` 由 HMAC 签发，每 1000 事件写 checkpoint）；落账前验链并核对执行状态 | 未登记 → `EXEC_UNRESOLVED`；`failed` / 审计不可用 → `EXEC_REJECTED`；事件被改写或冒签 → `EXEC_CHAIN_FAIL` |
| **步 3 · MANIFEST 上下文** | 行 `manifest_version` 必须等于本轮 `RunContext`；`data_refs[]` 必属数据条目且条目哈希等于 `data_hash` | 哈希漂移 → `TRANSPORTIVITY_FAIL`；指向文献条目 / 版本不符 / 不挂 MANIFEST → `MANIFEST_CONTEXT_MISMATCH` |
| **步 4 · hash 绑定** | 重算脚本库与产物库；`figure_hashes ⊆ output_hashes`；`plan_ref` 解析到 PlanItem 且 `expected_script_hash` 相符 | 脚本/产物被改 → `HASH_MISMATCH`、`ARTIFACT_UNREACHABLE`；figure 未绑 → `FIGURE_HASH_UNBOUND`；plan 未登记/错配 → `PLAN_UNBOUND` / `PLAN_MISMATCH`（exploratory 带偏差注记可降级） |
| **步 5 · 数值定位** | 产物按 RFC 6901 pointer 或 `csv:<列>[:行]` 取值，`exact` 按转型全等、`float_rel` 按容差比较 | 越界 → `OUTPUT_INDEX_OUT_OF_RANGE`；定位失败或值与声明不符 → `VALUE_LOCATOR_FAIL` |
| **步 6 · 引用一致性** | `m1/manifest.py`：DOI 必属本轮文献条目、`locator` 在可解析白名单、`primary` 必带快照且快照在库、`survey_transfer` 的 survey 与 `framing` 必为 `backbone` | `DOI_NOT_IN_MANIFEST` / `CITATION_LOCATOR_FAIL` / `SNAPSHOT_MISSING` / `BACKBONE_GRADE_VIOLATION` |
| **步 7 · 偏差标注** | `exploratory` 卡必须带 `lineage.deviation_note` | 缺失 → `DEVIATION_UNNOTED` |
| **步 8 · 落账** | `row_id` 幂等短路；`row_seq` 被占且内容不同即冲突；`audit_event_id` 由 HMAC 签发（密钥落盘 `audit_key`，同密钥下确定 ⇒ 重放幂等） | 序号冲突 → `ROW_CONFLICT`；伪造 `audit_event_id` → 对账报 `TAMPER_DETECTED` |
| **六道 rail** | `m1/rails.py`：CitationGate / Provenance / InferenceScope / Compliance / Budget / HITL，`evaluate()` 恒返回六条决策，`ledger.append(context=...)` 在步 1 前预检 | 超预算、声明越界、许可禁用、framing 无审批人 → BLOCK 拒绝且不落账；六条全 ALLOW → 正常落账 |

```python
from m1 import Entry, Ledger, Manifest, RunContext
from m1.rails import RailContext

led = Ledger(".m1store")          # claims/ rawlog/ artifacts/ scripts/ snapshots/ wal/ audit_key
script = led.store_script(b"print('mean=0.42')\n")     # 内容寻址入库，返回 sha256:…
artifact = led.store_artifact(b'{"mean": 0.42}')       # 步 5 的定位对象
snapshot = led.store_snapshot("原文快照：表 2，p.12")     # 步 6 的一手正文
led.register_plan("pln_0f1e2d3c4b5a", script)          # 步 4 的 PlanItem
led.record_execution("exec_a1b2c3d4e5f60718")          # 步 2：执行登记进事件链

manifest = Manifest("MANIFEST#7", entries=[
    Entry("mfe_0f1e2d3c4b5a", "data", sha256=artifact),
    Entry("mfe_1a2b3c4d5e6f", "literature", doi="10.1234/abc", role="backbone",
          snapshot_ref=snapshot, locators=("p.12",), license="cc-by"),
])
run_context = RunContext("run_01", "MANIFEST#7", "runctx_01", manifest)
rails = RailContext(allowed_claim_types=("result", "method"), human_approver="hitl-01")

led.append(card, manifest=manifest, run_context=run_context, context=rails)
led.append(card, manifest=manifest, run_context=run_context)   # 幂等：duplicate=True
led.recover()                     # 崩溃后调用：回滚 pending、补齐 rawlog_done
led.audit().ok                    # True = 账本与原始日志（含事件链）一致
```

**边界（不要过度解读）**：`m1/` 是可运行参考实现，**不是 ledger-mcp**。已实现八步链的判定逻辑、事件链与签发、六道 rail；未实现的是生产件——多写并发仲裁、远端对象存储、MCP 服务面、rail 策略热更新、`reject_log` 落盘。`prev_row_hash` / `row_hash` 是 M1 的链式扩展字段，**不写进冻结 schema**（避免改冻结版本）；对账码 `UNCOMMITTED_EVENT` / `ARTIFACT_MISSING` 与 rail 策略码是 M1 局部码，未登记进 `tools/freeze_codes.py`，因此不写进冻结文档（避免文档与码表漂移）。


## 端到端演示（`demo/`）

规格能写成文档，『能拒绝』得跑起来才算数。`demo/` 用**真实数据**把八步链走一遍：

- 数据：`GET https://www.rfc-editor.org/rfc/rfc8785.txt` 真实取回的 RFC 8785 正文（41,879 bytes，取证记录在 `demo/data/RETRIEVAL.json`）+ 本仓库真实 `git log --numstat` 导出（11 次提交）；
- 链路：检索 → 脚本真实执行 → 产物内容寻址 → RFC 6901 取值比对 → primary 引用 + 一手快照 → 八步校验后落账 → 双源对账；
- 负例：对每一步构造「只改一处」的卡片，断言被对应冻结码拒绝（`SCHEMA_FAIL` / `TRANSPORTIVITY_FAIL` / `PLAN_MISMATCH` / `VALUE_LOCATOR_FAIL` / `CITATION_LOCATOR_FAIL` / `SNAPSHOT_MISSING` / `TAMPER_DETECTED` … 共 20 条）；
- 实测：**48 项检查全绿**，账本 3 行，`audit()` 无 findings；`bash run_gates.sh` 的 **GATE 7** 即此演示。

```bash
python demo/run_e2e.py        # 从零重建账本并跑完整链路（数据与脚本入库，账本/产物可重建）
```

细节见 [`demo/README.md`](demo/README.md)。

## 初赛提交稿（`projects/`）

openJiuwen 智能体创意大赛的初赛稿不是手工拼的，是这条流水线生成的：

- 成品：[projects/sijie_20261028/思解-openJiuwen创意大赛.pptx](projects/sijie_20261028/思解-openJiuwen创意大赛.pptx) —— 11 页，基于官方模板逐页**原生编辑**（DrawingML 可编辑，非图片拼贴）；
- 源：`sources/source.pptx`（模板原件）+ `authoring-svg-flat/*.svg`（每页一层 SVG）+ `author_pages.py`（内容写入脚本，从 `_pristine/` 复原后幂等重跑）；
- 校验链：`svg_quality_checker.py --roundtrip`（11/11）→ `svg_to_pptx.py --roundtrip`（postflight passed）→ `pptx_delivery_check.py`（0 error）。

```bash
cd projects/sijie_20261028
python author_pages.py        # 改文案/版式后重跑（幂等）
```

`exports/`、`analysis/`、`validation/`、`.ppt-inspect/` 与 `*.备份.pptx` 都是一次性或可重建产物，已在 `.gitignore` 中排除。

## 本地运行

前置条件：

- Python **≥ 3.11**（CI 使用 3.12；本地实测 3.14）；
- `bash`（Windows 用 Git Bash / WSL；CI 的 `windows-latest` 走 Git Bash）；
- 门禁唯一硬依赖 `jsonschema==4.26.0`（`date-time` 断言由 `validate_freeze.py` 自实现，**不需要** `rfc3339-validator`）。

```bash
python -m pip install "jsonschema==4.26.0"   # 或: pip install -e . / pip install ".[dev]"
bash run_gates.sh
```

单条门禁（便于定位失败项）：

```bash
python tools/jcs.py --selftest
python tools/gen_composites.py --check
python tools/validate_freeze.py
python tools/check_cross_refs.py
python tools/check_docs_consistency.py
python tools/m1_acceptance.py
```

预期终态输出摘要：`jcs 35/35 passed`、复合件 2 件一致、`冻结门禁：全绿（82 项断言；G1: 42 / G2: 23 / G3: 7 / G4: 10；链层用例契约 5 项待 M3）`、版本对偶校验全绿、文档一致性全绿（含 3 处内嵌视图 `gen_docs_views.py --check`）、`M1 行为验收：全绿（76 项断言；A 幂等 / B 步1 / C 步2 / D 步3 / E 步4 / F 步5 / G 步6 / H 步7 / I 步8 / J rail）`。当前若仍有门禁为红，以 `run_gates.sh` 汇总为准。

仅在基础 schema 变更后需要重新生成复合件（会覆写 `schemas/`，正常提交前必须跑 `--check` 确认）：

```bash
python tools/gen_composites.py --write
python tools/gen_docs_views.py --write   # 同步交付物内嵌视图
```

## CI

[.github/workflows/gates.yml](.github/workflows/gates.yml)：

- 触发：`push` / `pull_request`（只校验，不部署、不发版）；
- 矩阵：`ubuntu-latest` × `windows-latest`，Python `3.12`；
- 步骤：`actions/checkout` → `actions/setup-python` → `pip install "jsonschema==4.26.0"` → `bash run_gates.sh`（Windows 上使用 Git Bash）；
- 与本地等价：CI 只多一层「干净环境安装依赖」，门禁判断完全由 `run_gates.sh` 承担（单入口，避免 CI 与本地两套口径漂移）。

## 状态与边界

- **阶段 1 = 规格冻结**：本包交付「冻结对象 + 冻结判据」，**无运行时实现**——ledger-mcp、六道 rail（ClaimCardRail / AuditRail / CitationGate / …）、沙箱执行、编排流水线均未实现。
  - 例外且已标注边界：`m1/` 是**可运行参考实现**（八步链判定 + 事件链与签发 + 六道 rail，76 项行为断言），用于把规格变成可测行为；它不是 ledger-mcp，未实现的部分是生产件（多写并发仲裁、远端存储、MCP 服务面、策略热更新、`reject_log`），行为验收范围见上一节表格。
- **登记未实现项**：链层契约 L1–L5（八步链专有错误码 8 项）以 `REG` 登记，门禁校验登记完整性；行为待 ledger-mcp 落地后由 **M3** 验收，不计入 82 项断言。
- **视图即生成物**：交付物 §1.2 / §1.6 / §1.7 的 JSON 视图块由 `tools/gen_docs_views.py` 机生成，`--check` 已入门禁，禁止手改。
- **非发行包**：`pyproject.toml` 只用于锁定依赖与 Python 版本（`packages = []`），不产出可安装包、不发布。
- **会话遥测不入库**：`.dsh-ops/`（DSH 会话面板/遥测）已在 `.gitignore` 中排除，不属于项目产物。

## 已知限制与待办

- **CI 依赖策略**：`jsonschema` 在 `pyproject.toml` 与 `gates.yml` 两处均钉死 `==4.26.0`（门禁实测版本）。升级依赖需同轮改两处并重跑全部门禁；如需放宽到区间版本，应先确认 4.26.0 之外的 draft-07 `oneOf`/`format` 行为无回归。
- **Python 版本矩阵**：CI 仅验证 3.12；`requires-python >= 3.11` 的下界未进 CI。需要覆盖 3.11/3.13 时扩 matrix。
- **索引清理已完成**：`tools/__pycache__/` 与 `.dsh-ops/` 的历史跟踪项已在优化提交中一次清掉（`git rm -r --cached` + 删除 `__pycache__`），当前 `git ls-files` 不含这两类路径；`.gitignore` 继续阻止其再次入库（含 `.archify/` 生成目录）。
- **阶段 2+ 待补**：TOST 校准回填、σ_d 可行域、外部锚（66–69% 与构念重建）等口径见两份 md 的待办与 D26/D27 登记。

## 参考

- 总纲：[科研智能体总体方案.md](科研智能体总体方案.md)（D1–D27、架构、路线图、§验收）
- 交付物：[阶段1交付物-声明卡Schema与反例测试规格.md](阶段1交付物-声明卡Schema与反例测试规格.md)（§一 schema 族 / §1.3 八步链 / §三 反例矩阵 / §五 冻结判据 / §十一 修订对照）
