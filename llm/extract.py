"""구급대원 발화(텍스트) → 환자 데이터.

1) 규칙 기반 추출 (항상 실행, GPU 불필요)
2) LLM 사용 가능하면 LLM 추출 결과로 덮어쓰기 (null이 아닌 값만)
3) 4대 응급 상황 분류 + 중증도
4) 비정상 값 경고(혈압 900 등) + 빠진 항목 되묻기 질문

정정 발언("아니 80대")은 같은 항목이 여러 번 나오면 **마지막 값**을 쓰는 방식으로 처리한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from schema import EmergencyType, Patient, Severity

from .client import get_client
from .korean_num import normalize_numbers

KST = timezone(timedelta(hours=9))

KNOWN_MEDS = ["와파린", "아스피린", "클로피도그렐", "플라빅스", "엘리퀴스", "자렐토", "인슐린",
              "메트포르민", "니트로글리세린", "혈압약", "당뇨약", "항응고제", "항혈소판제", "고지혈증약"]

# 상황별 추가 항목: (extra 키, 되묻기 질문)
TYPE_EXTRAS: dict[str, list[tuple[str, str]]] = {
    EmergencyType.CARDIAC_ARREST.value: [
        ("witnessed", "심정지 목격 여부를 알려주세요."),
        ("defibrillation", "제세동 시행했나요?"),
        ("rosc", "자발순환 회복됐나요?"),
    ],
    EmergencyType.MAJOR_TRAUMA.value: [
        ("mechanism", "손상 원인이 무엇인가요? (교통사고, 추락 높이 등)"),
        ("injury_site", "손상 부위는 어디인가요?"),
        ("bleeding", "출혈 정도는 어떤가요?"),
    ],
    EmergencyType.MI.value: [
        ("ecg_abnormal", "심전도 이상 소견 있나요?"),
    ],
    EmergencyType.STROKE.value: [
        ("last_known_well", "마지막 정상 확인 시각은 언제인가요?"),
        ("paralysis", "마비나 언어장애 있나요?"),
    ],
}

COMMON_QUESTIONS = {
    "age": "환자 나이를 알려주세요.",
    "sex": "환자 성별을 알려주세요.",
    "consciousness": "의식 상태는 어떤가요?",
    "medications": "복용 중인 약이 있나요?",
    "surgery_history": "수술이나 시술 이력이 있나요?",
    "onset_time": "증상 발생 시각은 언제인가요?",
}

STT_HINTS = "GCS, CPR, 새츄레이션, 산소포화도, 혈압, 맥박, 와파린, 아스피린, 스텐트, 제세동, 자발순환, 흉통, 편마비"


@dataclass
class ExtractResult:
    patient: Patient
    missing: list[str] = field(default_factory=list)       # 빠진 항목 키
    questions: list[str] = field(default_factory=list)     # 되묻기 문장
    warnings: list[str] = field(default_factory=list)      # 비정상 값 재확인

    def to_dict(self) -> dict:
        return {"patient": self.patient.to_dict(), "missing": self.missing,
                "questions": self.questions, "warnings": self.warnings}


def _last(pattern: str, text: str, flags: int = 0) -> Optional[re.Match]:
    m = None
    for m in re.finditer(pattern, text, flags):
        pass
    return m


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def _preprocess(text: str) -> str:
    text = normalize_numbers(text)
    # "오 분" 처럼 단위 없는 한 자리 숫자 + 분/세/살
    single = {"일": "1", "이": "2", "삼": "3", "사": "4", "오": "5", "육": "6", "칠": "7", "팔": "8", "구": "9"}
    # "오 분", "팔점"(GCS) 처럼 단위 없는 한 자리 숫자 + 분/시간/점
    text = re.sub(r"(?<![가-힣])([일이삼사오육칠팔구])\s?(분|시간|점)", lambda m: single[m.group(1)] + m.group(2), text)
    return text


def extract_rules(text: str, now: Optional[datetime] = None) -> Patient:
    t = _preprocess(text)
    now = now or datetime.now(KST)
    p = Patient()

    if m := _last(r"(\d{1,3})\s*(?:세|살)", t):
        p.age = int(m.group(1))
    elif m := _last(r"(\d{1,2}0)\s*대", t):
        p.age = int(m.group(1))
        p.extra["age_is_range"] = True

    # "77세 남" 처럼 한 글자 표기, 남학생·남아 등도 인식
    if m := _last(r"남자|남성|남학생|남아|할아버지|여자|여성|여학생|여아|할머니|"
                  r"(?<![가-힣])[남여](?![가-힣])", t):
        p.sex = "M" if m.group()[0] in "남할" and m.group() != "할머니" else "F"

    if m := _last(r"GCS\s*(\d{1,2})|지씨에스\s*(\d{1,2})", t, re.I):
        p.gcs = int(m.group(1) or m.group(2))

    cons = _last(r"의식\s*(?:이\s*)?(?:없|저하)|무반응|반응\s*없|통증에\s*(?:만\s*)?반응|부르면\s*반응|"
                 r"의식\s*(?:은\s*|이\s*)?(?:명료|있)", t)
    if cons:
        s = cons.group()
        if "통증" in s:
            p.consciousness = "통증반응"
        elif "부르면" in s:
            p.consciousness = "언어반응"
        elif re.search(r"명료|있", s):
            p.consciousness = "명료"
        else:
            p.consciousness = "무반응"

    if _has(r"CPR|씨피알|심폐소생|가슴\s*압박", t):
        p.cpr = True
        # "CPR 시작해서 지금 20분째" 처럼 사이에 말이 끼어도 쉼표 전까지는 인정
        if m := _last(r"(?:CPR|씨피알|심폐소생술?|가슴\s*압박)[^\d,.]{0,15}?(\d{1,3})\s*분", t, re.I):
            p.cpr_minutes = int(m.group(1))

    if m := _last(r"(?:혈압|BP)?\s*(\d{2,3})\s*(?:에|/|다시|over)\s*(\d{2,3})", t, re.I):
        p.blood_pressure = f"{m.group(1)}/{m.group(2)}"
    if m := _last(r"(?:맥박|심박수?|HR|펄스)\s*(\d{2,3})", t, re.I):
        p.pulse = int(m.group(1))
    if m := _last(r"(?:산소\s*포화도|새츄레이션|새츄|사츄|SpO2|포화도)\s*(\d{2,3})", t, re.I):
        p.spo2 = int(m.group(1))

    # 복용약
    if _has(r"(?:복용\s*(?:하는\s*)?약|먹는\s*약|약)\s*(?:은\s*|이\s*)?없", t):
        p.medications = ["없음"]
    else:
        meds = [d for d in KNOWN_MEDS if d in t]
        for m in re.finditer(r"([가-힣A-Za-z]+?)\s*(?:을|를)?\s*복용", t):
            w = m.group(1)
            # "약물 과다복용"은 약 이름이 아님
            if w not in meds and w not in ("약", "중", "과다", "약물"):
                meds.append(w)
        p.medications = meds

    # 수술력
    if _has(r"수술\s*(?:력|이력|받은\s*적)?\s*(?:은\s*|이\s*)?없", t):
        p.surgery_history = ["없음"]
    else:
        surg = []
        for m in re.finditer(r"([가-힣A-Za-z]+?)\s*(?:수술|시술)", t):
            if m.group(1) not in ("이전", "과거", "예전"):
                surg.append(m.group(1) + " 수술")
        if "스텐트" in t and not any("스텐트" in s for s in surg):
            surg.append("심장 스텐트")
        p.surgery_history = surg

    # 발생 시각
    if m := _last(r"(\d{1,3})\s*분\s*전", t):
        p.onset_time = (now - timedelta(minutes=int(m.group(1)))).isoformat(timespec="minutes")
    elif m := _last(r"(\d{1,2})\s*시간\s*전", t):
        p.onset_time = (now - timedelta(hours=int(m.group(1)))).isoformat(timespec="minutes")
    elif m := _last(r"(\d{1,2})\s*시\s*(?:(\d{1,2})\s*분)?\s*(?:경|쯤|에)", t):
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if h < 12 and now.hour >= 12 and h + 12 <= now.hour:
            h += 12
        p.onset_time = now.replace(hour=h % 24, minute=mi, second=0, microsecond=0).isoformat(timespec="minutes")
    elif (m := _symptom_duration(t)) is not None:
        p.onset_time = (now - m).isoformat(timespec="minutes")
    elif p.cpr_minutes is not None:
        p.onset_time = (now - timedelta(minutes=p.cpr_minutes)).isoformat(timespec="minutes")
        p.extra["onset_estimated_from_cpr"] = True

    # 주증상
    if m := _last(r"흉통|가슴\s*(?:통증|아프)|호흡\s*곤란|의식\s*저하|마비|어지러|복통|두통|출혈|경련", t):
        p.chief_complaint = m.group()

    _fill_type_extras(p, t)
    return p


_STROKE_SIGNS = (r"편?마비|언어\s*장애|말\s*(?:이\s*)?어눌|발음\s*(?:이\s*)?어눌|구음\s*장애|구음|"
                 r"말을\s*못|힘\s*(?:이\s*)?빠|안면\s*비대칭")
_CPR_WORDS = re.compile(r"CPR|씨피알|심폐소생|가슴\s*압박", re.I)


def _symptom_duration(t: str) -> Optional[timedelta]:
    """"흉통 20분째" → 20분 전 발생. CPR 경과("CPR 5분째")는 제외."""
    for m in re.finditer(r"(\d{1,3})\s*(분|시간)\s*째", t):
        if _CPR_WORDS.search(t[max(0, m.start() - 15) : m.start()]):
            continue
        n = int(m.group(1))
        return timedelta(minutes=n) if m.group(2) == "분" else timedelta(hours=n)
    return None


_NEG_AFTER = re.compile(r"\s*(?:은|는|이|가)?\s*(?:아직\s*)?(?:없|안\s*(?:됨|돼|했|함)|미회복|불가)")


def _sign(pattern: str, t: str) -> Optional[bool]:
    """증상 언급 여부: 긍정 언급이 하나라도 있으면 True, 부정 언급만 있으면 False, 언급 없으면 None."""
    found = None
    for m in re.finditer(pattern, t, re.I):
        neg = _NEG_AFTER.match(t, m.end())
        if not neg:
            return True
        found = False
    return found


def _fill_type_extras(p: Patient, t: str) -> None:
    e = p.extra
    for key, pat in (("witnessed", r"목격(?:자)?"),
                     ("defibrillation", r"제세동|AED|전기\s*충격|쇼크"),
                     ("rosc", r"자발\s*순환(?:\s*회복)?|ROSC")):
        if (v := _sign(pat, t)) is not None:
            e[key] = v
    if m := _last(r"교통사고|추락|낙상|자상|총상|압궤|오토바이", t):
        e["mechanism"] = m.group()
        if h := _last(r"(\d{1,3})\s*(?:층|m|미터)", t):
            e["mechanism"] += f" ({h.group()})"
    if m := _last(r"(머리|두부|흉부|복부|골반|다리|팔|척추|목)\s*(?:손상|외상|골절|출혈|부상)", t):
        e["injury_site"] = m.group(1)
    if m := _last(r"(?:출혈|피)\s*(?:이\s*)?(많|심|조금|적|소량|다량)", t):
        e["bleeding"] = "다량" if m.group(1) in ("많", "심", "다량") else "소량"
    if _has(r"심전도|ECG|EKG|ST\s*상승", t):
        e["ecg_abnormal"] = not _has(r"(?:심전도|ECG|EKG)\s*(?:는\s*|은\s*)?(?:정상|이상\s*없)", t)
    if m := _last(r"마지막\s*(?:으로\s*)?정상\D{0,10}?(\d{1,3}\s*(?:분|시간)\s*전|\d{1,2}\s*시)", t):
        e["last_known_well"] = m.group(1)
    # "마비는 없고 말이 어눌함" → 언어장애가 있으므로 True
    if (v := _sign(_STROKE_SIGNS, t)) is not None:
        e["paralysis"] = v


def classify_emergency(p: Patient, text: str) -> None:
    t = _preprocess(text)
    if p.cpr or _has(r"심정지|심장\s*마비|맥박\s*(?:이\s*)?없|arrest", t):
        p.emergency_type = EmergencyType.CARDIAC_ARREST.value
    elif _has(r"사고|추락|낙상|전복|자상|찔림|총상|압궤|끼임|외상", t):
        p.emergency_type = EmergencyType.MAJOR_TRAUMA.value
    elif _has(r"흉통|가슴\s*(?:이\s*)?(?:통증|아프|조이|답답)|심근경색|ST\s*상승|심전도\s*이상(?!\s*없)", t):
        p.emergency_type = EmergencyType.MI.value
    elif _sign(_STROKE_SIGNS, t) or _has(r"뇌졸중|중풍|편측|극심한\s*두통|벼락\s*두통", t):
        p.emergency_type = EmergencyType.STROKE.value
    else:
        p.emergency_type = p.emergency_type or EmergencyType.OTHER.value

    if p.emergency_type in (EmergencyType.CARDIAC_ARREST.value, EmergencyType.MAJOR_TRAUMA.value):
        p.severity = Severity.CRITICAL.value
    elif (p.emergency_type in (EmergencyType.MI.value, EmergencyType.STROKE.value)
          or p.consciousness in ("무반응", "통증반응")
          or (p.gcs is not None and p.gcs <= 8)
          or (p.spo2 is not None and p.spo2 < 90)
          or _sys_bp(p) is not None and _sys_bp(p) < 90):
        p.severity = Severity.SEVERE.value
    else:
        p.severity = Severity.MILD.value


def _sys_bp(p: Patient) -> Optional[int]:
    if p.blood_pressure and "/" in p.blood_pressure:
        try:
            return int(p.blood_pressure.split("/")[0])
        except ValueError:
            return None
    return None


def sanity_check(p: Patient) -> list[str]:
    w = []
    if p.age is not None and not 0 <= p.age <= 120:
        w.append(f"나이 {p.age}세가 맞나요?")
    if p.blood_pressure and "/" in p.blood_pressure:
        s, d = (int(x) for x in p.blood_pressure.split("/"))
        if not (30 <= s <= 300 and 10 <= d <= 200 and d < s):
            w.append(f"혈압 {p.blood_pressure}이 맞나요?")
    if p.pulse is not None and not 0 <= p.pulse <= 250:
        w.append(f"맥박 {p.pulse}이 맞나요?")
    if p.spo2 is not None and not 0 <= p.spo2 <= 100:
        w.append(f"산소포화도 {p.spo2}이 맞나요?")
    if p.gcs is not None and not 3 <= p.gcs <= 15:
        w.append(f"GCS {p.gcs}가 맞나요?")
    if p.cpr_minutes is not None and p.cpr_minutes > 120:
        w.append(f"CPR {p.cpr_minutes}분째가 맞나요?")
    return w


def find_missing(p: Patient) -> tuple[list[str], list[str]]:
    missing, questions = [], []
    for key, q in COMMON_QUESTIONS.items():
        v = getattr(p, key)
        if v is None or v == []:
            # 심정지 무반응 환자는 의식 질문 불필요
            missing.append(key)
            questions.append(q)
    for key, q in TYPE_EXTRAS.get(p.emergency_type or "", []):
        if key not in p.extra:
            missing.append(key)
            questions.append(q)
    return missing, questions


LLM_SYSTEM = """너는 119 구급대원의 무전/음성 보고를 구조화하는 도우미다.
입력 문장에서 환자 정보를 추출해 JSON 하나만 출력한다. 말하지 않은 값은 null(리스트는 []).
정정 발언이 있으면 마지막 값을 쓴다. 숫자는 아라비아 숫자로. 추측하지 않는다.
키: age(int), sex("M"|"F"), consciousness("명료"|"언어반응"|"통증반응"|"무반응"), gcs(int),
cpr(bool), cpr_minutes(int), blood_pressure("수축/이완"), pulse(int), spo2(int),
chief_complaint(str), medications([str]), surgery_history([str]),
emergency_type("심정지"|"중증외상"|"급성심근경색"|"뇌졸중"|"기타"),
extra(object: witnessed, defibrillation, rosc, mechanism, injury_site, bleeding, ecg_abnormal, last_known_well, paralysis 중 언급된 것만)"""


def _merge(base: Patient, new: Patient) -> Patient:
    """new에서 값이 있는 항목만 base에 덮어쓴다 (되묻기 답변 병합에도 사용)."""
    d = base.to_dict()
    for k, v in new.to_dict().items():
        if k == "extra":
            d["extra"].update(v)
        elif v not in (None, []):
            d[k] = v
    return Patient.from_dict(d)


def extract(text: str, base: Optional[Patient] = None, use_llm: bool = True,
            now: Optional[datetime] = None) -> ExtractResult:
    """발화 → 환자 데이터. base를 주면 되묻기 답변을 기존 데이터에 병합한다."""
    p = extract_rules(text, now=now)
    client = get_client() if use_llm else None
    if client is not None:
        try:
            data = client.chat_json(LLM_SYSTEM, text)
            p = _merge(p, Patient.from_dict(data))
        except Exception as e:  # LLM 실패 시 규칙 결과로 계속 진행 (현장에서 멈추면 안 됨)
            p.extra["_llm_error"] = str(e)[:200]
    if base is not None:
        p = _merge(base, p)
    # 첫 발화에서 분류, 되묻기 답변에서는 기존 분류가 '기타'일 때만 다시 분류
    if base is None or base.emergency_type in (None, EmergencyType.OTHER.value):
        classify_emergency(p, text)
    missing, questions = find_missing(p)
    return ExtractResult(p, missing, questions, sanity_check(p))


if __name__ == "__main__":
    import sys
    r = extract(" ".join(sys.argv[1:]) or "70대 남자 의식 없고 CPR 5분째, 혈압 구십에 육십, 와파린 복용")
    print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
