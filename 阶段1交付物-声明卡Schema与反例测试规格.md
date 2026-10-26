# 阶段 1 交付物：声明卡 Schema v1 + 反例测试规格 + 交接契约最小集合

> 依据《科研智能体总体方案 **v26**》**D13–D27**。本文档为阶段 1 冻结对象，**自包含**。
> **变更史**：v1.0.0=依 v12；v1.1.x–v1.2.x=对齐 v15–v20；v1.3.0=D23 修订一；v1.4.0=D24 修订二；v1.5.0=D25 一致性清零；v1.5.1=自包含勘误；v1.6.0=D26 机器可判定性清零（P0 四项 + P1 十二项 + P2 九项）。
> **版本记录**：**v1.7.0（当前）=D27 文档门禁化**：冻结判据由清单式改为**四层判据 G1–G4**（82 项断言）、三处内嵌视图改由 `tools/gen_docs_views.py` 机生成并守护、v1.6.0 残留的 12 处文档漂移全部转为 `tools/check_docs_consistency.py` 的机检断言 C1–C9（含链层契约 L1–L5 文档-码表对偶）、§1.4 末链层 5 项契约由散文改为 **L1–L5 结构化登记表**（契约本体 `tools/freeze_codes.py::CHAIN_CONTRACTS`）；ClaimCard **1.4.0**（三条机器可判定规则 + 十一角色词表）、ClaimRow **1.2.0**（`claimcard_schema_version` 版本绑定）、§六 TOST 检视网格与 σ_d 可行域（明细见 §十一修订对照表）。
> **版本口径**：方案版本（总纲 vN）／各 schema 自带 version。**阶段验收基线六件套** = 交付物 **v1.7.0** + ClaimCard **1.4.0** + ClaimRow **1.2.0** + PlanItem **1.0.1**（含 ManifestEntry **1.0.0**）。
> 其余两件同属**阶段验收基线六件套**：Contracts **1.1.0** + ExclusionList **1.0.2**。
> **版本对偶绑定规则（D26，修 P0-2）**：文档族任一侧修订必须同轮双向更新三处——①交付物抬头"依据总纲 vN"；②总纲 §12/§17 的交付物版本；③两侧基线清单。`tools/check_cross_refs.py` 机械校验，任一不一致即冻结失败。
> **权威源声明（D26/D27，结构建议 #1）**：schema 的权威源是 `schemas/*.json` 真实文件（$ref 全部可解析、可被 jsonschema 直接加载，**清单由目录派生**而非手写计数）；本文档内嵌块为**视图**，由 `tools/gen_docs_views.py --check` 保证 == 权威源确定性投影（§1.2/§1.6/§1.7 三块，手改即红，§五 5.2）；v1.5.x–v1.6.0 残留（$ref 占位、错误码双属、版本漂移、手写件数/实例数/步数/角色数类计数）100% 属机器可判定类，冻结判据从人工通读改为 **CI 全绿**（`validate_freeze.py` / `check_cross_refs.py` / `gen_docs_views.py --check` / `check_docs_consistency.py`）。

---

## 〇、术语收口（D26，修 P2「账本」双语用）

全文禁用含混词"账本"。四个存储各有唯一名称，任何校验步/错误码/反例只允许引用下表名称：

| 规范名 | 旧称（已消灭） | 内容 | 写权 | 时序键 |
|---|---|---|---|---|
| **事件链** AuditRail | 账本（指执行事件时）、链 | 执行/压缩/HITL/交接事件，线性 hash 链 + checkpoint | 仅封装层与 rail 服务身份 | `event_seq` |
| **声明链** CLAIMS.jsonl | 账本（指声明时）、账本增量 | ClaimRow，append-only | **仅 ledger-mcp** | `row_seq` |
| **原始日志库** rawlog | 第二存储、副本 | 沙箱执行原始记录 | 仅封装层 | `event_id` 幂等 |
| **产物副本库** artifacts | 副本库 | CAS 产物内容寻址副本 | 仅封装层 | `sha256` |
| **操作日志** lm_oplog | 独立留存日志 | LM 的 append/transition 记录（WAL 先行） | 仅 LM | `op_seq` |
| **拒绝日志** reject_log | `rejected_append`（v1.5.1 矛盾源） | 八步链任一步失败的被拒草稿投影 + 错误码 | 仅 LM | `reject_seq` |

**拒绝落点定案（修 P0-4）**：声明链 append 只发生在**第八步通过之后**，校验失败不产生任何声明链行；被拒草稿的**语义投影**（不含时间戳）以 `reject_logged` 记入 reject_log。矩阵"账本状态"列改名为"**声明链状态**"，取值仅 `无新增`（步 1–7 拒）或 `新增 1 行`（步 8 过 / Auditor 主动 transition）。**逐卡交付判定**分母 = 声明链当前态 active 卡；**EQI 声明卡覆盖率**分母同时报 reject_log 被拒草稿数（阶段 2–3 为抽检口径，§四）。

---

## 一、Schema 族

### 1.1 设计原则
- **证据范围**：结构约束证明"无执行记录、或无产物定位的数值不能入账"，不证明计算正确性——由预注册三方绑定（§1.6）+ Auditor 重放 + 评审共保；
- **两级比较分工**：产物级 `compare_type`（byte/numeric_rel/image_pixel，写入时声明）用于 Auditor 重放判等；值级 `values[].comparison`（exact/float_rel）用于步 5 定位值校验，互不混用；重放阈值预注册（数值相对差 ≤1e-10；图像曼哈顿 ≤0.1% 像素数）；
- **引用侧对称原则（D26）**：文献引用与数值证据受同一形态的入账约束——`citation_refs`/`framing_ref` 必须属当前轮 MANIFEST 文献条目、locator 可解析、骨干档位与 verification 相容（步 6）；v1.5.1 只在数值侧设防，claim 级转述引用可凭空入账；
- **确定性派生原则（D26）**：所有 id 与行 hash 只从**语义投影**派生，时间戳/链绑定字段一律排除——崩溃重试必得同一 `row_id`（幂等前提），同轮重放必得同一行 hash（阶段 5 重放一致率前提）；
- **机械可执行原则**：凡 draft-07 无法表达者（实例间相等、跨数组包含、集合关系）必须登记 §1.9 跨字段规则表并绑定错误码与校验步。

### 1.2 ClaimCard 1.4.0（权威源 `schemas/claimcard-1.4.0.json`；下为视图，由 `tools/gen_docs_views.py --check` 守护）
**1.3.0 → 1.4.0 变更（D27，修 P0-3「可表达却未落地」）**：①三条机器可判定规则进 schema——**首行（无 transition）仅 active**、**by_role↔credential_kind 配对**、**to=superseded 必带 on_behalf_of_role**（门禁实例 I14–I18，详见 §1.5/R-12–R-14）；②新增 `definitions.Role` **十一角色**唯一词表，`created_by_role`/`on_behalf_of_role` 由内联 enum 改为 `$ref` 至该定义（与 `contracts-1.1.0.json` 的 from_role/to_role 同一集合，check_cross_refs ⑤ 机检）；③`transition.allOf` 增三条 by_role→credential_kind 单向收紧（hitl→hitl、gate_rail/auditor→rail、compression_protocol→compression）。
**沿用的 1.3.0 变更**：①`derived_from` 补 pattern、新增 `is_revival`/`revival_reason`（修 P1-10）；②`by_role` 删除 `owner`（无签发组件）→ 新增 `on_behalf_of_role`（gate_rail 代签并记真实发起角色）；③`citation_refs[]`/`framing_ref` 增 `manifest_entry_id` 必填（引用侧支点）；④"含 transition 则 status 必为终态"卡级 if/then；⑤`survey_transfer` 增 `survey_doi` 必填（R-11）；⑥`pointer` pattern `^(csv:|/)`；⑦`csv_cast` 消除 `'3.5'` vs `3.5` 歧义；⑧exact 禁带 tolerance；⑨contains 子句补 `required:["verification"]`（v1.5.1 缺 required 时空对象可骗过 contains，属实质缺陷）。

```json
{
  "title": "ClaimCard",
  "version": "1.4.0",
  "type": "object",
  "required": [
    "claim_id",
    "claim_type",
    "claim_text",
    "status",
    "confidence",
    "lineage"
  ],
  "additionalProperties": false,
  "properties": {
    "claim_id": {
      "type": "string",
      "pattern": "^clm_[a-f0-9]{16}$"
    },
    "claim_type": {
      "enum": [
        "result",
        "method",
        "context",
        "framing"
      ]
    },
    "claim_text": {
      "type": "string",
      "minLength": 8
    },
    "status": {
      "enum": [
        "active",
        "rejected",
        "superseded",
        "compression_orphan"
      ]
    },
    "confidence": {
      "enum": [
        "confirmatory",
        "exploratory"
      ]
    },
    "evidence": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "sandbox_execution_id",
        "script_hash",
        "output_hashes"
      ],
      "properties": {
        "sandbox_execution_id": {
          "type": "string",
          "pattern": "^exec_[a-f0-9]{16}$"
        },
        "script_hash": {
          "type": "string",
          "pattern": "^sha256:[a-f0-9]{64}$"
        },
        "plan_ref": {
          "type": "string",
          "pattern": "^pln_[a-f0-9]{12}$"
        },
        "data_refs": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": [
              "data_hash",
              "manifest_entry_id"
            ],
            "properties": {
              "data_hash": {
                "type": "string",
                "pattern": "^sha256:[a-f0-9]{64}$"
              },
              "manifest_entry_id": {
                "type": "string",
                "pattern": "^mfe_[a-f0-9]{12}$"
              }
            }
          }
        },
        "output_hashes": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "string",
            "pattern": "^sha256:[a-f0-9]{64}$"
          }
        },
        "figure_hashes": {
          "type": "array",
          "items": {
            "type": "string",
            "pattern": "^sha256:[a-f0-9]{64}$"
          }
        },
        "values": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": [
              "output_index",
              "pointer",
              "value",
              "comparison"
            ],
            "properties": {
              "output_index": {
                "type": "integer",
                "minimum": 0
              },
              "pointer": {
                "type": "string",
                "pattern": "^(csv:|/)"
              },
              "value": {
                "type": [
                  "number",
                  "string"
                ]
              },
              "unit": {
                "type": "string"
              },
              "comparison": {
                "enum": [
                  "exact",
                  "float_rel"
                ]
              },
              "tolerance": {
                "type": "number",
                "exclusiveMinimum": 1e-15,
                "maximum": 1e-06
              },
              "csv_cast": {
                "enum": [
                  "as_string",
                  "as_number"
                ],
                "default": "as_number"
              }
            },
            "allOf": [
              {
                "if": {
                  "properties": {
                    "comparison": {
                      "const": "float_rel"
                    }
                  },
                  "required": [
                    "comparison"
                  ]
                },
                "then": {
                  "required": [
                    "tolerance"
                  ]
                }
              },
              {
                "if": {
                  "properties": {
                    "comparison": {
                      "const": "exact"
                    }
                  },
                  "required": [
                    "comparison"
                  ]
                },
                "then": {
                  "not": {
                    "required": [
                      "tolerance"
                    ]
                  }
                }
              }
            ]
          }
        }
      }
    },
    "framing_ref": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "survey_doi",
        "manifest_entry_id",
        "locator"
      ],
      "properties": {
        "survey_doi": {
          "type": "string",
          "pattern": "^10\\."
        },
        "manifest_entry_id": {
          "type": "string",
          "pattern": "^mfe_[a-f0-9]{12}$"
        },
        "locator": {
          "type": "string",
          "minLength": 1
        }
      }
    },
    "citation_refs": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "doi",
          "manifest_entry_id",
          "verification",
          "locator"
        ],
        "properties": {
          "doi": {
            "type": "string",
            "pattern": "^10\\."
          },
          "manifest_entry_id": {
            "type": "string",
            "pattern": "^mfe_[a-f0-9]{12}$"
          },
          "locator": {
            "type": "string",
            "minLength": 1
          },
          "verification": {
            "enum": [
              "primary",
              "survey_transfer"
            ]
          },
          "survey_doi": {
            "type": "string",
            "pattern": "^10\\."
          },
          "snapshot_ref": {
            "type": "string",
            "pattern": "^sha256:[a-f0-9]{64}$"
          }
        }
      }
    },
    "lineage": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "created_by_role",
        "created_at",
        "run_id"
      ],
      "properties": {
        "created_by_role": {
          "$ref": "#/definitions/Role"
        },
        "credential_kind": {
          "enum": [
            "rail",
            "hitl"
          ]
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "run_id": {
          "type": "string",
          "pattern": "^run_[a-z0-9_-]{6,64}$"
        },
        "derived_from": {
          "type": "array",
          "items": {
            "type": "string",
            "pattern": "^clm_[a-f0-9]{16}$"
          }
        },
        "is_revival": {
          "type": "boolean",
          "default": false
        },
        "revival_reason": {
          "type": "string",
          "minLength": 8
        },
        "deviation_note": {
          "type": "string"
        },
        "transition": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "from",
            "to",
            "by_role",
            "reason",
            "audit_event_id"
          ],
          "properties": {
            "from": {
              "const": "active"
            },
            "to": {
              "enum": [
                "rejected",
                "superseded",
                "compression_orphan"
              ]
            },
            "by_role": {
              "enum": [
                "auditor",
                "gate_rail",
                "hitl",
                "compression_protocol"
              ]
            },
            "on_behalf_of_role": {
              "$ref": "#/definitions/Role"
            },
            "reason": {
              "type": "string",
              "minLength": 4
            },
            "credential_kind": {
              "enum": [
                "rail",
                "hitl",
                "compression"
              ]
            },
            "audit_event_id": {
              "type": "string",
              "pattern": "^evt_[a-f0-9]{16}$"
            }
          },
          "allOf": [
            {
              "if": {
                "properties": {
                  "to": {
                    "const": "rejected"
                  }
                }
              },
              "then": {
                "properties": {
                  "by_role": {
                    "enum": [
                      "auditor",
                      "gate_rail",
                      "hitl"
                    ]
                  },
                  "credential_kind": {
                    "enum": [
                      "rail",
                      "hitl"
                    ]
                  }
                }
              }
            },
            {
              "if": {
                "properties": {
                  "to": {
                    "const": "superseded"
                  }
                }
              },
              "then": {
                "properties": {
                  "by_role": {
                    "enum": [
                      "gate_rail",
                      "auditor"
                    ]
                  },
                  "credential_kind": {
                    "const": "rail"
                  }
                },
                "required": [
                  "on_behalf_of_role"
                ]
              }
            },
            {
              "if": {
                "properties": {
                  "to": {
                    "const": "compression_orphan"
                  }
                }
              },
              "then": {
                "properties": {
                  "by_role": {
                    "const": "compression_protocol"
                  },
                  "credential_kind": {
                    "const": "compression"
                  }
                }
              }
            },
            {
              "if": {
                "properties": {
                  "by_role": {
                    "const": "hitl"
                  }
                },
                "required": [
                  "by_role"
                ]
              },
              "then": {
                "properties": {
                  "credential_kind": {
                    "const": "hitl"
                  }
                }
              }
            },
            {
              "if": {
                "properties": {
                  "by_role": {
                    "enum": [
                      "gate_rail",
                      "auditor"
                    ]
                  }
                },
                "required": [
                  "by_role"
                ]
              },
              "then": {
                "properties": {
                  "credential_kind": {
                    "const": "rail"
                  }
                }
              }
            },
            {
              "if": {
                "properties": {
                  "by_role": {
                    "const": "compression_protocol"
                  }
                },
                "required": [
                  "by_role"
                ]
              },
              "then": {
                "properties": {
                  "credential_kind": {
                    "const": "compression"
                  }
                }
              }
            }
          ]
        }
      }
    }
  },
  "allOf": [
    {
      "if": {
        "properties": {
          "lineage": {
            "required": [
              "transition"
            ]
          }
        }
      },
      "then": {
        "properties": {
          "status": {
            "enum": [
              "rejected",
              "superseded",
              "compression_orphan"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "lineage": {
            "required": [
              "is_revival"
            ]
          }
        }
      },
      "then": {
        "properties": {
          "lineage": {
            "allOf": [
              {
                "if": {
                  "properties": {
                    "is_revival": {
                      "const": true
                    }
                  }
                },
                "then": {
                  "required": [
                    "revival_reason",
                    "derived_from",
                    "credential_kind"
                  ],
                  "properties": {
                    "credential_kind": {
                      "const": "hitl"
                    }
                  }
                }
              }
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "claim_type": {
            "const": "result"
          }
        }
      },
      "then": {
        "required": [
          "evidence"
        ],
        "properties": {
          "evidence": {
            "required": [
              "sandbox_execution_id",
              "script_hash",
              "plan_ref",
              "output_hashes",
              "data_refs",
              "values"
            ],
            "properties": {
              "data_refs": {
                "minItems": 1
              },
              "values": {
                "minItems": 1
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "claim_type": {
            "const": "method"
          }
        }
      },
      "then": {
        "required": [
          "evidence"
        ],
        "properties": {
          "evidence": {
            "required": [
              "sandbox_execution_id",
              "script_hash",
              "plan_ref"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "claim_type": {
            "const": "context"
          }
        }
      },
      "then": {
        "required": [
          "citation_refs"
        ],
        "properties": {
          "citation_refs": {
            "minItems": 1,
            "contains": {
              "properties": {
                "verification": {
                  "const": "primary"
                }
              },
              "required": [
                "verification"
              ]
            }
          }
        },
        "not": {
          "required": [
            "evidence"
          ]
        }
      }
    },
    {
      "if": {
        "properties": {
          "claim_type": {
            "const": "framing"
          }
        }
      },
      "then": {
        "required": [
          "framing_ref"
        ],
        "not": {
          "required": [
            "evidence"
          ]
        }
      }
    },
    {
      "if": {
        "required": [
          "lineage"
        ],
        "properties": {
          "lineage": {
            "not": {
              "required": [
                "transition"
              ]
            }
          }
        }
      },
      "then": {
        "properties": {
          "status": {
            "const": "active"
          }
        }
      }
    }
  ],
  "definitions": {
    "Role": {
      "type": "string",
      "enum": [
        "coordinator",
        "intake-curator",
        "librarian",
        "analyst",
        "writing",
        "reviewer-1",
        "reviewer-2",
        "reviewer-3",
        "ac",
        "auditor",
        "profile-curator"
      ]
    }
  }
}
```
转换表与 schema 同构（1.4.0 起三条规则由 schema 直接判定）：from=active；**首行（无 transition）只能 active**；rejected←{auditor, gate_rail, hitl}；superseded←{gate_rail, auditor}（凭证必为 rail，且须 on_behalf_of_role）；compression_orphan←{compression_protocol}；终态不可再变；复活=新卡（is_revival=true 须 hitl 凭证 + revival_reason + derived_from）。

### 1.3 服务端校验链（ledger-mcp；校验对象 = ClaimRow；**八步**，D26）
| 步 | 校验 | 失败错误码 |
|---|---|---|
| 1 | ClaimRow schema（行字段+内嵌 card；FormatChecker；tolerance 条件；pointer pattern；**卡级规则三条 1.4.0 起由 schema allOf 直接判定**：无 transition 仅 active、by_role↔credential_kind 配对、to=superseded 须 on_behalf_of_role，R-12–R-14） | `SCHEMA_FAIL` |
| 2 | execution_id 存在、completed、审计状态可用、**事件链验算通过**（checkpoint 每 1000 行，从最近 checkpoint 验至目标事件，修 P1 O(N²)；含 R-01） | `EXEC_UNRESOLVED` / `EXEC_REJECTED` / `EXEC_CHAIN_FAIL` |
| 3 | `run_context_ref` 解析到当前轮 RunContext 且 `row.manifest_version == RunContext.manifest_version`（**LM 只读挂载 intake 冻结的 MANIFEST 注册表**，修 P1 来源未定义）；`data_refs[].manifest_entry_id` 属该 MANIFEST **数据**条目且条目 hash == data_hash | `MANIFEST_CONTEXT_MISMATCH` / `TRANSPORTIVITY_FAIL` |
| 4 | hash 一致（脚本/产物 vs 事件链；产物副本库存在且 hash 同）；plan_ref 解析到 PlanItem 且 expected_script_hash==script_hash（不符须 exploratory+note）；行级状态机（§1.5、§1.9）；figure_hashes ⊆ output_hashes | `HASH_MISMATCH` / `ARTIFACT_UNREACHABLE` / `PLAN_UNBOUND` / `PLAN_MISMATCH` / `TRANSITION_INVALID` / `FIGURE_HASH_UNBOUND` |
| 5 | 产物副本库读产物按 pointer 定位（R-06/R-07；output_index 界内 R-04）：exact 按 csv_cast 转换后全等；float_rel=\|a−b\|≤tolerance·max(1,\|b\|)；非有限/类型不匹配即败 | `VALUE_LOCATOR_FAIL` / `OUTPUT_INDEX_OUT_OF_RANGE` |
| 6 | **引用一致性（D26 新增，与数值侧对称）**：citation_refs/framing_ref 的 manifest_entry_id 属该 MANIFEST **文献**条目、doi==条目 doi、locator 可解析；survey_transfer 必带 survey_doi 且属骨干条目；framing 指向条目 role==backbone（T3 禁承载 framing）；primary 须有 snapshot_ref | `DOI_NOT_IN_MANIFEST` / `CITATION_LOCATOR_FAIL` / `BACKBONE_GRADE_VIOLATION` / `SNAPSHOT_MISSING` |
| 7 | exploratory 必带 deviation_note | `DEVIATION_UNNOTED` |
| 8 | 通过 → append 声明链；幂等键=row_id（内容派生，§1.8） | `ROW_CONFLICT` |

步 1–7 任一失败 → 不产生声明链行，仅写 reject_log（§〇）。

### 1.4 分支实例（I01–I20 二十例 + ClaimRow 三例；标注校验层级与拦截步；fixtures 见 `tools/validate_freeze.py`）
门禁 G2 的实例表逐例声明「预期通过/拒绝」，参数化执行；步 1 判据由 schema 层直接判定，步 2–8 为链层（M3 后由 ledger-mcp 验收）。

| 实例 | 场景 | 层级·拦截步 | 预期 |
|---|---|---|---|
| I01 | result 正例：evidence 全，float_rel 带 tolerance=1e-9 | schema+链 | 过 |
| I02 | result 拒：缺 values | 步 1 | `SCHEMA_FAIL` |
| I03 | result 拒：exact 带 tolerance | 步 1 | `SCHEMA_FAIL` |
| I04 | method 正例 | schema+链 | 过 |
| I05 | method 拒A：plan_ref 缺失（D26 与 PLAN_UNBOUND 拆分，错误码不再双属） | 步 1 | `SCHEMA_FAIL` |
| I06 | context 正例 | schema | 过 |
| I07 | context 拒A：全 survey_transfer | 步 1（contains + required） | `SCHEMA_FAIL` |
| I08 | framing 正例 | schema | 过 |
| I09 | framing 拒A：含 evidence | 步 1 | `SCHEMA_FAIL` |
| I10 | transition 正例：superseded + gate_rail + on_behalf_of_role=analyst | schema+链 | 过 |
| I11 | transition 拒：by_role=owner（1.3.0 已废除） | 步 1 | `SCHEMA_FAIL` |
| I12 | revival 拒：缺 hitl 凭证 / 缺 revival_reason | 步 1 | `SCHEMA_FAIL` |
| I13 | revival 正例：hitl 凭证 + 理由 + 谱系 | schema+链 | 过 |
| I14 | 1.4.0 拒：首行（无 transition）为 superseded → 首行只允许 active（R-12） | 步 1 | `SCHEMA_FAIL` |
| I15 | 1.4.0 拒：首行为 compression_orphan | 步 1 | `SCHEMA_FAIL` |
| I16 | 1.4.0 拒：by_role=hitl 却用 rail 凭证（凭证映射表落 schema，R-13） | 步 1 | `SCHEMA_FAIL` |
| I17 | 1.4.0 拒：by_role=gate_rail 却用 hitl 凭证 | 步 1 | `SCHEMA_FAIL` |
| I18 | 1.4.0 拒：to=superseded 缺 on_behalf_of_role（R-14） | 步 1 | `SCHEMA_FAIL` |
| I19 | 1.4.0 拒：未登记角色 reviewer（十一角色词表未收录） | 步 1 | `SCHEMA_FAIL` |
| I20 | 1.4.0 正例：登记角色 reviewer-1 | schema+链 | 过 |

**ClaimRow 包装三例（G2，修 P1 漂移 #12）**：正例（内嵌 card 经 `$ref` 生效）；拒·未知字段（行级 `additionalProperties:false`）；拒·`claimcard_schema_version`=1.3.0 与内嵌 card 1.4.0 不符（1.2.0 起该字段为 `const`，防混版本声明链）。

**链层用例契约五项（L1–L5 结构化登记；schema 层不可判定或不可完整判定——L4 已可判定，仅需回归确认，其余需链层运行时，ledger-mcp 实现后由 M3 逐条验收）**：登记表是**契约本体**（单一事实源 `tools/freeze_codes.py::CHAIN_CONTRACTS`），门禁 G3e–G3g 校验其登记完整性（id 连续、码属八步链、三通道 + 两条凭证规则全覆盖），`tools/check_docs_consistency.py` C9 校验「本表 ↔ 码表」双向一致；**登记不计入 PASS 断言数**，执行结果待 M3 回填。

| 契约 | 场景（schema 判不了的部分） | 拦截步 | 错误码 | M3 验收点 |
|---|---|---|---|---|
| L1 | method 通道：`plan_ref` 不可解析（schema 只判非空） | 步 4 | `PLAN_UNBOUND` | 计划注册表查无该 `plan_ref` → 拒绝合并并落码 |
| L2 | context 通道：`citation_refs` 条目不属当前轮 MANIFEST（schema 只判必填） | 步 6 | `DOI_NOT_IN_MANIFEST` | 本轮 MANIFEST 无该条目 → 拒绝并落码 |
| L3 | framing 通道：`framing_ref` 档位非 backbone（schema 只判必填） | 步 6 | `BACKBONE_GRADE_VIOLATION` | 档位矩阵校验 `curation_grade` → 拒绝并落码 |
| L4 | 凭证规则：`to=superseded` 缺 `on_behalf_of_role`（1.4.0 起 schema 已可判定） | 步 1 | `SCHEMA_FAIL` | 回归确认链层不复判、不产生第二来源 |
| L5 | 凭证规则：首行 `created_by_role` ≠ 凭证 `on_behalf_of_role`（R-08，需比对凭证，schema 不可判定） | 步 4 | `TRANSITION_INVALID` | rail 凭证代签角色与行谱系不符 → 落码 |

### 1.5 状态机、凭证映射与复活规则
- **时序键（修 P1-7）**：当前态 = 同 claim_id 的 `row_seq` 最大行（链上整数，不用 appended_at）；writing/终检读当前态 active-only；Auditor 读全历史；
- **凭证映射表（修 P1-9）**：transition 统一走 LM transition 通道，`by_role` 为**签发组件身份**，真实发起方记 `on_behalf_of_role`：

| 签发组件 | credential_kind | 允许 by_role | 允许 to |
|---|---|---|---|
| ClaimCardRail（=枚举 gate_rail，命名映射固定于此） | rail | gate_rail / auditor | rejected / superseded |
| HITL interrupt rail | hitl | hitl | rejected（及 is_revival 首行签发） |
| 上下文压缩管理器 | compression | compression_protocol | compression_orphan（唯一） |
| Auditor 服务身份 | rail | auditor | rejected / superseded |

by_role↔凭证不符 → `TRANSITION_INVALID`。**owner 值废除**（v1.5.1 无签发组件，superseded 不可产生）——owner 语义由 by_role=gate_rail + on_behalf_of_role=<发起角色> 表达。
- **1.4.0 三条卡级规则前移进 schema（R-12–R-14，原文仅在文字与链层，修 P0-3）**：①**R-12 首行只能 active**——lineage 无 transition 时 `status` 为 `const "active"`，终态必须经 transition 事件派生（实例 I14/I15）；②**R-13 by_role↔credential_kind 单向配对**——hitl→hitl、gate_rail/auditor→rail、compression_protocol→compression，反向不等价（实例 I16/I17）；③**R-14 to=superseded 必带 on_behalf_of_role**——superseded 的 `allOf` 分支 `required:["on_behalf_of_role"]` + `credential_kind` `const "rail"`（实例 I18）。
- **角色词表（十一角色，1.4.0 唯一事实源）**：coordinator、intake-curator、librarian、analyst、writing、reviewer-1、reviewer-2、reviewer-3、ac、auditor、profile-curator。`created_by_role`/`on_behalf_of_role` 均由内联 enum 改为 `$ref` 本定义，`contracts-1.1.0.json` 的 from_role/to_role 为同一集合（check_cross_refs ⑤ 机检）；未登记角色（如旧写法 reviewer）→ 步 1 `SCHEMA_FAIL`（实例 I19/I20）。
- **首行凭证（R-08）**：首行 lineage.credential_kind 必填，created_by_role 必须等于凭证的 on_behalf_of_role，否则 `TRANSITION_INVALID`（v1.5.1 首行可谎报创建者）；
- **复活 vs 排除清单（修 P1-10）**：**禁**——被排除 claim_id 出现在 ①C2/C4 claim_ids ②正文数字支撑引用 ③自演进技能注入 → 写作组装层 `EXCLUDED_CLAIM_REFERENCE`（新增反例 **T5f**，阶段 1 硬验收）；**允许**——derived_from 作谱系标注；is_revival=true 时三条同时成立：(i) 新卡完整重跑八步链（禁继承 tainted execution_id）；(ii) revival_reason 必填；(iii) hitl 凭证签发。口径一句话：**排除清单管"作为证据"，不管"作为谱系"**；
- active-only 前移落在写作组装层（读取口径+排除禁项），对应 T5f，不等 Auditor 终检。

### 1.6 PlanItem 1.0.1 与 ManifestEntry 1.0.0（权威源 `schemas/planitem-1.0.1.json`、`schemas/manifestentry-1.0.0.json`）
v1.5.1 只在文字里说"属当前轮 MANIFEST 条目"但从未定义条目 schema——步 3/6 无可解析对象。现补 ManifestEntry：

```json
{
  "title": "ManifestEntry",
  "version": "1.0.0",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "manifest_entry_id",
    "kind",
    "curation_grade"
  ],
  "properties": {
    "manifest_entry_id": {
      "type": "string",
      "pattern": "^mfe_[a-f0-9]{12}$"
    },
    "kind": {
      "enum": [
        "data",
        "literature"
      ]
    },
    "curation_grade": {
      "enum": [
        "user_provided",
        "T1",
        "T2",
        "T3"
      ]
    },
    "sha256": {
      "type": "string",
      "pattern": "^sha256:[a-f0-9]{64}$"
    },
    "doi": {
      "type": "string",
      "pattern": "^10\\."
    },
    "role": {
      "enum": [
        "backbone",
        "primary",
        "supporting"
      ]
    },
    "snapshot_ref": {
      "type": "string",
      "pattern": "^sha256:[a-f0-9]{64}$"
    },
    "semantics_handle": {
      "type": "string"
    },
    "provenance": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "query_path_ref": {
          "type": "string"
        },
        "retriever_version": {
          "type": "string"
        },
        "exclusion_reason": {
          "type": "string"
        }
      }
    }
  }
}
```
条件必填登 R-09/R-10（kind=data→sha256 必填；kind=literature→doi 必填；T2→provenance 三字段必填，兑现 D6 可归因）。PlanItem 1.0.1 同 v1.5.1（description 注明 expected_script_hash 即重放比对对象）。**本节 JSON 为视图**：由 `tools/gen_docs_views.py --check` 保证 == `schemas/manifestentry-1.0.0.json` 的确定性投影（删 `$schema` 与全部 description），手改即红。

**档位相容矩阵（步 6 判定；fixtures 含机器可读版）**：

| 条目档位 | 可作 primary | 可作 survey_transfer 转述源 | 可被 framing_ref 指向 |
|---|---|---|---|
| user_provided / T1 backbone | 是（若一手） | 是 | 是 |
| T2 AI 自建（快照齐备） | 是（须 snapshot_ref） | 是 | 是 |
| T3 纯检索 | 是（仅引用级） | **否** | **否** → `BACKBONE_GRADE_VIOLATION` |

### 1.7 ClaimRow 1.2.0（权威源 `schemas/claimrow-1.2.0.json`，ClaimCard 全文内嵌于 definitions，$ref 全可解析）
```json
{
  "title": "ClaimRow",
  "version": "1.2.0",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "row_id",
    "row_seq",
    "claimcard_schema_version",
    "card",
    "appended_at",
    "audit_event_id",
    "manifest_version",
    "venue_profile_version"
  ],
  "properties": {
    "row_id": {
      "type": "string",
      "pattern": "^row_[abcdef0123456789]{16}$"
    },
    "row_seq": {
      "type": "integer",
      "minimum": 0
    },
    "claimcard_schema_version": {
      "const": "1.4.0"
    },
    "card": {
      "$ref": "#/definitions/ClaimCard"
    },
    "appended_at": {
      "type": "string",
      "format": "date-time"
    },
    "audit_event_id": {
      "type": "string",
      "pattern": "^evt_[abcdef0123456789]{16}$"
    },
    "manifest_version": {
      "type": "string"
    },
    "venue_profile_version": {
      "type": "string"
    }
  },
  "definitions": {
    "ClaimCard": "…ClaimCard 1.4.0 全文见 §1.2（权威源 schemas/claimcard-1.4.0.json）…",
    "Role": {
      "type": "string",
      "enum": [
        "coordinator",
        "intake-curator",
        "librarian",
        "analyst",
        "writing",
        "reviewer-1",
        "reviewer-2",
        "reviewer-3",
        "ac",
        "auditor",
        "profile-curator"
      ]
    }
  }
}
```

**1.1.0 → 1.2.0 变更（D27，修 P1 漂移 #12）**：`claimcard_schema_version` 由自由串（`pattern: ^\d+\.\d+\.\d+$`）收紧为 `const "1.4.0"`——1.2.0 起内嵌 card 即权威，行头版本必须与内嵌版本一致，防「混版本声明链」；门禁 G2 有对应反例（版本写 1.3.0 即拒）。本节 JSON 为视图，由 `tools/gen_docs_views.py --check` 守护。

### 1.8 id 派生与重放基准（D26，修 P1-6）
- **稳定投影**：ClaimRow 剔除易变字段（`appended_at`、`audit_event_id`、`row_seq`）后的对象；
- **row_id 派生** = `"row_" + SHA-256(JCS(稳定投影))[:16]`——崩溃重试/重复提交重派生同一 row_id，幂等去重自然生效；不同内容必不同 row_id；
- **replay_normalized_hash**（阶段 5 重放一致率基准）= SHA-256(JCS(稳定投影))——重放比对基于此，不比较含时间戳的整行；
- 行幂等比对 hash（§7.1）同此投影；序列化层遇 NaN/±Inf 直接报错（JCS 禁非有限值）。

### 1.9 跨字段规则表（D26/D27；R-01–R-11 链层实现，R-12–R-14 自 1.4.0 起由 schema 判定）
| # | 规则 | 校验步 | 错误码 |
|---|---|---|---|
| R-01 | 事件链凭证记录的 on_behalf_of 与引用该执行的卡 lineage 一致 | 2 | `EXEC_CHAIN_FAIL` |
| R-02 | transition.to == 本行 card.status | 4 | `TRANSITION_INVALID` |
| R-03 | transition.from == 该 claim_id 当前态（按 row_seq） | 4 | `TRANSITION_INVALID` |
| R-04 | values[].output_index < len(evidence.output_hashes) | 5 | `OUTPUT_INDEX_OUT_OF_RANGE` |
| R-05 | figure_hashes ⊆ output_hashes | 4 | `FIGURE_HASH_UNBOUND` |
| R-06 | pointer 文法：`csv:L<正整数>C<正整数>`（1-based）；否则 RFC 6901 | 5 | `VALUE_LOCATOR_FAIL` |
| R-07 | exact 按 csv_cast 转换（as_number: 数值串化后比对；as_string: 原串比对） | 5 | `VALUE_LOCATOR_FAIL` |
| R-08 | 首行 created_by_role == 凭证 on_behalf_of_role | 4 | `TRANSITION_INVALID` |
| R-09 | ManifestEntry：kind=data→sha256 必填；kind=literature→doi 必填 | 3/6 | `TRANSPORTIVITY_FAIL` / `DOI_NOT_IN_MANIFEST` |
| R-10 | T2 条目 provenance 三字段必填 | 6 | `BACKBONE_GRADE_VIOLATION` |
| R-11 | verification=survey_transfer → survey_doi 必填且属骨干条目 | 6 | `CITATION_LOCATOR_FAIL` |
| R-12 | 首行（lineage 无 transition）status 只能 active——终态必经 transition 事件派生 | 1（1.4.0 起 schema；I14/I15） | `SCHEMA_FAIL` |
| R-13 | transition.by_role 与 credential_kind 单向配对：hitl→hitl、gate_rail/auditor→rail、compression_protocol→compression | 1（1.4.0 起 schema；I16/I17） | `SCHEMA_FAIL` |
| R-14 | transition.to=superseded → credential_kind=rail 且 on_behalf_of_role 必填 | 1（1.4.0 起 schema；I18） | `SCHEMA_FAIL` |

---

## 二、反例与配套测试规格（一正 + 九反 + T5a–f）

**分层定义**：L1=OS/ACL 与调用鉴权；L2=hash 链验算（**事件链任意点：从最近 checkpoint 验至目标事件；声明链：append 时链尾增量 O(1)，终检全链**——两类对象分别计预算，修 P1 O(N²) 表述冲突）；L3=Auditor 双源对账（事后）。T1b3=append 时事件解析失败（步 2）；T4a=事后审计发现事件链注入篡改（L2 全链）。

### 正例（对照）
**阶段 1 前置（D26 扩，L1 平台能力门）**：确定性环境（OS 镜像 digest｜uv.lock｜OMP_NUM_THREADS=1、单线程 BLAS｜**PYTHONHASHSEED=0+显式 seed**｜LC_ALL=C｜TZ=UTC｜CPU-only｜matplotlib 锁定）+ **L1 平台能力 PoC**（服务身份隔离、事件链/rawlog/artifacts/WAL 只读 ACL 挂载、analyst 工具面裁剪——三项在 WorkSwarm 各跑一次最小验证，为 M1 第一项，修 P1-16）。产物写入规范与 compare_type 同 §1.1。

### 追溯矩阵（D26：reject_logged 落点；声明链状态列；T5f 新增；T4b 夹具化）
| 子例 | 攻击/触发 | 拦截层/步 | 错误码/判据 | 日志落点 | 声明链状态 | 环境/恢复 |
|---|---|---|---|---|---|---|
| T1a | agent 直接调用 LM | L1 鉴权 | `CALLER_DENIED` | lm_oplog | 无新增 | 生产 |
| T1b1 | execution_id 空/格式错 | 步 1 | `SCHEMA_FAIL` | reject_log | 无新增 | 生产 |
| T1b2 | 事件链查无此执行 | 步 2 | `EXEC_UNRESOLVED` | 同上 | 无新增 | 生产 |
| T1b3 | 引用链验不过的执行 | 步 2 | `EXEC_CHAIN_FAIL` | 同上 | 无新增 | 生产 |
| T2 | data_hash/条目不属当前轮或 hash 不符 | 步 3 | `TRANSPORTIVITY_FAIL` / `MANIFEST_CONTEXT_MISMATCH` | 同上 | 无新增 | 生产 |
| T3 | values 定位落空/超差/非有限/越界 | 步 5；漏网→transition 行 | `VALUE_LOCATOR_FAIL` / `OUTPUT_INDEX_OUT_OF_RANGE` | 同上/transition | 无新增或 rejected | 生产 |
| T4a | 事件链注入不重算链 | L2 全链（事后） | `TAMPER_DETECTED` | 链验算报告 | 事件隔离 | 测试副本 |
| T4b | 自洽伪造（重算链） | L3 双源对账 | `PHANTOM_EVENT` | 审计报告（三元组） | 事件标记 | 测试副本 + **最小对账夹具（一次性 harness：事件×rawlog 存在性+交叉绑定核对；产品级 Auditor 对账阶段 2+，修 P0-3）** |
| T4c | agent 直写事件链/rawlog/artifacts/WAL | L1 ACL | `EACCES` | 独立安全日志 | 无变化 | 生产 |
| T5a | (i) plan_ref **不可解析**（缺失走步 1）→ `PLAN_UNBOUND`；(ii) script≠expected 未标 exploratory → `PLAN_MISMATCH` | 步 4 | 两判据分立 | reject_log | 无新增 | 生产 |
| T5b | 引用 tainted 执行 | 步 2 | `EXEC_REJECTED` | 同上 | 无新增 | 生产 |
| T5c | 非法转换/凭证不匹配/首行谎报 | 步 4 | `TRANSITION_INVALID` | 同上 | 无新增 | 生产 |
| T5d | 同 row_id 重放（同/异内容） | 步 8 幂等（JCS 投影 hash） | 幂等成功 / `ROW_CONFLICT` | lm_oplog | 恰一行 | 生产 |
| T5e | 三写点崩溃/重启补写/重复补写/孤儿标记 | §8.6 | 无 pending 残留/事件恰一次/孤儿仅标记/WAL 可读 | WAL+审计报告 | 事件恰一次 | 测试副本 |
| **T5f** | 写作组装引用被排除 claim_id（C2/C4/正文/技能注入四路） | 写作组装层（active-only 前移） | `EXCLUDED_CLAIM_REFERENCE` | reject_log | 无新增 | 生产 |

---

## 三、交接契约（Contracts 1.1.0，权威源 `schemas/contracts-1.1.0.json`；ExclusionList 内嵌 definitions）
公共信封（八字段，封闭）同前。变更（1.0.1→1.1.0）：**C3 对齐引用侧新模型**（doi pattern、manifest_entry_id、locator 必填；verification 放开 enum，survey_transfer 须 survey_doi——framing 通道专用）；**C5.rebuttal 封闭**（`{point, response}` 字段集冻结；review_form 保持开放但注明子 schema 由 venue 档案运行时装配，属登记例外）；**C7.conclusions 封闭**（`{passed, failed, undetermined}` 三数组）；**C7.exclusion_list $ref 指向同文件 `#/definitions/ExclusionList`（全文内嵌，可执行）**。C4 白名单与 resolver 表征字段集 {claim_text, claim_type, status, confidence} 不变，**白名单断言已入门禁 G1c**（C4 payload 注入 rawlog_path/execution_id/data_file 等字段 → `SCHEMA_FAIL`，负例与 C1–C8 正例同批 fixture 计数）。

---

## 四、验收阈值可操作性审查
同 v1.5.1 表，另两条 D26 注记：**α 估计量**——"两两配对取均值"为非标准估计量，与文献阈值不可直接比，阶段 3 改用标准 Krippendorff α（含 CI）；**MVP 溯源边界（修 P1-14）**——论文数字抽取器阶段 4/5 交付前，"正文无卡数字"为抽检而非硬门，EQI 覆盖率按此口径标注并写入总纲 limitation。

## 五、冻结判据（v1.7.0）
- **5.1 门禁四层 = `tools/validate_freeze.py`，全绿即退出码 0**：当前共 **82 项断言**，分层计数 **G1 42 / G2 23 / G3 7 / G4 10**（每次运行由脚本自报，文档不得写死与实测不符的数；C4/C4b 双向校验「本文与总纲登记的数字 == 门禁实测」）：
  - **G1 语义层（42）**：六件 schema 全部通过 draft-07 meta-schema；全部 `$ref` 可解析（含 ClaimRow/Contracts 内嵌 definitions）；六件 fixture 正负例——PlanItem 4、ManifestEntry 4、ExclusionList 5（oneOf 分支）、Contracts 10（C1–C8 各一正例 + **C4 白名单注入负例** + payload 不属 C1–C8 负例）；`date-time` FormatChecker；
  - **G2 规则层（23）**：ClaimCard 1.4.0 三条卡级规则 + 十一角色词表（实例 I01–I20 二十例）+ ClaimRow 包装三例（正例 / 行级封闭 / `claimcard_schema_version` 与内嵌版本不符）；本层全部由 jsonschema 直接判定；
  - **G3 一致性层（7）**：错误码矩阵全大写且唯一、15 子例矩阵（T1a–T5f）无重复归属、八步链 20 个错误码全覆盖、链层专有码 8 项登记、**链层契约 L1–L5 登记完整性**（G3e id 连续 / G3f 码均属八步链 / G3g 三通道 + 两条凭证规则全覆盖）；
  - **G4 确定性层（10）**：JCS=RFC 8785（`tools/jcs.py` 内置 35 向量 selftest）、数字规范化（1.0→1、−0.0→0、1e-7、1e20、1e21）、UTF-16 键序、转义、非有限值拒、row_id 幂等派生。
- **退出码三分**：**0**=全绿；**1**=存在失败（逐条打印失败项）；**2**=依赖缺失（jsonschema 或 `tools/jcs.py` 不可用）。CI 据此区分「schema/文档缺陷」与「环境缺依赖」，不把后者算作红。
- **清单目录派生**：schema 清单 = `schemas/*.json` 排序结果，不硬编码手写计数（件数/实例数/步数/角色数一律与门禁实测对齐）——计数漂移从此在机器上不可发生（D27 修 P1-6 计数类）。
- **5.2 四脚本全绿（冻结判据整体）**：`validate_freeze.py`（四层判据）+ `check_cross_refs.py`（版本对偶三处一致：交付物抬头 / 总纲 §12§17 / 基线清单）+ `gen_docs_views.py --check`（§1.2/§1.6/§1.7 三视图 == 权威源确定性投影）+ `gen_composites.py --check`（内嵌定义组合可执行）；
- **5.3 链层用例契约 5 项待 M3（L1–L5）**：schema 层无法判定，门禁只校验**登记完整性**、不执行链层行为；契约本体为 `tools/freeze_codes.py::CHAIN_CONTRACTS`，本文件 §1.4 末表为其文档投影（C9 双向对偶），ledger-mcp 实现后由 M3 逐条回填验收结果——届时 `[REG ]` 转 PASS 后计入门禁断言数；
- **5.4**：P2 未尽项（α 类别敏感性、Compliance/HITL 衔接细则）随签核单归档 M2/M3。

## 六、宽松度差统计口径（TOST；与总纲 v26 §10 统一；D26/D27 量纲、n 网格与 α-spending 修订）
- d_i = 集成分 − 人工双盲均分，**两侧同量表**：尺度归一若应用须对人工分做同一变换（或直接用原始分）；δ=±0.5 明示 **10 分制绝对分**，基线取 D25；
- **样本量公式（复核成立）**：n = (z₀.₉₅ + z₀.₈₀)²·σ_d² / (δ − |μ|)² = 6.1832·σ_d² / (δ − |μ|)²。代入 D25 基线 σ_d=1.2、|μ|=0.2、δ=0.5 → n≈98.9 → **n_start = 99**（与总纲 §10/§15 同值；σ_d 仍随 D19 顺序依赖，M1 首轮须实测复核）；
- TOST：单侧 α=0.05、功效 0.80；bootstrap 按文章重采样，报 90% CI；
- **α-spending（修 P1-11）**：中期检视自 n_start 起每 +25，即 **99 / 124 / 149** 三个检视点；**只做"失败/继续"分支**（CI 全在外→提前终止判偏差）；**"证明等效"仅终末判定**——名义 α 不因中期检视膨胀；**max n = 150** 是硬上限与终末判定点，**不是检视点**；仍未定按"未证明等效"处理；
- **功效边界（v1.6.0 网格越界的更正）**：由 max n=150 反解 σ_d ≤ 1.48（δ=0.5、|μ|=0.2）；故 σ_d>1.48 时 150 样本不足以达 0.80 功效，M1 前须重定 δ 或显式宣告功效不足。v1.6.0 的网格 99/124/149/174 与 max n=150 自相矛盾（174>150），且"δ=±0.5 起始 n≈99"暗含 σ_d≈2.0、与 D25 基线 1.2 不一致——两处均按上式重算更正；
- **锚构念重建（修 P1-12）**：阶段 3 为"C4 表征评审"单独建锚（表征/全文双条件锚），不沿用与分数偏差不同构念的投稿决策一致率；锚定实验设计入阶段 3 交付。

## 七、ledger-mcp 权限边界（全文；D26：八步引用同步）
| 项 | 规定 |
|---|---|
| 运行身份 | 独立服务进程（沙箱外），专用服务账户 LM |
| 谁可调用 | 仅 ClaimCardRail 与 transition 通道（凭证类型匹配 §1.5）；agent 直接调用 → `CALLER_DENIED` 入 lm_oplog |
| agent 工具面 | 只暴露 `ledger.query`（只读） |
| 对事件链 | 只读（ACL）；execution_id 解算含 checkpoint 验算 |
| 对声明链 | 唯一 append 权；写入前执行**八步**校验链 |
| 对 rawlog/artifacts | 只读（步 4/5 读副本）；WAL 仅 Auditor 读 |
| 自身可审计性 | append/拒绝/transition 写 lm_oplog；Auditor 定期抽查与声明链增量一致性 |
| 凭据管理 | 与 agent 凭据物理分离、定期轮换 |
| 失效模式 | LM 宕机 → 声明链写路径关闭（fail-closed ≠ fail-loss）；恢复按 §7.1 |

### 7.1 补 append 幂等（幂等键 = row_id，比对 hash = §1.8 稳定投影 JCS hash）
触发=重启扫描 lm_oplog 检出"步 1–7 过、步 8 未落账"pending；同 row_id 同投影 hash → 幂等成功；异 → `ROW_CONFLICT` 升级 HITL；补写前重跑八步链；lm_oplog WAL 先行。

## 八、双源对账源定义（全文；术语按 §〇 收口）
**8.1 两库**：rawlog（exec_id/event_id、命令、stdout 摘要、产物清单含 hash+compare_type+人读标签、环境指纹；仅封装层写；**event_id 幂等**）/ artifacts（CAS；compare_type 标注；仅封装层写）。
**8.2 三写与四源**：三写 = rawlog → artifacts → 事件链（同批，WAL 先行，事件含前两者引用）；四源对账 = 事件链 × rawlog × artifacts × WAL；交叉绑定 log_ref/event_id，核对 exec_id/output_hashes/env_digest。
**8.3 引用三元组**：(库, entry_id, 库状态 hash)；空结果带库 head hash。
**8.4 防污染**：agent 全只读（T4c）；封装层被攻破=对账退化自证（显式 limitation；缓解凭据轮换/WORM）。
**8.5 验算与交付**：声明链 append 增量验算 O(1)、Auditor 终检全链（失败=交付失败）；事件链任意点 checkpoint 验算；交付逐声明卡（当前态 active 才支撑数字）。
**8.6 三写失败恢复与 T5e**：WAL（JSONL+checksum+fsync，尾截断跳过、中部损坏告警）位于 evidence/wal/；pending 不发 execution_id；event_id/CAS 幂等补写；孤儿仅标记（CAS 引用计数），清理须 HITL；判据同矩阵。

## 九、ExclusionList 1.0.2（权威源 `schemas/exclusionlist-1.0.2.json`）
1.0.1 + 新增可选 `revival_permits`（HITL 批准的复活谱系，clm_ 数组——与 §1.5 is_revival/hitl 凭证对应，消费规则：coordinator 冻结入 intake；步 2/3/写作层（含 T5f 禁项，revival_permits 内 id 的 derived_from 合法）/自演进四路消费）。

## 十、工程产物与门禁（D26/D27 新增，结构建议 #1 落地）
| 产物 | 说明 |
|---|---|
| `schemas/claimcard-1.4.0.json` | ClaimCard 权威 schema（十一角色词表 + 三条卡级规则 allOf） |
| `schemas/claimrow-1.2.0.json` | ClaimRow，**ClaimCard 全文内嵌 definitions**，单文件可执行；`claimcard_schema_version` 为 `const` |
| `schemas/planitem-1.0.1.json` / `schemas/manifestentry-1.0.0.json` | 计划条目 / MANIFEST 条目 |
| `schemas/contracts-1.1.0.json` | 信封+C1–C8 payload，**ExclusionList 内嵌 definitions** |
| `schemas/exclusionlist-1.0.2.json` | 排除清单 |
| `tools/validate_freeze.py` | 四层门禁 G1–G4：meta-schema／$ref 全解析／C4 白名单断言／三条 1.4.0 规则与十一角色词表／错误码矩阵与链层契约登记／JCS 确定性；当前 **82 项断言**，退出码 0/1/2 |
| `tools/check_cross_refs.py` | 版本对偶三处一致 + 内嵌 version/const/Role 与 11 项集合对偶校验 |
| `tools/gen_docs_views.py` | §1.2/§1.6/§1.7 三视图自权威源确定性投影；`--check` 手改即红，`--write` 重生成 |
| `tools/gen_composites.py` | 内嵌定义组合可执行性；`--check` 校验两件 composite |
| `tools/check_docs_consistency.py` | 文档机检 C1–C9：版本锚／禁止口径／必需口径／断言计数==门禁实测（含总纲 C4b）／反引号大写码白名单／§1.3 码覆盖／视图一致／章节结构／链层契约 L1–L5 文档-码表对偶 |
| `tools/freeze_codes.py` / `tools/jcs.py` | 错误码单一事实源 / RFC 8785 JCS 实现（含 selftest 向量） |

**脚本工程化约定（D27，四条硬约束）**：①**入口**——统一 `bash run_gates.sh`（导出 `PYTHONIOENCODING=utf-8`/`PYTHONUTF8=1`/`PYTHONDONTWRITEBYTECODE=1`，逐项打印 `[GATE n]` 与 rc，汇总后退出）；②**退出码三分**——0=全绿 / 1=存在失败 / 2=依赖缺失（python 或 `jsonschema` 不可用），CI 与本地同语义；③**单一事实源**——错误码在 `tools/freeze_codes.py`、规范化在 `tools/jcs.py`、视图在 `tools/gen_docs_views.py`，脚本间只 import 不复制；④**清单与计数目录派生**——schema 件数 = `schemas/*.json`，实例数与断言数由脚本自报，文档只许复述实测值（C4/C4b 守护）。
工程化外围：`pyproject.toml` 钉 `jsonschema==4.26.0`（`date-time` 断言由本仓库自实现，不依赖 `rfc3339-validator`）；`.github/workflows/gates.yml` 在 ubuntu + windows × py3.12 跑同一 `run_gates.sh`；`.gitignore` 排除 `__pycache__`/`*.pyc` 与会话遥测目录。

**冻结判据 = 四脚本全绿**（`validate_freeze.py`、`check_cross_refs.py`、`gen_docs_views.py --check`、`gen_composites.py --check`），人工签核只负责脚本不可判定项（四方签核、夹具/脚本评审、登记项确认）。

**门禁首跑实录（D26 论据）**：门禁首次运行即捕获 5 项真实失败，全部属人工通读不可判定类——①values 的 if/then 误置于数组层而非 items 内（连续两轮人工评审未发现的**实质 schema 缺陷**，导致一切合法 result 卡被拒）；②row_id pattern 字面量含不可见字符（视觉与 ASCII 无差、字节不同，re 手测通过而 jsonschema 按文件判失败——**人工阅读原理上不可发现**）；③④⑤版本对偶三处漂移。修复后全绿。这正是"冻结判据必须 CI 化"的实证：残留缺陷 100% 落在机器可判定层。

## 十一、修订对照表（D26/D27）
| 级别 | 项 | 处置 |
|---|---|---|
| D27 | 文档门禁化（v1.6.0→v1.7.0） | 门禁 v2 四层 G1–G4 + 三视图机生成（`gen_docs_views.py`）+ 四脚本冻结判据（§五/§十） |
| P0-1 | $ref 占位/中文引用 | ClaimRow/Contracts 权威文件内嵌 definitions；门禁 $ref 全解析 |
| P0-2 | 版本号自相矛盾 | 版本对偶绑定规则 + check_cross_refs.py |
| P0-3 | T4b 依赖阶段 2+ 组件 | T4b 用一次性最小对账夹具（M3 交付），产品级对账阶段 2+，M3 注记 |
| P0-4 | rejected_append 落点 | §〇 术语表：reject_log/reject_logged；声明链状态列 |
| P1-5 | T5a(i) 错误码双属 | 缺失→步 1 SCHEMA_FAIL；不可解析→步 4 PLAN_UNBOUND（§1.4/矩阵拆分） |
| P1-6 | id 派生/重放基准 | §1.8 稳定投影派生 row_id；replay_normalized_hash |
| P1-7 | 时序键 | row_seq（§1.5/§1.7） |
| P1-8 | MANIFEST 来源 | LM 只读挂载注册表；run_context_ref；MANIFEST_CONTEXT_MISMATCH |
| P1-9 | owner 无签发方 | owner 废除→on_behalf_of_role + 凭证映射表 |
| P1-10 | 复活 vs 排除清单冲突 | 证据/谱系分工 + is_revival 三条件 + T5f + revival_permits |
| P1-11 | 量纲/α-spending | §六：两侧同量表、δ 明示、中期只判失败/继续、等效仅终末 |
| P1-12 | 投稿决策一致率构念错位 | §六：双条件建锚，阶段 3 交付；不等同于分数偏差，原文数值口径已删 |
| P1-13 | 引用侧不设防 | 步 6 + ManifestEntry + 档位矩阵 + 四错误码 |
| P1-14 | MVP 数字溯源边界 | §四注记 + 总纲 limitation（抽检口径） |
| P1-15 | O(N²)/复用算术 | checkpoint 机制；M1 双轨排期（总纲 §12 注记：复用率区间改"含未验证假设，双轨验证后校准"，数值待校准后落笔） |
| P1-16 | L1 平台能力 | 阶段 1 前置 PoC（正例节） |
| P1 漂移#1/#10 | 文档里 schemas 清单计数硬编码（手写「N 个 schema 文件」类表述） | 清单改为 `schemas/*.json` 目录派生；§五 5.1 与 §十 均不再写死计数（D27） |
| P1 漂移#3 | 分支实例计数与实际执行不符 | §1.4 重写为 I01–I20 二十例 + ClaimRow 三例，全部由门禁 G2 机器执行（D27） |
| P1 漂移#4 | 「T5a–e」漏 T5f | 全文统一 T5a–f；矩阵 T5f 行保留（D27 复核） |
| P1 漂移#11 | C4 白名单断言宣称入门禁而实际未入 | 已入 G1c，正/负 fixture 计数进 G1 断言（D27） |
| P1 漂移#12 | ClaimRow 版本字段为自由串 | claimrow-1.2.0 起 `const "1.4.0"`，G2 备不符反例（D27） |
| P2 | 检视网格越界与 σ_d 边界缺失 | §六：网格 99/124/149、max n=150 为终末判定点、反解 σ_d≤1.48（D27） |
| P2×9 | 术语/计数/封闭性/pattern 等 | §〇 术语表、六件套计数、C5/C7 封闭、版本 pattern 放宽、csv_cast、figure 子集 R-05 等；未尽项登记 §5.4 |
