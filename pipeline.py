"""AI 음성 통합 파이프라인 (CLAUDE.md 3절).

[입력] 구급대원 음성 → (잡음 제거) STT → LLM 추출·분류 → 되묻기
[발신] 확인된 환자 데이터 → 대본 → TTS → 묶음 호출
[응답] 간호사 음성 → STT → LLM 분류 → 상태 갱신 → server 통보
STT·LLM·TTS는 입력과 발신 양쪽에서 같은 인스턴스를 재사용한다 (get_stt/get_tts/get_client 캐시).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
import uuid
from typing import Optional

from call import Dispatcher, SimulatedChannel
from llm.extract import STT_HINTS, ExtractResult, extract
from schema import CallResult, Hospital, Patient
from stt import get_stt


def _post_to_server(incident_id: str, result: CallResult) -> None:
    """server(Spring)로 통화 결과 전달. SERVER_CALLBACK_URL 미설정 시 생략."""
    url = os.getenv("SERVER_CALLBACK_URL")   # 예: http://localhost:8080/api/incidents/{incident_id}/calls
    if not url:
        return
    body = json.dumps(result.to_dict(), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url.format(incident_id=incident_id), data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")

    def send():
        try:
            urllib.request.urlopen(req, timeout=5).close()
        except Exception as e:
            print(f"[server 통보 실패] {incident_id} {result.hospital_id}: {e}")

    threading.Thread(target=send, daemon=True).start()


class VoicePipeline:
    def __init__(self):
        self.channel = SimulatedChannel()
        self.incidents: dict[str, Dispatcher] = {}
        self.lock = threading.Lock()

    # ----- 입력 -----
    def intake_text(self, text: str, base: Optional[Patient] = None) -> ExtractResult:
        return extract(text, base=base)

    def intake_audio(self, audio: bytes, base: Optional[Patient] = None) -> tuple[str, ExtractResult]:
        text = get_stt().transcribe(audio, hints=STT_HINTS)
        return text, extract(text, base=base)

    # ----- 발신 -----
    def start_incident(self, patient: Patient, hospitals: list[Hospital]) -> Dispatcher:
        incident_id = uuid.uuid4().hex[:8]
        d = Dispatcher(incident_id, patient, hospitals, self.channel, on_event=_post_to_server)
        with self.lock:
            self.incidents[incident_id] = d
            d.start(time.time())
        return d

    # ----- 응답 -----
    def respond_text(self, incident_id: str, hospital_id: str, text: Optional[str]) -> CallResult:
        with self.lock:
            return self.incidents[incident_id].on_response(hospital_id, text, time.time())

    def respond_audio(self, incident_id: str, hospital_id: str, audio: bytes) -> CallResult:
        text = get_stt().transcribe(audio, hints="수용, 가능, 불가, 병상, 당직, 의사 선생님 확인")
        return self.respond_text(incident_id, hospital_id, text)

    def tick_all(self) -> None:
        now = time.time()
        with self.lock:
            for d in self.incidents.values():
                d.tick(now)
