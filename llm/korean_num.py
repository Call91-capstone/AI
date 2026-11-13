"""한글 숫자 읽기 → 아라비아 숫자 ("구십에 육십" → "90에 60", "일흔" → "70")."""
from __future__ import annotations

import re

_DIGITS = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9}
_UNITS = {"십": 10, "백": 100, "천": 1000}
_NATIVE = {"스물": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60, "일흔": 70, "여든": 80, "아흔": 90}

# 단위(십/백)가 반드시 하나 이상 들어간 덩어리만 숫자로 본다 → "이", "사" 같은 일반 단어 오변환 방지
_D = "[일이삼사오육륙칠팔구]"
_SINO = re.compile(rf"{_D}?천(?:{_D}?백)?(?:{_D}?십)?{_D}?|{_D}?백(?:{_D}?십)?{_D}?|{_D}?십{_D}?")


def _sino_to_int(s: str) -> int:
    total, cur = 0, 0
    for ch in s:
        if ch in _DIGITS:
            cur = _DIGITS[ch]
        elif ch in _UNITS:
            total += (cur or 1) * _UNITS[ch]
            cur = 0
    return total + cur


_NATIVE_ONES = {"하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "넷": 4, "네": 4, "다섯": 5,
                "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
_NATIVE_RE = re.compile("(" + "|".join(_NATIVE) + ")(" + "|".join(sorted(_NATIVE_ONES, key=len, reverse=True)) + ")?")

# STT가 띄어 쓴 숫자 붙이기: "육십 오 세" → "육십오 세" (뒤에 단위가 올 때만, "칠십 이 남자" 오변환 방지)
_SPACED_ONES = re.compile(r"(십)\s([일이삼사오육칠팔구])(?=\s?(?:세|살|분|점|대|에|도|회|번))")
# "백 이십" → "백이십" (백 뒤에 십 단위 덩어리가 띄어 나올 때)
_SPACED_TENS = re.compile(r"(백)\s(?=[일이삼사오육칠팔구]?십)")


def _native(m: re.Match) -> str:
    return str(_NATIVE[m.group(1)] + _NATIVE_ONES.get(m.group(2) or "", 0))


_ONES_RE = "|".join(sorted(_NATIVE_ONES, key=len, reverse=True))
# "열일곱" → 17 ("열 나고", "열성경련"은 뒤에 일의 자리가 없으므로 그대로)
_TEEN_RE = re.compile("(?<![가-힣])열(" + _ONES_RE + ")")
# "세 살", "다섯 살" → 3 살, 5 살 (나이 단위 '살' 앞에서만)
_ONES_AGE_RE = re.compile("(?<![가-힣])(" + _ONES_RE + r")\s*(?=살)")


def normalize_numbers(text: str) -> str:
    text = text.replace("스무", "스물")
    text = _NATIVE_RE.sub(_native, text)
    text = _TEEN_RE.sub(lambda m: str(10 + _NATIVE_ONES[m.group(1)]), text)
    text = _ONES_AGE_RE.sub(lambda m: f"{_NATIVE_ONES[m.group(1)]} ", text)
    text = _SPACED_ONES.sub(r"\1\2", text)
    text = _SPACED_TENS.sub(r"\1", text)
    return _SINO.sub(lambda m: str(_sino_to_int(m.group())), text)
