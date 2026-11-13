"""환자 데이터 → 병원용 대본 (TTS로 읽힐 문장).

간호사 인터뷰 반영 (CLAUDE.md 4절):
- 첫 문장 고정: "119 구급대 응급환자 수용 문의입니다."
- 첫 몇 초 안에 중증도·나이·주증상
- 그 다음 활력징후 → 복용약·수술력 → 상황별 정보 → 도착 예정 → 수용 여부 질문
LLM을 쓰지 않는 템플릿 방식: 대본이 매번 같은 구조여야 간호사가 듣기 편하고, 사실 왜곡 위험이 없다.
"""
from __future__ import annotations

from typing import Optional

from schema import Patient

OPENING = "119 구급대 응급환자 수용 문의입니다."
CANCEL_OPENING = "119 구급대입니다. 앞서 문의드린 환자는 다른 병원으로 이송이 확정되어 수용 문의를 취소합니다. 감사합니다."

_CONS_SPEECH = {"무반응": "의식 없음", "통증반응": "통증에만 반응", "언어반응": "부르면 반응", "명료": "의식 명료"}
_SEX = {"M": "남자", "F": "여자"}


def _age_sex(p: Patient) -> str:
    age = ""
    if p.age is not None:
        age = f"{p.age}대" if p.extra.get("age_is_range") else f"{p.age}세"
    return " ".join(x for x in [age, _SEX.get(p.sex or "", "")] if x) or "나이 미상"


def _headline(p: Patient) -> str:
    parts = [f"{p.severity or ''} {p.emergency_type or ''} 환자".strip()]
    parts.append(_age_sex(p))
    if p.cpr:
        parts.append(f"현재 심폐소생술 {p.cpr_minutes}분째" if p.cpr_minutes else "심폐소생술 중")
    elif p.consciousness:
        parts.append(_CONS_SPEECH.get(p.consciousness, p.consciousness))
    if p.chief_complaint and not p.cpr:
        parts.append(p.chief_complaint)
    return ", ".join(parts) + "입니다."


def _vitals(p: Patient) -> Optional[str]:
    v = []
    if p.blood_pressure:
        s, _, d = p.blood_pressure.partition("/")
        v.append(f"혈압 {s}에 {d}")
    if p.pulse is not None:
        v.append(f"맥박 {p.pulse}")
    if p.spo2 is not None:
        v.append(f"산소포화도 {p.spo2}")
    if p.gcs is not None:
        v.append(f"GCS {p.gcs}")
    return ("활력징후는 " + ", ".join(v) + "입니다.") if v else None


def _history(p: Patient) -> Optional[str]:
    s = []
    if p.medications:
        s.append("복용약 " + ", ".join(p.medications))
    if p.surgery_history:
        s.append("수술력 " + ", ".join(p.surgery_history))
    return (", ".join(s) + "입니다.") if s else None


def _extras(p: Patient) -> Optional[str]:
    e, s = p.extra, []
    yn = lambda k, yes, no: s.append(yes if e[k] else no) if k in e else None
    yn("witnessed", "목격된 심정지", "목격 없는 심정지")
    yn("defibrillation", "제세동 시행", "제세동 미시행")
    yn("rosc", "자발순환 회복", "자발순환 미회복")
    if "mechanism" in e:
        s.append(f"손상 원인 {e['mechanism']}")
    if "injury_site" in e:
        s.append(f"{e['injury_site']} 손상")
    if "bleeding" in e:
        s.append(f"출혈 {e['bleeding']}")
    yn("ecg_abnormal", "심전도 이상 있음", "심전도 이상 없음")
    if "last_known_well" in e:
        s.append(f"마지막 정상 확인 {e['last_known_well']}")
    yn("paralysis", "마비 또는 언어장애 있음", "마비 없음")
    return (", ".join(s) + "입니다.") if s else None


def build_script(p: Patient, eta_min: Optional[float] = None) -> str:
    lines = [OPENING, _headline(p), _vitals(p), _history(p), _extras(p)]
    if p.onset_time:
        lines.append(f"발생 시각은 {_speak_time(p.onset_time)}입니다.")
    if eta_min is not None:
        lines.append(f"도착까지 약 {round(eta_min)}분 예상됩니다.")
    lines.append("수용 가능하신지 말씀해 주세요.")
    return " ".join(x for x in lines if x)


def build_sms(p: Patient) -> str:
    """통화 후 병원에 보낼 환자 요약 문자."""
    return "[119 수용문의] " + " ".join(x for x in [_headline(p), _vitals(p), _history(p), _extras(p)] if x)


def _speak_time(iso: str) -> str:
    try:
        hhmm = iso.split("T")[1][:5]
        h, m = hhmm.split(":")
        return f"{int(h)}시 {int(m)}분"
    except (IndexError, ValueError):
        return iso
