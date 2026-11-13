"""한글 숫자 읽기 → 아라비아 숫자 ("구십에 육십" → "90에 60", "일흔" → "70")."""
from __future__ import annotations

import re

_DIGITS = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9}
_UNITS = {"십": 10, "백": 100}
_NATIVE = {"스물": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60, "일흔": 70, "여든": 80, "아흔": 90}

# 단위(십/백)가 반드시 하나 이상 들어간 덩어리만 숫자로 본다 → "이", "사" 같은 일반 단어 오변환 방지
_SINO = re.compile(r"[일이삼사오육륙칠팔구]?백(?:[일이삼사오육륙칠팔구]?십)?[일이삼사오육륙칠팔구]?|[일이삼사오육륙칠팔구]?십[일이삼사오육륙칠팔구]?")


def _sino_to_int(s: str) -> int:
    total, cur = 0, 0
    for ch in s:
        if ch in _DIGITS:
            cur = _DIGITS[ch]
        elif ch in _UNITS:
            total += (cur or 1) * _UNITS[ch]
            cur = 0
    return total + cur


def normalize_numbers(text: str) -> str:
    for word, val in _NATIVE.items():
        text = text.replace(word, str(val))
    return _SINO.sub(lambda m: str(_sino_to_int(m.group())), text)
