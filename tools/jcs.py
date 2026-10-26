#!/usr/bin/env python3
"""jcs.py — RFC 8785 (JSON Canonicalization Scheme) 的确定性实现（仅标准库）。

为什么需要本文件（交付物 1.8 节）：row_id / replay_normalized_hash 等派生标识必须
跨实现可复算；json.dumps(sort_keys=True, ensure_ascii=False) 不是 RFC 8785 —
它在数字（1.0 / -0.0 / 1e-07 / 1e20）、字符串转义（U+000F）与键排序
（按 UTF-16 码元而非 Unicode 码点）三处都会产生不同字节。

对外 API
  canonical(obj) -> str      RFC 8785 规范化文本（UTF-8 可编码，无空白）
  digest16(obj) -> str       sha256(canonical(obj))[:16]
  canonical_number(x) -> str ES6 Number::toString（RFC 8785 3.2.2.3）
  sort_key(s) -> bytes       UTF-16 码元序（RFC 8785 3.2.3）
  selftest() -> list[(name, ok)]

自测：python tools/jcs.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import sys

__all__ = ["canonical", "digest16", "canonical_number", "sort_key", "selftest",
           "RFC_VECTORS", "NUMBER_VECTORS", "SORT_VECTORS", "STRING_VECTORS"]

_MAX_SAFE_INT = 2 ** 53 - 1
_BS = chr(92)  # 反斜杠；源文件不含该字符，避免转义层漂移


def sort_key(s: str) -> bytes:
    """对象键排序键：UTF-16 码元的大端字节序（RFC 8785 3.2.3）。"""
    return s.encode("utf-16-be", "surrogatepass")


def canonical_number(x) -> str:
    """ES6 Number::toString(x)，等价于 RFC 8785 3.2.2.3 的数字序列化。"""
    if isinstance(x, bool):  # bool 是 int 子类，单独拦截
        raise TypeError("bool 不是 number")
    if isinstance(x, int):
        if abs(x) <= _MAX_SAFE_INT:
            return str(x)
        x = float(x)
    x = float(x)
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError("NaN/Infinity 不可规范化（RFC 8785 要求拒绝）")
    if x == 0.0:
        return "0"
    sign = "-" if x < 0 else ""
    digits, exp = _decompose(repr(abs(x)))  # repr 给出最短往返十进制
    while len(digits) > 1 and digits.endswith("0"):  # 去尾零（如 repr 的 ".0"）
        digits = digits[:-1]
        exp += 1
    k = len(digits)
    n = k + exp  # 小数点前的位数
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        mant = digits if k == 1 else digits[0] + "." + digits[1:]
        body = mant + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + body


def _decompose(s: str) -> tuple[str, int]:
    """'1.234e+05' 拆为 ('1234', 2)：value = int(digits) * 10**exp（digits 无前导零）。"""
    s = s.lower()
    if "e" in s:
        mant, est = s.split("e")
        exp = int(est)
    else:
        mant, exp = s, 0
    if "." in mant:
        ip, fp = mant.split(".")
    else:
        ip, fp = mant, ""
    digits = (ip + fp).lstrip("0") or "0"
    exp += -len(fp)  # value = int(ip+fp) * 10**-len(fp)；前导零不改变整数值
    return digits, exp


_ESC = {'"': _BS + '"', _BS: _BS * 2, chr(8): _BS + "b", chr(9): _BS + "t",
        chr(10): _BS + "n", chr(12): _BS + "f", chr(13): _BS + "r"}


def _encode_string(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch in _ESC:
            out.append(_ESC[ch])
        elif o < 0x20 or 0xD800 <= o <= 0xDFFF:
            out.append(_BS + "u%04x" % o)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def canonical(obj) -> str:
    """RFC 8785 规范化：对象键按 UTF-16 码元排序，无空白，UTF-8 文本输出。"""
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, str):
        return _encode_string(obj)
    if isinstance(obj, (int, float)):
        return canonical_number(obj)
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(canonical(v) for v in obj) + "]"
    if isinstance(obj, dict):
        for k in obj:
            if not isinstance(k, str):
                raise TypeError("JCS 要求对象键为字符串")
        items = sorted(obj.items(), key=lambda kv: sort_key(kv[0]))
        return "{" + ",".join(_encode_string(k) + ":" + canonical(v) for k, v in items) + "}"
    raise TypeError("不可规范化的类型: %r" % (type(obj),))


def digest16(obj) -> str:
    """sha256(canonical(obj)) 的前 16 个十六进制字符（row_id 等 id 后缀口径）。"""
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()[:16]


# ---------- 官方向量 ----------
# 数字向量取自 RFC 8785 Appendix B（源自 ECMAScript Number::toString 测试集）
NUMBER_VECTORS = [
    (1.0, "1"),
    (0.0, "0"),
    (-0.0, "0"),
    (4.5, "4.5"),
    (2e-3, "0.002"),
    (1e-7, "1e-7"),
    (1e-6, "0.000001"),
    (1e20, "100000000000000000000"),
    (1e21, "1e+21"),
    (1e30, "1e+30"),
    (333333333.33333329, "333333333.3333333"),
    (1.2345678901234568e20, "123456789012345680000"),
    (0.000000000000000000000000001, "1e-27"),
    (-1.5, "-1.5"),
    (123, "123"),
]

_U000F = chr(15)
_U0020 = chr(32)
_U20AC = chr(0x20AC)
_UFFFD = chr(0xFFFD)
_U1F600 = chr(0x1F600)
_CR = chr(13)
_LF = chr(10)
_TAB = chr(9)
_COMBINED = _U20AC + "$" + _U000F + _LF + "A'B" + '"' + _BS + _BS + '"' + "/"

# 字符串转义向量取自 RFC 8785 3.2.2.2（逐字符 + 组合）
STRING_VECTORS = [
    (chr(0), '"' + _BS + 'u0000"'),
    (_U000F, '"' + _BS + 'u000f"'),
    (_LF, '"' + _BS + 'n"'),
    (_TAB, '"' + _BS + 't"'),
    ('"', '"' + _BS + '"' + '"'),
    (_BS, '"' + _BS * 2 + '"'),
    ("/", '"/"'),
    (_U20AC, '"' + _U20AC + '"'),
    ("abc", '"abc"'),
    (_COMBINED,
     '"' + _U20AC + "$" + _BS + "u000f" + _BS + "n" + "A'B" + _BS + '"'
     + _BS * 4 + _BS + '"' + "/" + '"'),
]

# 键排序：UTF-16 码元序（U+000A 小于 U+000D 小于 U+000F 小于 A 小于 U+20AC 小于
# U+1F600 小于 U+FFFD；注意 U+1F600 的 UTF-16 首码元 U+D83D 小于 U+FFFD）
SORT_VECTORS = [
    ([_UFFFD, _U1F600, _U20AC, "A", _U000F, _CR, _LF],
     [_LF, _CR, _U000F, "A", _U20AC, _U1F600, _UFFFD]),
]

# 整体规范化向量（RFC 8785 Appendix A 结构，数字与键序按 3.2.2.3/3.2.3 修正）
RFC_VECTORS = [
    ({"numbers": [333333333.33333329, 1e30, 4.5, 2e-3, 0.000000000000000000000000001],
      "string": _COMBINED,
      "literals": [None, True, False]},
     '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
     '"string":"' + _U20AC + "$" + _BS + "u000f" + _BS + "n" + "A'B" + _BS + '"'
     + _BS * 4 + _BS + '"' + "/" + '"}'),
    ({"b": 1, "a": [1, {"y": 2, "x": 1}]}, '{"a":[1,{"x":1,"y":2}],"b":1}'),
    ({}, "{}"),
    ([], "[]"),
    ({"k": "1"}, '{"k":"1"}'),
]


def selftest() -> list[tuple[str, bool]]:
    """返回 [(用例名, 是否通过)]；validate_freeze.py 与 --selftest 共用。"""
    results: list[tuple[str, bool]] = []
    for i, (val, want) in enumerate(NUMBER_VECTORS):
        try:
            got = canonical_number(val)
        except Exception as e:  # noqa: BLE001
            got = "<error: %s>" % e
        results.append(("number#%d %r" % (i, val), got == want))
    for i, (s, want) in enumerate(STRING_VECTORS):
        results.append(("string#%d" % i, _encode_string(s) == want))
    for raw, want in SORT_VECTORS:
        results.append(("sort UTF-16", sorted(raw, key=sort_key) == want))
    for i, (obj, want) in enumerate(RFC_VECTORS):
        results.append(("canonical#%d" % i, canonical(obj) == want))
    # 往返：规范化输出可被 JSON 解析且再规范化不变
    for obj in [{"a": [1.0, -0.0, 1e20]}, {"s": _U000F + _LF, "n": None}]:
        once = canonical(obj)
        results.append(("idempotent", canonical(json.loads(once)) == once))
    for bad in [float("nan"), float("inf")]:
        try:
            canonical(bad)
            results.append(("reject %r" % bad, False))
        except ValueError:
            results.append(("reject %r" % bad, True))
    return results


def main(argv: list[str]) -> int:
    if "--selftest" in argv or not argv:
        res = selftest()
        bad = [n for n, ok in res if not ok]
        for name, ok in res:
            print(("[PASS] " if ok else "[FAIL] ") + name)
        print("%d/%d passed" % (len(res) - len(bad), len(res)))
        return 0 if not bad else 1
    if argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    with open(argv[0], encoding="utf-8") as f:
        print(canonical(json.load(f)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))