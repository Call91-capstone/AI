"""AI API 서버 (포트 8000). server(Spring)·시뮬레이션 폰과만 통신한다.

실행:  uvicorn api:app --host 0.0.0.0 --port 8000
문서:  http://<서버>:8000/docs
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from pipeline import VoicePipeline
from schema import CallStatus, Hospital, Patient

pipe = VoicePipeline()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def ticker():
        while True:
            pipe.tick_all()
            await asyncio.sleep(1)

    task = asyncio.create_task(ticker())
    yield
    task.cancel()


app = FastAPI(title="119 AI 음성 수용문의", lifespan=lifespan)


class IntakeText(BaseModel):
    text: str
    base: Optional[dict[str, Any]] = None     # 되묻기 답변이면 기존 환자 데이터


class StartIncident(BaseModel):
    patient: dict[str, Any]                   # 구급대원이 확인·수정한 환자 데이터
    hospitals: list[dict[str, Any]]           # server가 정렬한 병원 목록


class Response(BaseModel):
    hospital_id: str
    text: Optional[str] = None                # None/빈 문자열 = 무응답


class DirectResult(BaseModel):
    status: str
    reject_reason: Optional[str] = None


def _incident(incident_id: str):
    d = pipe.incidents.get(incident_id)
    if d is None:
        raise HTTPException(404, "incident 없음")
    return d


@app.get("/health")
def health():
    return {"ok": True}


# ---------- 입력: 구급대원 ----------
@app.post("/intake/text")
def intake_text(body: IntakeText):
    base = Patient.from_dict(body.base) if body.base else None
    return pipe.intake_text(body.text, base).to_dict()


@app.post("/intake/audio")
async def intake_audio(request: Request):
    """본문: 오디오 바이트(WAV). Push-to-talk 한 번 = 요청 한 번."""
    text, r = pipe.intake_audio(await request.body())
    return {"transcript": text, **r.to_dict()}


# ---------- 발신 ----------
@app.post("/incidents")
def start_incident(body: StartIncident):
    try:
        d = pipe.start_incident(Patient.from_dict(body.patient), [Hospital.from_dict(h) for h in body.hospitals])
    except PermissionError as e:
        raise HTTPException(400, str(e))
    return d.state()


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str):
    return _incident(incident_id).state()


# ---------- 응답: 간호사 ----------
@app.post("/incidents/{incident_id}/responses")
def respond(incident_id: str, body: Response):
    _incident(incident_id)
    return pipe.respond_text(incident_id, body.hospital_id, body.text).to_dict()


@app.post("/incidents/{incident_id}/responses/{hospital_id}/audio")
async def respond_audio(incident_id: str, hospital_id: str, request: Request):
    _incident(incident_id)
    return pipe.respond_audio(incident_id, hospital_id, await request.body()).to_dict()


# ---------- 직접 전화 모드 ----------
@app.post("/incidents/{incident_id}/direct/{hospital_id}")
def direct_call(incident_id: str, hospital_id: str):
    d = _incident(incident_id)
    with pipe.lock:
        d.direct_call(hospital_id)
    return d.state()


@app.post("/incidents/{incident_id}/direct/{hospital_id}/result")
def direct_result(incident_id: str, hospital_id: str, body: DirectResult):
    if body.status not in {s.value for s in CallStatus}:
        raise HTTPException(400, "status 값 오류")
    d = _incident(incident_id)
    with pipe.lock:
        d.record_direct_result(hospital_id, body.status, body.reject_reason)
    return d.state()


# ---------- 시뮬레이션 폰 (팀원 폰 = 병원) ----------
@app.get("/sim/inbox/{hospital_id}")
def sim_inbox(hospital_id: str):
    msgs = pipe.channel.pop(hospital_id)
    for m in msgs:
        if "audio" in m:
            m["audio"] = base64.b64encode(m["audio"]).decode()
    return msgs
