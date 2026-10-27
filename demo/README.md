# 端到端演示：用真实数据跑一遍八步链

这个目录不是规格文档，而是**可执行的证据**：用真实数据把 `m1/` 的八步链完整走一遍，
每一步都真实触发，并且对每一步都构造一个「只改一处」的负例，断言它被对应的冻结错误码拒绝。

```bash
python demo/run_e2e.py          # 从零重建：清空 demo/.store，重跑全链路
bash run_gates.sh               # 其中 GATE 7 就是本演示
```

实测结果（2026-10-27）：**48 项检查全绿**，账本 3 行，`audit()` 无 findings。

## 真实数据是什么

| 数据 | 来源 | 关键数字 |
|---|---|---|
| `data/rfc8785.txt` | `GET https://www.rfc-editor.org/rfc/rfc8785.txt`（HTTP 200） | 41,879 bytes；字节 sha256 `sha256:63d52294…c3ab240`；DOI `10.17487/RFC8785` |
| `data/RETRIEVAL.json` | 上面这次取回的取证记录 | URL / DOI / `retrieved_at` / 状态码 / 字节哈希 |
| `data/git-log.tsv` | 本仓库 `git log --numstat --format='commit %H %aI'` | 11 次提交、80 条文件改动、8 个二进制文件、+24,104 / −1,990 行 |

RFC 8785 是 JCS 的规范本身，本仓库的 `tools/jcs.py` 正是按它实现的——所以它在这里既是
「检索到的一手文献」，也是「被验证对象的方法学出处」，不是随便找的一段引文。

## 八步各自被什么触发（正例）

| 步骤 | 演示中的真实动作 | 账本里的证据 |
|---|---|---|
| 步 0 六道 rail | `RailContext` 限定本轮可产出 `result`/`context`，禁用 `proprietary` 许可，登记审批人 | 六条决策全部 ALLOW，才进入下一步 |
| 步 1 schema | 两张 **ClaimCard 1.4.0** 卡（`result` + `context`）逐字段校验 | `claim_id=clm_1e6dee97…`、`clm_570b2eda…` |
| 步 2 执行溯源 | 真实跑 `demo/scripts/git_commit_stats.py`（0.3 s），登记 `exec_203fee8ec6748021`，`verify_event_chain()` 通过 | rawlog 事件链 1 条 → 3 条 |
| 步 3 上下文传递 | `Record` 的 `manifest_version` 与 `RunContext` 一致；`data_refs[0].data_hash` == MANIFEST 数据条目哈希 | `TRANSPORTIVITY` 通过 |
| 步 4 hash 绑定 | 脚本、产物都以内容寻址入库；`plan_ref` 指向登记的 PlanItem | `script_hash=sha256:d36b43a4…`、`artifact_hash=sha256:c9b51b95…` |
| 步 5 取值比对 | RFC 6901 指针 `/n_commits`（exact=11）、`/lines_per_commit_median`（float_rel=799.0） | 两个 `values` 指针都命中 |
| 步 6 引用一致性 | 引用 RFC 8785 `verification=primary`，locator `sec 3.2.2.3` 在条目白名单内，快照在快照库 | `snapshot_ref=sha256:caec2968…` |
| 步 7 偏差标注 | 两张卡都是 `confirmatory`；如改 `exploratory` 则必须写 `deviation_note` | — |
| 步 8 落账 | 两次 `append` 得到 `row_57cebcd0…`（seq 1）、`row_7a6615dd…`（seq 2）；同卡再 append → `duplicate=True` | WAL 写完即清 |

## 负例：每一步的拒绝能力（都用真实数据改一处）

| 步骤 | 构造方式 | 期望错误码 | 实测 |
|---|---|---|---|
| 1 | `claim_text` 过短 | `SCHEMA_FAIL` | ✅ |
| 1 | 角色写 `owner`（1.4.0 已废除） | `SCHEMA_FAIL` | ✅ |
| 2 | 执行编号未登记 | `EXEC_UNRESOLVED` | ✅ |
| 2 | 执行状态为 `rejected` | `EXEC_REJECTED` | ✅ |
| 3 | 数据哈希换成另一个 | `TRANSPORTIVITY_FAIL` | ✅ |
| 3 | 拿文献条目冒充数据条目 | `MANIFEST_CONTEXT_MISMATCH` | ✅ |
| 4 | 产物哈希不存在 | `ARTIFACT_UNREACHABLE` | ✅ |
| 4 | 计划未登记 | `PLAN_UNBOUND` | ✅ |
| 4 | 脚本哈希与计划不符 | `PLAN_MISMATCH` | ✅ |
| 5 | 声称 999 次提交 | `VALUE_LOCATOR_FAIL` | ✅ |
| 5 | `output_index=1`（只有一个产物） | `OUTPUT_INDEX_OUT_OF_RANGE` | ✅ |
| 5 | 指针指向不存在的字段 | `VALUE_LOCATOR_FAIL` | ✅ |
| 6 | DOI 不在本轮 MANIFEST | `DOI_NOT_IN_MANIFEST` | ✅ |
| 6 | locator `sec 9.9` 不在白名单 | `CITATION_LOCATOR_FAIL` | ✅ |
| 6 | primary 的快照不在快照库 | `SNAPSHOT_MISSING` | ✅ |
| 6 | 综述转述挂 `supporting` 条目 | `BACKBONE_GRADE_VIOLATION` | ✅ |
| 7 | `exploratory` 未写偏差说明 | `DEVIATION_UNNOTED` | ✅ |
| 0 | 禁用许可（`IETF-Trust-BCP78`） | `COMPLIANCE_LICENSE_FORBIDDEN` | ✅ |
| 0 | 本轮不允许 `context` 类声明 | `INFERENCE_SCOPE_OUT_OF_SCOPE` | ✅ |
| 0 | 预算耗尽 | `BUDGET_EXCEEDED` | ✅ |

所有负例都在**落账前**被拒，账本行数保持不变（演示脚本逐条断言）。

## 审计与恢复（同样用真实账本验）

| 破坏方式 | `audit()` 报告 | 恢复 |
|---|---|---|
| 改写 `claims/CLAIMS.jsonl` 里一行 `claim_text` | `TAMPER_DETECTED`（row_hash / row_id / audit_event_id 三处同时不符） | 还原备份后重新通过 |
| 删掉 rawlog 里一条 claim 事件 | `PHANTOM_EVENT` | 还原后重新通过 |
| 删掉产物副本 | `ARTIFACT_MISSING` | 还原后重新通过 |
| 崩溃注入：rawlog 已写、账本未写 | `UNCOMMITTED_EVENT` | `recover()` → `rolled_back=1`，账本仍 2 行 |
| 崩溃注入：账本已写、WAL 未清 | — | `recover()` → `finished=1`，WAL 清空 |

## 文件

| 文件 | 说明 |
|---|---|
| `run_e2e.py` | 演示编排：检索 → 脚本 → 数值 → 引用 → 落账 → 审计 + 负例 |
| `scripts/git_commit_stats.py` | 被落账的统计脚本（只解析传入的 TSV，不读网络/工作树，可重放） |
| `data/rfc8785.txt` | 真实取回的 RFC 正文（步 6 的一手快照） |
| `data/RETRIEVAL.json` | 取回取证记录（URL/DOI/时间/字节哈希） |
| `data/git-log.tsv` | 真实 git 历史导出（步 3/5 的数据源） |
| `.store/`、`out/` | 演示产生的账本与产物（已 gitignore，可由 `run_e2e.py` 重建） |

## 边界

- 这是 **M1 单机参考实现**的端到端演示：账本是本地 JSONL + WAL，不是 ledger-mcp 服务，也没有
  并发写仲裁、远端 CAS、策略热更新（这些属 M3）。
- 「检索」这一步没有接真实检索服务，而是把一次真实 HTTP 取回的文件与其取证记录固定下来，
  保证离线可重放；换数据只需替换 `data/` 与 `RETRIEVAL.json`，八步链的其他部分不用改。
- 数值结论只用于演示链路（「11 次提交、中位数 799 行」），没有研究意义。
