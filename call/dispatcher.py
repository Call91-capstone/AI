"""발신·묶음 호출·취소 로직 (CLAUDE.md 5절).

시간은 모두 인자로 받는다(now: 초 단위 float) → 스레드·타이머 없이 테스트 가능.
API 서버는 주기적으로 tick(now)를 호출하고, 간호사 응답이 오면 on_response()를 호출한다.

규칙
- 중증도별 묶음: 최중증 3곳→30초마다 +2 / 중증 2곳→60초마다 +2 / 경증 1곳씩 순차
- 진행 중인 통화(발신 중·의사 확인 중)가 하나도 없으면 시간과 상관없이 다음 묶음 즉시 호출
- '의사 확인 중'은 콜백 제한 시간 동안 기다리되, 그동안 다음 묶음 호출은 계속
- 수락 확정: 먼저 확정한 병원. 같은 tick 안에 여러 곳 수락 시 도착 예상 시간이 짧은 곳
- 확정 후 나머지 병원은 즉시 AI 취소 연락
- 직접 전화: 그 병원은 AI 발신 즉시 중단(중복 통화 금지), 결과는 구급대원이 탭으로 기록
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from llm.classify import classify
from llm.script import CANCEL_OPENING, build_script, build_sms
from schema import CallResult, CallStatus, Hospital, Patient, Severity

from .channel import PhoneChannel


@dataclass(frozen=True)
class BatchPolicy:
    first: int
    step: int
    interval_sec: Optional[float]   # None = 시간 기반 확장 없음(순차)


POLICIES = {
    Severity.CRITICAL.value: BatchPolicy(3, 2, 30),
    Severity.SEVERE.value: BatchPolicy(2, 2, 60),
    Severity.MILD.value: BatchPolicy(1, 1, None),
}

MAX_CONCURRENT = 5             # 동시에 진행 중인 통화(발신 중 + 의사 확인 중) 최대 수 (중간발표 5곳 동시 호출 기준)
RING_TIMEOUT_SEC = 40          # 발신 후 응답 없으면 무응답
DOCTOR_CALLBACK_SEC = 180      # 의사 확인 콜백 제한 시간
ACTIVE = {CallStatus.DIALING.value, CallStatus.DOCTOR_CHECKING.value}
FINAL = {CallStatus.REJECTED.value, CallStatus.NO_ANSWER.value, CallStatus.CANCELLED.value}


@dataclass
class HospitalCall:
    hospital: Hospital
    status: str = CallStatus.PENDING.value
    started_at: Optional[float] = None
    updated_at: Optional[float] = None
    reject_reason: Optional[str] = None
    transcripts: list[str] = field(default_factory=list)

    def result(self, now: float) -> CallResult:
        return CallResult(
            hospital_id=self.hospital.hospital_id,
            status=self.status,
            reject_reason=self.reject_reason,
            transcript=self.transcripts[-1] if self.transcripts else None,
            elapsed_sec=round(now - self.started_at, 1) if self.started_at is not None else None,
        )


class Dispatcher:
    def __init__(self, incident_id: str, patient: Patient, hospitals: list[Hospital],
                 channel: PhoneChannel, on_event: Optional[Callable[[str, CallResult], None]] = None):
        self.incident_id = incident_id
        self.patient = patient
        self.calls = [HospitalCall(h) for h in hospitals]   # server가 정렬해서 준 순서 유지
        self.channel = channel
        self.on_event = on_event or (lambda incident_id, r: None)
        self.policy = POLICIES.get(patient.severity or "", POLICIES[Severity.SEVERE.value])
        self.started_at: Optional[float] = None
        self.last_batch_at: Optional[float] = None
        self.confirmed: Optional[str] = None
        self.log: list[dict] = []     # 통화·전달 기록 (분쟁 시 근거)

    # ---------- 조회 ----------
    def _get(self, hospital_id: str) -> HospitalCall:
        for c in self.calls:
            if c.hospital.hospital_id == hospital_id:
                return c
        raise KeyError(hospital_id)

    def state(self, now: Optional[float] = None) -> dict:
        now = now if now is not None else time.time()
        return {
            "incident_id": self.incident_id,
            "confirmed_hospital_id": self.confirmed,
            "elapsed_sec": round(now - self.started_at, 1) if self.started_at is not None else 0,
            "hospitals": [{**c.result(now).to_dict(), "name": c.hospital.name} for c in self.calls],
        }

    # ---------- 내부 ----------
    def _set(self, c: HospitalCall, status: str, now: float, reason: Optional[str] = None) -> None:
        c.status, c.updated_at, c.reject_reason = status, now, reason
        r = c.result(now)
        self.log.append({"t": now, **r.to_dict()})
        self.on_event(self.incident_id, r)

    def _dial(self, c: HospitalCall, now: float) -> None:
        script = build_script(self.patient, c.hospital.eta_min)
        c.started_at = now
        self._set(c, CallStatus.DIALING.value, now)
        self.channel.dial(self.incident_id, c.hospital, script)

    def _dial_next(self, n: int, now: float) -> int:
        # 동시 통화는 최대 5곳: 거절·무응답으로 자리가 나면 그만큼만 다음 병원에 건다
        n = min(n, MAX_CONCURRENT - len(self._active()))
        dialed = 0
        for c in self.calls:
            if dialed >= n:
                break
            if c.status == CallStatus.PENDING.value:
                self._dial(c, now)
                dialed += 1
        if dialed:
            self.last_batch_at = now
        return dialed

    def _active(self) -> list[HospitalCall]:
        return [c for c in self.calls if c.status in ACTIVE]

    def _confirm(self, c: HospitalCall, now: float) -> None:
        self.confirmed = c.hospital.hospital_id
        self.channel.send_sms(self.incident_id, c.hospital, build_sms(self.patient))
        for other in self.calls:
            if other is c:
                continue
            if other.status in ACTIVE:
                self.channel.dial(self.incident_id, other.hospital, CANCEL_OPENING)
            if other.status in ACTIVE | {CallStatus.PENDING.value}:
                self._set(other, CallStatus.CANCELLED.value, now)

    # ---------- 공개 API ----------
    def start(self, now: Optional[float] = None) -> None:
        now = now if now is not None else time.time()
        self.started_at = now
        self._dial_next(self.policy.first, now)

    def on_response(self, hospital_id: str, text: Optional[str], now: Optional[float] = None) -> CallResult:
        """간호사 응답(STT 결과 텍스트) 처리."""
        now = now if now is not None else time.time()
        c = self._get(hospital_id)
        if self.confirmed or c.status not in ACTIVE:
            return c.result(now)      # 이미 끝난 통화의 늦은 응답은 무시
        if text:
            c.transcripts.append(text)
        r = classify(text)
        self._set(c, r.status, now, r.reject_reason)
        if r.status == CallStatus.ACCEPTED.value:
            self._confirm(c, now)
        else:
            self.tick(now)
        return c.result(now)

    def on_responses(self, items: list[tuple[str, Optional[str]]], now: Optional[float] = None) -> None:
        """같은 시점에 들어온 여러 응답: 수락이 둘 이상이면 도착 예상 시간이 짧은 곳으로 확정."""
        now = now if now is not None else time.time()
        accepted = []
        for hid, text in items:
            c = self._get(hid)
            if self.confirmed or c.status not in ACTIVE:
                continue
            if text:
                c.transcripts.append(text)
            r = classify(text)
            if r.status == CallStatus.ACCEPTED.value:
                accepted.append(c)
                c.status = CallStatus.ACCEPTED.value
            else:
                self._set(c, r.status, now, r.reject_reason)
        if accepted:
            best = min(accepted, key=lambda c: c.hospital.eta_min if c.hospital.eta_min is not None else 1e9)
            for c in accepted:
                if c is not best:
                    c.status = CallStatus.DIALING.value   # _confirm에서 취소 처리됨
            self._set(best, CallStatus.ACCEPTED.value, now)
            self._confirm(best, now)
        else:
            self.tick(now)

    def tick(self, now: Optional[float] = None) -> None:
        """타임아웃 처리 + 다음 묶음 호출. API 서버가 1초마다 호출."""
        now = now if now is not None else time.time()
        if self.confirmed or self.started_at is None:
            return
        for c in self.calls:
            if c.status == CallStatus.DIALING.value and c.started_at is not None \
                    and now - c.started_at >= RING_TIMEOUT_SEC:
                self._set(c, CallStatus.NO_ANSWER.value, now)
            elif c.status == CallStatus.DOCTOR_CHECKING.value and c.updated_at is not None \
                    and now - c.updated_at >= DOCTOR_CALLBACK_SEC:
                self._set(c, CallStatus.NO_ANSWER.value, now, "의사 확인 콜백 시간 초과")
        p = self.policy
        if not self._active():
            # 걸어 둔 곳이 전부 거절·무응답 → 기다리지 않고 남은 병원에 최대 5곳까지 한 번에
            # (경증은 그대로 1곳씩 순차)
            self._dial_next(MAX_CONCURRENT if p.interval_sec is not None else p.step, now)
        elif p.interval_sec is not None and self.last_batch_at is not None and now - self.last_batch_at >= p.interval_sec:
            self._dial_next(p.step, now)

    def direct_call(self, hospital_id: str, now: Optional[float] = None) -> None:
        """구급대원이 '직접 전화' 누름 → 해당 병원 AI 통화 즉시 중단."""
        now = now if now is not None else time.time()
        c = self._get(hospital_id)
        if c.status == CallStatus.DIALING.value:
            self.channel.hang_up(self.incident_id, c.hospital)
        if c.started_at is None:
            c.started_at = now
        self._set(c, CallStatus.DIRECT.value, now)

    def record_direct_result(self, hospital_id: str, status: str, reason: Optional[str] = None,
                             now: Optional[float] = None) -> None:
        now = now if now is not None else time.time()
        c = self._get(hospital_id)
        self._set(c, status, now, reason)
        if status == CallStatus.ACCEPTED.value and not self.confirmed:
            self._confirm(c, now)
        else:
            self.tick(now)
