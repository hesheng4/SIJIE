#!/usr/bin/env bash
# run_gates.sh — D:\HuaWei 阶段 1 冻结候选包的统一门禁入口
#
# 平台：Windows git-bash / WSL / Ubuntu 均可运行（只依赖 bash + python）。
# 用法：bash run_gates.sh
#
# 退出码语义（与 tools/validate_freeze.py 对齐）：
#   0 = 全绿（check_docs_consistency.py 尚未落地时该项仅 WARN，不计失败）
#   1 = 至少一项门禁真实失败
#   2 = 依赖缺失（找不到 python / 缺 jsonschema / 某门禁自身报告依赖异常）
#
# 设计要点：
#   - 不用 set -e：逐项跑完并汇总，避免第一项失败掩盖后续结果；
#   - PYTHONIOENCODING=utf-8：门禁输出为 UTF-8 中文（Windows cp936 会乱码）；
#   - PYTHONDONTWRITEBYTECODE=1：门禁运行不往仓库里落 __pycache__（保持工作树干净）；
#   - 每一步打印 [GATE] 名称 + rc + PASS/FAIL/WARN，最后给汇总。

set -uo pipefail

# 仓库根 = 本脚本所在目录；保证从任意 cwd 调用都能找到 schemas/ 与 tools/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || { echo "[GATE] 进入仓库根失败 → exit 2"; exit 2; }

export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
export PYTHONDONTWRITEBYTECODE=1

echo "==================== 阶段 1 冻结门禁 ===================="
echo "repo:   $SCRIPT_DIR"
echo "utf-8:  PYTHONIOENCODING=$PYTHONIOENCODING"
echo

# ---------- 解释器探测 ----------
PY=""
if [ -n "${PYTHON:-}" ] && command -v "$PYTHON" >/dev/null 2>&1; then
  PY="$PYTHON"
elif command -v python >/dev/null 2>&1; then
  PY="python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
fi

if [ -z "$PY" ]; then
  echo "[GATE] 环境预检 python ......... FAIL（未找到 python，需 Python >= 3.11）"
  echo "run_gates: 依赖缺失（python）→ exit 2"
  exit 2
fi
echo "[GATE] 环境预检 python ......... PASS（$("$PY" --version 2>&1)）"

# ---------- jsonschema 依赖预检（validate_freeze 的硬依赖）----------
if "$PY" -c 'import jsonschema' >/dev/null 2>&1; then
  JS_VER="$("$PY" -c 'import importlib.metadata as m; print(m.version("jsonschema"))' 2>/dev/null)"
  echo "[GATE] 环境预检 jsonschema ..... PASS（${JS_VER:-unknown}）"
else
  echo "[GATE] 环境预检 jsonschema ..... FAIL（pip install jsonschema==4.26.0）"
  echo "run_gates: 依赖缺失（jsonschema）→ exit 2"
  exit 2
fi
echo

FAILED=()
RESULTS=()
MISSING_DEPS=0

# run_gate <序号> <展示名> <命令...>
run_gate() {
  local n="$1" name="$2"
  shift 2
  echo "---- [GATE $n] $name ----"
  echo "\$ $*"
  "$@"
  local rc=$?
  echo
  if [ "$rc" -eq 0 ]; then
    echo "[GATE $n] $name ......... PASS（rc=0）"
    RESULTS+=("[GATE $n] $name = PASS")
  elif [ "$rc" -eq 2 ]; then
    echo "[GATE $n] $name ......... MISSING-DEP（rc=2）"
    RESULTS+=("[GATE $n] $name = MISSING-DEP")
    MISSING_DEPS=1
  else
    echo "[GATE $n] $name ......... FAIL（rc=$rc）"
    RESULTS+=("[GATE $n] $name = FAIL（rc=$rc）")
    FAILED+=("$name")
  fi
  return 0
}

run_gate 1 "jcs RFC 8785 自测（35 向量）" "$PY" tools/jcs.py --selftest
run_gate 2 "gen_composites --check（复合件与生成结果一致）" "$PY" tools/gen_composites.py --check
run_gate 3 "validate_freeze（G1–G4 四层判据）" "$PY" tools/validate_freeze.py
run_gate 4 "check_cross_refs（版本对偶绑定）" "$PY" tools/check_cross_refs.py

# 文档口径一致性：Lead 正在落地，缺失时仅 WARN（便于并行开发），存在则失败即失败
if [ -f tools/check_docs_consistency.py ]; then
  run_gate 5 "check_docs_consistency（文档口径一致性）" "$PY" tools/check_docs_consistency.py
else
  echo "---- [GATE 5] check_docs_consistency（文档口径一致性）----"
  echo "\$ python tools/check_docs_consistency.py"
  echo "[GATE 5] check_docs_consistency ......... WARN（脚本尚未落地，跳过；不计失败）"
  RESULTS+=("[GATE 5] check_docs_consistency = WARN（缺失，跳过）")
  echo
fi

# M1 最小闭环行为验收：实现缺失时同样只 WARN（规格门禁不该被运行时代码绑架）
if [ -f tools/m1_acceptance.py ]; then
  run_gate 6 "m1_acceptance（M1 八步链 + 六道 rail 行为验收）" "$PY" tools/m1_acceptance.py
else
  echo "---- [GATE 6] m1_acceptance（M1 八步链 + 六道 rail 行为验收）----"
  echo "\$ python tools/m1_acceptance.py"
  echo "[GATE 6] m1_acceptance ......... WARN（m1/ 或验收脚本缺失，跳过；不计失败）"
  RESULTS+=("[GATE 6] m1_acceptance = WARN（缺失，跳过）")
  echo
fi

# ---------- 汇总 ----------
echo "========================= 汇总 ========================="
for r in "${RESULTS[@]}"; do
  echo "  $r"
done
echo

if [ "$MISSING_DEPS" -ne 0 ]; then
  echo "run_gates: 依赖缺失 → exit 2"
  exit 2
fi
if [ "${#FAILED[@]}" -ne 0 ]; then
  echo "run_gates: ${#FAILED[@]} 项门禁失败（${FAILED[*]}）→ exit 1"
  exit 1
fi
echo "run_gates: 全绿 → exit 0"
exit 0
