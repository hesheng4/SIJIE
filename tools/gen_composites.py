#!/usr/bin/env python3
"""gen_composites.py — 生成复合 schema 文件（D26 权威源机制的一部分）。

从基础 schema 生成两个复合文件，保证 definitions 内嵌、$ref 全部本地可解析：
  schemas/claimrow-1.2.0.json   = ClaimRow 结构 + definitions.ClaimCard（全文内嵌 1.4.0）
  schemas/contracts-1.1.0.json  = 契约信封 + definitions.C1..C8 + definitions.ExclusionList（全文内嵌）

复合文件是权威源；基础文件变更后必须重新生成。默认行为是 --check（只读比对，
不一致即非零退出，供 CI/门禁使用）；只有显式 --write 才覆写权威文件。
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
S = ROOT / "schemas"


def load(name: str) -> dict:
    with open(S / name, encoding="utf-8") as f:
        return json.load(f)


def dump(obj: dict, name: str) -> None:
    with open(S / name, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


HEX_CLS = "abcdef0123456789"  # 无连字符、纯 ASCII 构造，杜绝不可见字符混入


def id_pat(prefix: str) -> str:
    return "^" + prefix + "[" + HEX_CLS + "]{16}$"


def build_claimrow() -> tuple[str, dict]:
    card = load("claimcard-1.4.0.json")
    card.pop("$schema", None)  # 嵌套 definitions 不携带独立 $schema
    # $ref 是文档相对的：ClaimCard 内的 #/definitions/Role 必须在 ClaimRow 根上可解析，
    # 故把嵌套 definitions 提升到复合件根（1.4.0 引入 Role 后必需；否则引用悬空）。
    nested_defs = card.pop("definitions", {})
    claimrow = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "ClaimRow",
        "version": "1.2.0",
        "type": "object",
        "additionalProperties": False,
        "required": ["row_id", "row_seq", "claimcard_schema_version", "card", "appended_at",
                     "audit_event_id", "manifest_version", "venue_profile_version"],
        "properties": {
            "row_id": {"type": "string", "pattern": id_pat("row_")},
            "row_seq": {"type": "integer", "minimum": 0,
                        "description": "声明链时序键（当前态=同 claim_id 最大 row_seq 行）"},
            "claimcard_schema_version": {
                "const": card["version"],
                "description": "与 definitions.ClaimCard 版本绑定（1.2.0 起因内嵌即权威，防混版本声明链）"},
            "card": {"$ref": "#/definitions/ClaimCard"},
            "appended_at": {"type": "string", "format": "date-time",
                            "description": "仅人读；不参与 row_id 派生与排序"},
            "audit_event_id": {"type": "string", "pattern": id_pat("evt_")},
            "manifest_version": {"type": "string"},
            "venue_profile_version": {"type": "string"}},
        "definitions": {"ClaimCard": card, **nested_defs},
    }
    return "claimrow-1.2.0.json", claimrow


def build_contracts() -> tuple[str, dict]:
    excl = load("exclusionlist-1.0.2.json")
    excl.pop("$schema", None)

    c1 = {"type": "object", "additionalProperties": False,
          "required": ["manifest_version", "semantics_handle", "knowledge_map_handle",
                       "venue_profile_version"],
          "properties": {
              "manifest_version": {"type": "string"},
              "semantics_handle": {"type": "string"},
              "knowledge_map_handle": {"type": "string"},
              "venue_profile_version": {"type": "string"}}}
    c2 = {"type": "object", "additionalProperties": False,
          "required": ["claim_ids", "figure_refs", "citation_requests"],
          "properties": {
              "claim_ids": {"type": "array", "minItems": 1,
                            "items": {"type": "string", "pattern": "^clm_"}},
              "figure_refs": {"type": "array", "items": {"type": "string"}},
              "citation_requests": {"type": "array", "items": {"type": "string"}}}}
    c3 = {"type": "object", "additionalProperties": False, "required": ["citation_cards"],
          "properties": {"citation_cards": {"type": "array", "minItems": 1, "items": {
              "type": "object", "additionalProperties": False,
              "required": ["doi", "manifest_entry_id", "verification", "locator"],
              "properties": {
                  "doi": {"type": "string", "pattern": "^10\\."},
                  "manifest_entry_id": {"type": "string", "pattern": "^mfe_[a-f0-9]{12}$"},
                  "verification": {"enum": ["primary", "survey_transfer"]},
                  "survey_doi": {"type": "string", "pattern": "^10\\."},
                  "locator": {"type": "string", "minLength": 1},
                  "snapshot_ref": {"type": "string", "pattern": "^sha256:[a-f0-9]{64}$"}}}}}}
    c4 = {"type": "object", "additionalProperties": False,
          "required": ["manuscript_ref", "claim_ids", "figure_refs", "venue_profile_version"],
          "properties": {
              "manuscript_ref": {"type": "string"},
              "claim_ids": {"type": "array", "items": {"type": "string"}},
              "figure_refs": {"type": "array", "items": {"type": "string"}},
              "venue_profile_version": {"type": "string"}},
          "description": "双盲白名单：注入 rawlog_path/execution_id/data_file 等字段一律 SCHEMA_FAIL"}
    c5 = {"type": "object", "additionalProperties": False, "required": ["review_form"],
          "properties": {
              "review_form": {"type": "object", "additionalProperties": True,
                              "description": "登记例外：子 schema 由 venue 档案 review 段运行时装配"},
              "rebuttal": {"type": "object", "additionalProperties": False,
                           "required": ["point", "response"],
                           "properties": {"point": {"type": "string"},
                                          "response": {"type": "string"}}},
              "reviewer_model": {"type": "string"}}}
    c6 = {"type": "object", "additionalProperties": False,
          "required": ["manuscript_ref", "claims_snapshot_version"],
          "properties": {
              "manuscript_ref": {"type": "string"},
              "claims_snapshot_version": {"type": "string"}}}
    c7 = {"type": "object", "additionalProperties": False,
          "required": ["report_ref", "conclusions", "exclusion_list"],
          "properties": {
              "report_ref": {"type": "string"},
              "conclusions": {"type": "object", "additionalProperties": False,
                              "required": ["passed", "failed", "undetermined"],
                              "properties": {
                                  "passed": {"type": "array", "items": {"type": "string"}},
                                  "failed": {"type": "array", "items": {"type": "string"}},
                                  "undetermined": {"type": "array", "items": {"type": "string"}}}},
              "exclusion_list": {"$ref": "#/definitions/ExclusionList"}}}
    c8 = {"type": "object", "additionalProperties": False,
          "required": ["lesson", "scope", "evidence_run_id", "source_run_status"],
          "properties": {
              "lesson": {"type": "string"},
              "scope": {"enum": ["venue", "task", "global"]},
              "evidence_run_id": {"type": "string"},
              "source_run_status": {"enum": ["success", "failed", "partial"]}}}

    roles = ["coordinator", "intake-curator", "librarian", "analyst", "writing",
             "reviewer-1", "reviewer-2", "reviewer-3", "ac", "auditor", "profile-curator"]
    contracts = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Contracts",
        "version": "1.1.0",
        "type": "object",
        "additionalProperties": False,
        "required": ["contract_id", "schema_version", "from_role", "to_role", "stage",
                     "run_id", "created_at", "payload"],
        "properties": {
            "contract_id": {"type": "string", "pattern": "^ctr_[a-f0-9]{12}$"},
            "schema_version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$"},
            "from_role": {"enum": roles},
            "to_role": {"enum": roles},
            "stage": {"type": "integer", "minimum": 1},
            "run_id": {"type": "string", "pattern": "^run_[a-z0-9_-]{6,64}$"},
            "created_at": {"type": "string", "format": "date-time"},
            "payload": {"oneOf": [{"$ref": f"#/definitions/C{i}"} for i in range(1, 9)]}},
        "definitions": {
            "C1": c1, "C2": c2, "C3": c3, "C4": c4, "C5": c5, "C6": c6, "C7": c7, "C8": c8,
            "ExclusionList": excl}}
    return "contracts-1.1.0.json", contracts


def main(argv: list[str]) -> int:
    write = "--write" in argv
    if not write and "--check" not in argv:
        print("usage: gen_composites.py --check | --write")
        return 2
    bad = []
    for name, obj in (build_claimrow(), build_contracts()):
        if write:
            dump(obj, name)
            print("[WRITE] " + name)
            continue
        got = json.loads((S / name).read_text(encoding="utf-8"))
        ok = got == obj
        print(("[PASS] " if ok else "[FAIL] ") + "复合件与生成结果一致: " + name)
        if not ok:
            bad.append(name)
    if write:
        print("composites regenerated: claimrow-1.2.0.json, contracts-1.1.0.json")
        return 0
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
