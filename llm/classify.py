"""간호사 응답(텍스트) → 수락 / 거절+사유 / 의사 확인 중 / 무응답.

규칙 기반을 먼저 돌리고, 애매하면(규칙이 못 잡으면) LLM에 묻는다.
부정 표현("안 돼요", "어려워요")이 수락 키워드("가능")보다 우선한다: "수용 가능한 병상이 없어요" → 거절.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from schema import CallStatus

from .client import get_client

# 번복·거절 사유 (CLAUDE.md 4절)
REJECT_REASONS = [
    # "병상은 있는데 의사가 없어요"를 병상 없음으로 착각하지 않도록 '없음'과 붙어 있을 때만
    ("병상 없음", r"(?:병상|자리|베드|침대)\s*(?:이|가|은|는|도)?\s*(?:없|부족|모자)|만실|꽉\s*찼|포화"),
    ("의사 부재", r"(?:의사|당직|선생님|교수님|전문의).{0,6}(?:없|부재|안\s*계|수술\s*중)|당직\s*없"),
    ("치료 역량 부족", r"(?:시술|수술|치료|처치).{0,6}(?:안\s*돼|불가|못\s*해|어려)|장비|역량|전문의"),
    ("다른 응급환자 처치 중", r"다른\s*환자|(?:중환|환자).{0,6}많|바빠|여유\s*없"),
]

_REJECT = (r"안\s*(?:돼|되|됩|될)|어렵|어려|힘들|불가|못\s*(?:받|해|하)|받기\s*어|거절|안\s*받|안\s*계|"
           r"없어요|없습니다|없네요|죄송|만실|꽉\s*찼|포화|"
           r"다른\s*(?:병원|데|곳)|(?:센터|병원)\s*(?:으로|로)\s*가세요")
_CHECKING = r"확인\s*(?:해|하고|후|중|이\s*필요)|연락\s*드리|여쭤|물어\s*보|잠시만|잠깐만|기다려|다시\s*(?:연락|전화)|콜백|보고\s*(?:하고|드리)"
_ACCEPT = r"(?:받을|받겠|받아|수용|가능|오세요|보내\s*주|데려오|와\s*주세요|됩니다|돼요|괜찮)"


@dataclass
class ClassifyResult:
    status: str
    reject_reason: Optional[str] = None
    confidence: float = 1.0          # 규칙 1.0 / LLM 0.8 / 판단 불가 0.0

    def to_dict(self) -> dict:
        return {"status": self.status, "reject_reason": self.reject_reason, "confidence": self.confidence}


def _reject_reason(t: str) -> str:
    for reason, pat in REJECT_REASONS:
        if re.search(pat, t):
            return reason
    return "기타"


def classify_rules(text: Optional[str]) -> Optional[ClassifyResult]:
    if text is None or not text.strip():
        return ClassifyResult(CallStatus.NO_ANSWER.value)
    t = text.strip()
    if re.search(_REJECT, t):
        return ClassifyResult(CallStatus.REJECTED.value, _reject_reason(t))
    if re.search(_CHECKING, t):
        return ClassifyResult(CallStatus.DOCTOR_CHECKING.value)
    if re.search(_ACCEPT, t):
        return ClassifyResult(CallStatus.ACCEPTED.value)
    return None


LLM_SYSTEM = """너는 응급실 간호사의 전화 응답을 분류한다. JSON 하나만 출력한다.
{"status": "수락"|"거절"|"의사 확인 중"|"무응답",
 "reject_reason": "병상 없음"|"의사 부재"|"치료 역량 부족"|"다른 응급환자 처치 중"|"기타"|null}
확실하지 않으면 "의사 확인 중"으로 답한다 (수락으로 잘못 판단하는 것이 가장 위험하다)."""


def classify(text: Optional[str], use_llm: bool = True) -> ClassifyResult:
    r = classify_rules(text)
    if r is not None:
        return r
    client = get_client() if use_llm else None
    if client is not None:
        try:
            d = client.chat_json(LLM_SYSTEM, text or "")
            status = d.get("status")
            if status in {s.value for s in CallStatus}:
                return ClassifyResult(status, d.get("reject_reason"), 0.8)
        except Exception:
            pass
    # 판단 불가 → 수락으로 오판하지 않도록 '의사 확인 중' 처리 후 재질문 대상
    return ClassifyResult(CallStatus.DOCTOR_CHECKING.value, None, 0.0)
