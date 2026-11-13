# AI — 119 응급환자 수용문의 AI 음성

구급대원 음성 → 환자 데이터 → 병원용 대본·TTS → 묶음 호출 → 간호사 응답 분류 → server 통보.
자세한 배경·규칙은 [CLAUDE.md](CLAUDE.md).

```
AI/
├── api.py         # FastAPI 서버 (포트 8000)
├── pipeline.py    # STT·LLM·TTS·호출 통합 (모델 1회 로드, 입력·응답 공용)
├── stt/           # 음성 → 텍스트 (faster-whisper) + denoise.py 잡음 제거
├── tts/           # 텍스트 → 음성 (MeloTTS 한국어)
├── llm/
│   ├── client.py      # OpenAI 호환(vLLM) 클라이언트, 없으면 규칙 기반
│   ├── korean_num.py  # "구십에 육십" → 90/60
│   ├── extract.py     # 발화 → 환자 데이터, 4대 상황 분류, 되묻기, 이상값 경고
│   ├── script.py      # 환자 데이터 → 병원용 대본 / 요약 문자
│   └── classify.py    # 간호사 응답 → 수락/거절+사유/의사 확인 중/무응답
├── call/
│   ├── dispatcher.py  # 중증도별 묶음 호출, 타임아웃, 수락 확정·취소, 직접 전화
│   └── channel.py     # 시뮬레이션 전화(팀원 폰), 실제 번호 차단
├── schema/        # 팀 공유 데이터 형식 (Patient, CallResult, Hospital)
└── tests/         # unittest (GPU 없이 실행)
```

## 실행

집(GPU 없음) — 규칙 기반 + 텍스트 모드, 외부 패키지 불필요:
```bash
python -m unittest discover tests -v
```
```bash
python -m llm.extract "70대 남자 의식 없고 CPR 5분째 혈압 구십에 육십"
```

API 서버:
```bash
pip install -r requirements.txt
```
```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

H100 — `.env.example`을 `.env`로 복사 후 `STT_BACKEND=whisper`, `TTS_BACKEND=melo`, `LLM_BASE_URL` 설정, `pip install -r requirements-gpu.txt`.

## API 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/intake/text` | `{text, base?}` → 환자 데이터 + 되묻기 질문 + 경고 |
| POST | `/intake/audio` | WAV 바이트 → 위와 같음 + `transcript` |
| POST | `/incidents` | `{patient, hospitals}` → 묶음 호출 시작 |
| GET | `/incidents/{id}` | 병원별 상태 (앱 배지용) |
| POST | `/incidents/{id}/responses` | `{hospital_id, text}` 간호사 응답 |
| POST | `/incidents/{id}/responses/{hid}/audio` | 간호사 응답 음성 |
| POST | `/incidents/{id}/direct/{hid}` | 직접 전화 → 해당 병원 AI 중단 |
| POST | `/incidents/{id}/direct/{hid}/result` | 직접 통화 결과 기록 |
| GET | `/sim/inbox/{hid}` | 시뮬레이션 폰이 대본·음성·문자 수신 |

상태 변화는 `SERVER_CALLBACK_URL`로 server에 POST된다.

## 안전 규칙
- 실제 병원 번호로 발신 금지 — `ALLOWED_PHONES` 접두사 외 번호는 `PermissionError`
- 가짜 환자 데이터만, `.env`는 커밋 금지
