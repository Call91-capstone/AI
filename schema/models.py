"""팀 공유 데이터 형식 (AI ↔ server).

- 표준 라이브러리 dataclass만 사용 → GPU·외부 패키지 없이 집에서도 동작
- 필드 이름은 snake_case (server 담당과 합의 전 초안, CLAUDE.md 7절)
- JSON 직렬화: to_dict() / from_dict()
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from typing import Any, Optional


class EmergencyType(str, Enum):
    CARDIAC_ARREST = "심정지"
    MAJOR_TRAUMA = "중증외상"
    MI = "급성심근경색"
    STROKE = "뇌졸중"
    OTHER = "기타"


class Severity(str, Enum):
    CRITICAL = "최중증"   # 심정지, 중증외상
    SEVERE = "중증"
    MILD = "경증"


class CallStatus(str, Enum):
    PENDING = "대기"
    DIALING = "발신 중"
    ACCEPTED = "수락"
    REJECTED = "거절"
    DOCTOR_CHECKING = "의사 확인 중"
    NO_ANSWER = "무응답"
    CANCELLED = "취소"
    DIRECT = "직접 전화"     # 구급대원이 직접 통화 → AI 발신 중단


@dataclass
class Patient:
    # 공통
    age: Optional[int] = None
    sex: Optional[str] = None                 # "M" / "F"
    consciousness: Optional[str] = None       # 명료 / 언어반응 / 통증반응 / 무반응 (AVPU)
    gcs: Optional[int] = None
    cpr: Optional[bool] = None
    cpr_minutes: Optional[int] = None
    blood_pressure: Optional[str] = None      # "90/60"
    pulse: Optional[int] = None
    spo2: Optional[int] = None
    chief_complaint: Optional[str] = None
    medications: list[str] = field(default_factory=list)
    surgery_history: list[str] = field(default_factory=list)
    emergency_type: Optional[str] = None      # EmergencyType 값
    severity: Optional[str] = None            # Severity 값
    onset_time: Optional[str] = None          # ISO8601 또는 "30분 전" 같은 원문
    # 상황별 추가 항목 (CLAUDE.md 6절)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Patient":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class CallResult:
    hospital_id: str
    status: str                               # CallStatus 값
    reject_reason: Optional[str] = None
    transcript: Optional[str] = None          # 간호사 응답 원문 (분쟁 시 근거)
    elapsed_sec: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Hospital:
    """server → AI: 정렬된 병원 목록의 한 항목 (형식 합의 필요)."""
    hospital_id: str
    name: str
    phone: str                                # 시연: 반드시 팀원 폰 번호만
    eta_min: Optional[float] = None
    capabilities: list[str] = field(default_factory=list)  # ["외상센터", "PCI", "뇌졸중"]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Hospital":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})
