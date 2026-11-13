"""오디오 로드 + 잡음 제거 (구급차 사이렌·엔진·장비음).

의존성: numpy, soundfile, noisereduce (requirements-gpu.txt)
더 강한 모델(DeepFilterNet 등)로 바꿀 때는 reduce_noise만 교체하면 된다.
"""
from __future__ import annotations

import io

TARGET_SR = 16000


def load_audio(audio: bytes):
    import numpy as np
    import soundfile as sf

    wav, sr = sf.read(io.BytesIO(audio), dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    if sr != TARGET_SR:
        # 간단한 선형 보간 리샘플 (정확도가 필요하면 librosa/torchaudio로 교체)
        n = int(len(wav) * TARGET_SR / sr)
        wav = np.interp(np.linspace(0, len(wav), n, endpoint=False), np.arange(len(wav)), wav).astype("float32")
        sr = TARGET_SR
    return wav, sr


def reduce_noise(wav, sr: int):
    import noisereduce as nr

    # 사이렌은 비정상(non-stationary) 잡음 → stationary=False
    return nr.reduce_noise(y=wav, sr=sr, stationary=False, prop_decrease=0.85)
