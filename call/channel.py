"""전화 채널.

실제 전화망 연동은 학교 내부망 제약으로 어려우므로(CLAUDE.md 10절),
시연은 SimulatedChannel: 학교 와이파이 안의 팀원 폰이 '병원' 역할을 한다.
- 팀원 폰(브라우저)이 /sim/inbox/{hospital_id} 를 폴링해 대본(TTS 음성)을 받고
- 응답을 녹음/입력해 /incidents/{id}/responses 로 보낸다.

⚠ 실제 병원 응급실 번호로 절대 발신하지 않는다. ALLOWED_PHONE_PREFIXES 이외 번호는 거부.
"""
from __future__ import annotations

import os
from collections import defaultdict, deque
from typing import Protocol

from schema import Hospital
from tts import get_tts


class PhoneChannel(Protocol):
    def dial(self, incident_id: str, hospital: Hospital, script: str) -> None: ...
    def hang_up(self, incident_id: str, hospital: Hospital) -> None: ...
    def send_sms(self, incident_id: str, hospital: Hospital, text: str) -> None: ...


def _check_number(phone: str) -> None:
    allowed = [p.strip() for p in os.getenv("ALLOWED_PHONES", "sim:").split(",") if p.strip()]
    if not any(phone.startswith(p) for p in allowed):
        raise PermissionError(f"허용되지 않은 번호입니다: {phone} (테스트는 팀원 폰/시뮬레이션만)")


class SimulatedChannel:
    def __init__(self):
        self.inbox: dict[str, deque] = defaultdict(deque)   # hospital_id → 메시지 큐
        self.tts = get_tts()

    def dial(self, incident_id: str, hospital: Hospital, script: str) -> None:
        _check_number(hospital.phone)
        audio = self.tts.synthesize(script)
        self.inbox[hospital.hospital_id].append(
            {"type": "call", "incident_id": incident_id, "script": script,
             "media_type": self.tts.media_type, "audio": audio})

    def hang_up(self, incident_id: str, hospital: Hospital) -> None:
        self.inbox[hospital.hospital_id].append({"type": "hang_up", "incident_id": incident_id})

    def send_sms(self, incident_id: str, hospital: Hospital, text: str) -> None:
        self.inbox[hospital.hospital_id].append({"type": "sms", "incident_id": incident_id, "text": text})

    def pop(self, hospital_id: str) -> list[dict]:
        q = self.inbox[hospital_id]
        out = list(q)
        q.clear()
        return out
