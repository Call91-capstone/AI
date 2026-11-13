"""텍스트 → 음성.

TTS_BACKEND (.env)
- "text" (기본) 음성 없이 텍스트만 → 시뮬레이션 화면에 대본을 띄우는 방식
- "melo" MeloTTS 한국어 (H100, 오프라인 동작). TTS_SPEED=1.1 등

반환값: WAV 바이트 (text 백엔드는 UTF-8 텍스트 바이트)
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Protocol


class TTS(Protocol):
    media_type: str

    def synthesize(self, text: str) -> bytes: ...


class TextOnlyTTS:
    media_type = "text/plain; charset=utf-8"

    def synthesize(self, text: str) -> bytes:
        return text.encode("utf-8")


class MeloTTS:
    media_type = "audio/wav"

    def __init__(self, device: str = "cuda", speed: float = 1.1):
        from melo.api import TTS as _Melo  # 지연 import

        self.model = _Melo(language="KR", device=device)
        self.speaker = self.model.hps.data.spk2id["KR"]
        self.speed = speed

    def synthesize(self, text: str) -> bytes:
        import soundfile as sf

        wav = self.model.tts_to_file(text, self.speaker, None, speed=self.speed, quiet=True)
        buf = io.BytesIO()
        sf.write(buf, wav, self.model.hps.data.sampling_rate, format="WAV")
        return buf.getvalue()


@lru_cache(maxsize=1)
def get_tts() -> TTS:
    if os.getenv("TTS_BACKEND", "text") == "melo":
        return MeloTTS(device=os.getenv("TTS_DEVICE", "cuda"), speed=float(os.getenv("TTS_SPEED", "1.1")))
    return TextOnlyTTS()
