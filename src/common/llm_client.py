from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests


@dataclass
class LLMConfig:
    model: str = None
    base_url: str = None
    api_key: str | None = None
    api_key_file: Path | None = None
    timeout_seconds: int = 180


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig):
        self.config = config
        self.config.base_url = os.environ.get("OPENAI_BASE_URL", self.config.base_url)
        self.api_key = config.api_key or os.environ.get("OPENAI_API_KEY") or self._read_key_file(config.api_key_file)
        if not self.api_key:
            raise ValueError("Missing API key. Set OPENAI_API_KEY or pass --api-key-file.")

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        last_error = None
        for _ in range(3):
            try:
                response = requests.post(
                    f"{self._api_base()}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(2)
        raise RuntimeError(f"LLM request failed: {last_error}")

    def _api_base(self) -> str:
        base_url = self.config.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            return base_url
        return f"{base_url}/v1"

    @staticmethod
    def _read_key_file(path: Path | None) -> str | None:
        if path is None or not path.exists():
            return None
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        first = lines[0]
        if " " in first:
            return first.split()[-1]
        try:
            data = json.loads(first)
            return data.get("api_key")
        except json.JSONDecodeError:
            return first
