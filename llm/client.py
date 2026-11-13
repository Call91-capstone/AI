"""LLM 백엔드.

H100 서버에서 vLLM 등 OpenAI 호환 서버를 띄우고 LLM_BASE_URL로 연결한다.
LLM_BASE_URL이 없으면 None을 돌려주고, 각 모듈은 규칙 기반으로 동작한다
(집에서 GPU 없이 개발·테스트 가능).

.env 예:
    LLM_BASE_URL=http://localhost:8001/v1
    LLM_MODEL=Qwen/Qwen2.5-32B-Instruct
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Optional


class LLMClient:
    def __init__(self, base_url: str, model: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def chat_json(self, system: str, user: str) -> dict:
        text = self.chat(system, user, json_mode=True)
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start : end + 1])


def get_client() -> Optional[LLMClient]:
    url = os.getenv("LLM_BASE_URL")
    if not url:
        return None
    return LLMClient(url, os.getenv("LLM_MODEL", "default"))
