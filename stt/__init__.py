"""음성 → 텍스트. 구급대원 입력과 간호사 응답에 **같은 모델**을 재사용한다.

STT_BACKEND (.env)
- "text"    (기본) 오디오 대신 텍스트를 그대로 통과 → 집에서 GPU 없이 파이프라인 테스트
- "whisper" faster-whisper (H100). STT_MODEL=large-v3 등

잡음 제거: STT_DENOISE=1 이면 noisereduce로 사이렌·엔진음 감쇠 후 인식.
의료 용어 힌트: Whisper initial_prompt 로 전달 (llm.extract.STT_HINTS).
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Optional, Protocol


class STT(Protocol):
    def transcribe(self, audio: bytes, hints: Optional[str] = None) -> str: ...


class TextPassthroughSTT:
    """시뮬레이션용: 바이트를 UTF-8 텍스트로 간주."""

    def transcribe(self, audio: bytes, hints: Optional[str] = None) -> str:
        return audio.decode("utf-8", errors="ignore").strip()


class WhisperSTT:
    def __init__(self, model: str = "large-v3", device: str = "cuda", denoise: bool = False):
        from faster_whisper import WhisperModel  # 지연 import: GPU 없는 환경에서도 패키지 로드 가능

        self.model = WhisperModel(model, device=device, compute_type="float16" if device == "cuda" else "int8")
        self.denoise = denoise

    def transcribe(self, audio: bytes, hints: Optional[str] = None) -> str:
        from .denoise import load_audio, reduce_noise

        wav, sr = load_audio(audio)
        if self.denoise:
            wav = reduce_noise(wav, sr)
        segments, _ = self.model.transcribe(
            wav, language="ko", initial_prompt=hints, vad_filter=True, beam_size=5,
        )
        return " ".join(s.text.strip() for s in segments).strip()


@lru_cache(maxsize=1)
def get_stt() -> STT:
    backend = os.getenv("STT_BACKEND", "text")
    if backend == "whisper":
        return WhisperSTT(
            model=os.getenv("STT_MODEL", "large-v3"),
            device=os.getenv("STT_DEVICE", "cuda"),
            denoise=os.getenv("STT_DENOISE", "0") == "1",
        )
    return TextPassthroughSTT()


__all__ = ["STT", "TextPassthroughSTT", "WhisperSTT", "get_stt", "io"]
