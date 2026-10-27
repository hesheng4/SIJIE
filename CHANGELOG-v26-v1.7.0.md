# 变更报告：阶段 1 冻结候选包优化（总纲 v26 / 交付物 v1.7.0）

> 依据：`.dsh-ops/panel/prior_report.md`（只读审计报告）+ 用户选择的 **A. 全量实施修复**。
> 冻结口径：**冻结 = 脚本全绿**；本文所有数字均可由第 6 节命令复算，不手抄。

---

## 1. 一句话结论

审计报告的 **4 项 P0 + 12 处文档漂移 + 主要 P2 项** 已全部落地为**机器可判定的门禁断言**：
原本「门禁全绿 ≠ 可冻结」的三处自欺（不读 markdown、非 RFC 8785 规范化、三条规则未落 schema）已消除，
门禁覆盖面从约 1/3 提升到语义/规则/一致性/确定性四层，且文档计数与口径由 `check_docs_consistency.py` 反向守护。

## 2. 修复对照（审计项 → 落地物 → 验证）

| 审计项 | 问题 | 落地物 | 验证 |
|---|---|---|---|
| P0-1 | 门禁不读任何 markdown；§1.2/§1.7 视图块**语法不可解析**，§1.6 与文件不相等 | `tools/gen_docs_views.py`（视图=权威源确定性投影：删 `$schema`/全部 `description`，ClaimRow 内嵌 card 换固定占位；`--check` 深比较 / `--write` 生成） | 三块视图重写后 `--check` 全绿；`check_docs_consistency.py` C7 常态守护 |
| P0-2 | `canonical()` 非 RFC 8785（`1.0`→`"1.0"`、`-0.0`、`1e-7`、`1e20`、UTF-16 码元排序均错），自测是同义反复 | 新增 `tools/jcs.py`（纯标准库：`canonical`/`canonical_number`/`sort_key`/`digest16` + RFC 8785 官方数字/字符串/排序向量） | `jcs.py --selftest` 35/35；门禁 G4 另做字节级断言（数字规范化、UTF-16 排序、转义、拒 nan/inf） |
| P0-3 | 三条 draft-07 可表达规则未落 schema（首行终态、hitl+rail、superseded 缺代签角色均可通过） | `schemas/claimcard-1.4.0.json`：新增 `definitions.Role`（十一角色唯一词表）、`transition.allOf` 三条 by_role↔credential_kind 配对、`to=superseded` 必带 `on_behalf_of_role`、顶层「无 transition ⇒ status=active」 | 门禁 G2 实例 I14–I20 正反例；I19 未登记角色、I18 缺代签角色均被拒 |
| P0-4 | PlanItem/ManifestEntry/ExclusionList/Contracts 无实例 fixture；C4 白名单断言未入门禁；错误码矩阵只覆盖 15 子例 | `validate_freeze.py` G1 补六件 fixture（含 C4 白名单注入 `rawlog_path` 必拒、payload 不属 C1–C8 必拒）；G3 校验码唯一性/全大写/八步链 20 码全覆盖 | G1 42 项、G3 7 项断言（含链层契约 L1–L5 登记完整性 G3e–G3g）；`tools/freeze_codes.py` 成为错误码单一事实源 |
| P1-5 | `check_cross_refs.py` ② 用全文档 `findall` + `in`，命中变更史历史版本 → 假阴性 | 重写为 `parse_baseline_deliv()`（只锚定「验收基线六件套」行）+ `parse_current_deliv()`；③b/③c 改结构化枚举；全部版本从 `schemas/*.json` 派生，零硬编码 | 18 项断言；`--selftest` 回归：伪造「变更史有 v1.7.0、基线行仍 v1.6.0」旧实现得 `['1.7.0','1.6.0']` 会误 PASS，新实现判不一致 |
| P1-6 | 12 处文档漂移（五文件/七步/十角色/T5a–e/D1–D24/66–69%/40–45%/十三断言/…） | 总纲 v26（+D27）、交付物 v1.7.0（+§十一 逐项对照）；同时新增 `tools/check_docs_consistency.py` C1–C8 使此类漂移**下次必然被机检拦下** | `check_docs_consistency.py` 67 项全绿（含 C4b 总纲断言数） |
| 漂移 #12 | ClaimRow `claimcard_schema_version` 自由 pattern，不绑定内嵌 card | 改为 `const` 绑定内嵌 `definitions.ClaimCard.version`（ClaimRow 1.2.0） | 门禁 G2 有反例（写 1.3.0 即拒）；`check_cross_refs` ④d 交叉验证 |
| P2 | n 网格与 max n 冲突、σ_d 隐含约束未写明 | 交付物 §六 重写：`n = 6.1832·σ_d²/(δ−|μ|)²`，检视点 99/124/149，max n=150 为终末判定点，反解 σ_d ≤ 1.48 | 交付物 §六 自洽；口径由 C2/C4 守护 |
| P2 | 脚本无 `__main__`/中文乱码/无分层退出码/无 `--check` | 全部脚本：`if __name__ == "__main__"` + `stdout.reconfigure(utf-8)` + 退出码 0/1/2；`gen_composites.py` 改 `--check`（默认只读）/`--write` | `bash run_gates.sh` 全绿 |
| P2 | 无工程化骨架 | `README.md`、`pyproject.toml`（锁 `jsonschema==4.26.0`）、`.gitignore`、`.github/workflows/gates.yml`、`run_gates.sh` | CI 配置就绪；本地门禁入口可跑 |

## 3. 判据分层（D27）

- **G1 语义层**：六件 schema 过 draft-07 meta-schema、`$ref` 全本地可解析、六件各有实例 fixture（含 C4 白名单注入拒收）。
- **G2 规则层**：ClaimCard 1.4.0 三条规则 + 十一角色词表 + ClaimRow 1.2.0 版本绑定（I01–I20）。
- **G3 一致性层**：错误码矩阵一一对应、全大写、八步链逐码覆盖（20 码）。
- **G4 确定性层**：RFC 8785 JCS 官方向量 + `row_id` 派生幂等（崩溃重试同 id、内容变化新 id、字节级可复算）。
- **文档层**：`check_docs_consistency.py` C1–C8 反向守护「文档自称的数字」（版本锚、禁止/必需口径、断言数、错误码来源、八步链覆盖、视图一致、结构完整性）。

## 4. 版本口径（本期基线）

总纲 **v26** · 交付物 **v1.7.0** · ClaimCard **1.4.0** · ClaimRow **1.2.0** · PlanItem **1.0.1** ·
ManifestEntry **1.0.0** · Contracts **1.1.0** · ExclusionList **1.0.2**。

## 5. 变更清单

**新增**：`tools/jcs.py`、`tools/freeze_codes.py`、`tools/gen_docs_views.py`、`tools/check_docs_consistency.py`、
`schemas/claimcard-1.4.0.json`、`schemas/claimrow-1.2.0.json`、`README.md`、`pyproject.toml`、`.gitignore`、
`.github/workflows/gates.yml`、`run_gates.sh`、本报告。
**重写**：`tools/validate_freeze.py`（v2，四层 82 断言）、`tools/check_cross_refs.py`（18 断言 + `--selftest`）。
**修改**：`tools/gen_composites.py`（`$ref` 文档相对解析 + `claimcard_schema_version const` + `--check/--write`）；
两份 md 升版并清零漂移。
**删除**：`schemas/claimcard-1.3.0.json`、`schemas/claimrow-1.1.0.json`、`tools/__pycache__/*.pyc`；
`.dsh-ops/`（会话遥测）移出版本库并加入 `.gitignore`。

## 6. 复算命令

```bash
bash run_gates.sh          # 全部门禁（0=绿 / 1=失败 / 2=依赖缺失）
python tools/validate_freeze.py --help 2>/dev/null || python tools/validate_freeze.py
python tools/check_docs_consistency.py   # 文档口径机检
python tools/check_cross_refs.py --selftest   # P1-5 假阴性回归
python tools/jcs.py --selftest           # RFC 8785 官方向量
```

## 7. 已知边界（不是缺陷）

1. **链层用例契约 L1–L5 待 M3**：`method 拒B / context 拒B / framing 拒B / 缺 on_behalf_of_role / 首行角色≠凭证` 在 `tools/freeze_codes.py::CHAIN_CONTRACTS` 结构化登记，
   门禁只校验登记完整性（G3e–G3g）+ 文档-码表对偶（C9），**不判定行为通过、不占 PASS 计数**——阶段 1 只冻结规格，链层运行时（八步编排）属 M1–M3；M3 回填后 `[REG ]` 转 PASS 才计数。
2. **非发行包**：本仓库是规格冻结候选包（schema + md + 门禁），不产出可安装 Python 包。
3. **CI 只跑 py3.12**：本地已验证 3.14；`jsonschema` 在 `pyproject.toml` 与 workflow 双处钉 `==4.26.0`，升级需同轮改两处并重跑断言。
4. **总纲 D26 行保留「（v25 新增）」溯源标记**：与 D20–D25「（vN 新增）」同体例，属决策溯源而非版本声明。
5. **`check_docs_consistency.py` 的 73 项是自身断言数**，与门禁 82 项不同源；两份文档只允许登记门禁实测 82（C4/C4b 守护）。

## 8. 增量 B（同版本补强，未改变版本口径）

用户「继续」后对三项遗留可继续项闭环，均**不新增版本号**（同 v26 / v1.7.0，属冻结前补强）：

| 项 | 原状态 | 本轮落地 | 验收 |
|---|---|---|---|
| ① 总纲 §12 工期假设 | 三条假设混在注记散文里，不可逐条推翻/校准 | 编号化为 **A1/A2/A3**，每条写明「若不成立 → 后果」，双轨口径标 (A1)、并行标 (A2)、区间标「依赖 A1–A3」；新增**校准协议**（M1 复用接口核实 + L1 PoC 回填后逐条替换重算） | 阅读即可定位被推翻哪条；算式自洽（5.5−0.5−0.5=4.5 ≥ A3 的 4） |
| ② 交付物 §十 实现细节 | 只有文件清单，四条工程化约束散落在 run_gates.sh 注释里 | §十 增「脚本工程化约定」四条硬约束（统一入口/退出码 0-1-2/单一事实源/清单与计数目录派生）+ 工程化外围（pyproject 钉 4.26.0、CI 双 OS×py3.12、.gitignore） | 读文档即可复现门禁行为，不必翻脚本 |
| ③ 链层契约登记化 | 5 项契约是散文枚举，`[REG ]` 只打印不计断言，无登记完整性校验 | `tools/freeze_codes.py::CHAIN_CONTRACTS` 结构化登记（id/场景/拦截步/码/M3 验收点）+ `CHAIN_CASES` 派生；门禁 **G3e/G3f/G3g**（id 连续/码属八步链/三通道+两凭证规则全覆盖）；交付物 §1.4 改登记表、§5.3 改登记口径；C9 校验文档↔码表对偶 | 门禁 79→**82 断言**（G3 4→7）；checker 67→**73 项**（C9 五项） |

**当前全绿口径**：`validate_freeze.py` 82 断言（G1 42 / G2 23 / G3 7 / G4 10）· `check_cross_refs.py` 18 项 ·
`check_docs_consistency.py` 73 项 · `gen_docs_views.py --check` 3/3 · `gen_composites.py --check` 2 件 · `jcs.py --selftest` 35/35。

## 9. M1 最小闭环（新增运行时代码与 GATE 6）

用户「继续」后，把「规格说能追溯」推进为「可运行的最小闭环」。**冻结对象与版本口径均未改变**（仍 v26 / v1.7.0 / ClaimCard 1.4.0），新增的是运行时代码与其行为门禁：

| 新增 | 内容 | 验收 |
|---|---|---|
| `m1/ledger.py` + `m1/__init__.py` | 最小账本：`row_id = "row_" + JCS(stable_projection).digest16`；落账前重算脚本/产物哈希；写序 rawlog → artifacts → 账本，每步 WAL 先行；`recover()` 回滚 pending / 补齐 rawlog_done；`audit()` 只读重放（链式 row_hash、row_seq 连续、账本↔rawlog 双射、产物仍在） | — |
| `tools/m1_acceptance.py` | 行为验收 31 项：A 幂等（8）· B hash 绑定与失败原子性（4）· C WAL 崩溃恢复（9）· D 双源对账（6）· E 重放确定性（4） | `M1 行为验收：全绿（31 项断言）` |
| `run_gates.sh` | 新增 **GATE 6**；`m1/` 或验收脚本缺失时降级 WARN（规格门禁不被运行时代码绑架） | 六 gate 全绿 |
| `README.md` | 新增「M1 最小闭环」章节 + 版本边界说明：`m1/` 不是 ledger-mcp，八步链其余步骤 / 全量 schema 校验 / rail / 快照与 DOI 仍属 M3 | — |

实现过程中被自己的断言抓出的一个真 bug：`row_id` 曾参与自身派生（`stable_projection` 未排除 `row_id` 字段），
导致「落账前的记录」与「读回的行」算不出同一个 id——审计会对正常账本报 `TAMPER_DETECTED`，幂等键也随之失效。
修法：`VOLATILE` 加入 `row_id`（派生结果是输出，不是输入）。

**未实现（M3 范围，明确不冒充）**：ClaimCard 全量 schema 校验、八步链第 2/3/6/7/8 步、六道 rail、快照/DOI 校验、
`audit_event_id` 签发。对账码 `UNCOMMITTED_EVENT`（rawlog 有事件而账本无行）与 `ARTIFACT_MISSING` 是 M1 局部码，
**故意不写进冻结文档**、不登记进 `freeze_codes.py`，以免文档与码表漂移。

**当前全绿口径**：六 gate —— `jcs.py --selftest` 35/35 · `gen_composites.py --check` 2 件 · `validate_freeze.py` 82 断言
（G1 42 / G2 23 / G3 7 / G4 10）· `check_cross_refs.py` 18 项 · `check_docs_consistency.py` 73 项 · `m1_acceptance.py` 40 项（v2，见 §10）。

## 10. M1 行为验收 v2（对齐 ClaimRow 真实 schema + 八步链步 1）

用户「继续」后按时给出的下一步建议实施：落账对象从 v1 的自造简化记录，换成**真实 `ClaimRow 1.2.0`**（内嵌 `ClaimCard 1.4.0`），并补上八步校验链的**第 1 步全量 schema 校验**。冻结对象与版本口径仍不变（v26 / v1.7.0 / ClaimCard 1.4.0 / ClaimRow 1.2.0）。

| 新增 / 变更 | 内容 | 验收 |
|---|---|---|
| `m1/ledger.py` | 行对象 = ClaimRow 1.2.0 冻结字段 + `prev_row_hash` / `row_hash` 两个**链式扩展字段**（schema 校验按冻结字段视图进行，不改冻结 schema）；`validate_card()` / `validate_row()` 抛 `SCHEMA_FAIL`；`date-time` 因本机缺 `rfc3339-validator` 改为自实现并强制注入；`audit_event_id` 改为确定性派生（幂等重放同值）；append 顺序 = stub → row_id → 幂等短路 → 步1 schema → 步4 hash → WAL → rawlog → 提交 | — |
| `tools/m1_acceptance.py` | 重写为 **40 项断言**：A 幂等（8）· B hash 与失败原子性（5）· C WAL（9）· D 双源对账（6）· E 重放（4）· **F 步 1 schema（8）** | `M1 行为验收：全绿（40 项断言；… / F 步1 schema）` |
| `README.md` | M1 章节改五条承诺（步1 schema / hash / 幂等 / WAL / 双源对账）、用法示例改真实 ClaimCard、边界重写（已实现步 1 + 步 4 子集） | — |

实现过程中被断言抓出的两个真 bug：

1. `VOLATILE` 漏了 `prev_row_hash` —— 该字段由前序行决定、却在稳定投影里，重派生 `row_id` 与落账时不一致，审计会对正常账本误报 `TAMPER_DETECTED`。
2. 自实现 `date-time` checker 返回 `None` —— `jsonschema.FormatChecker` 以**返回真值**判定通过，返回 `None` 会被当成失败，导致合法卡全部 `SCHEMA_FAIL`；修法：合法时返回 `True`。

**仍未实现（M3，明确不冒充）**：步 2/3/5/6/7/8、六道 rail、快照/DOI 校验、`audit_event_id` 签发。
