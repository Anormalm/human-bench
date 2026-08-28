from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderConfig:
    system_id: str
    model: str
    base_url: str
    api_key_env: str
    temperature: float = 0.2
    top_p: float = 1.0
    max_tokens: int = 512
    timeout_seconds: float = 90.0
    retries: int = 3


class OpenAICompatibleProvider:
    """Small, dependency-free client for OpenAI-compatible chat-completion APIs."""

    def __init__(self, config: ProviderConfig):
        self.config = config

    def generate(self, *, system_prompt: str, user_prompt: str) -> tuple[str, dict[str, Any]]:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"missing API key environment variable: {self.config.api_key_env}")
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
        }
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(self.config.retries):
            request = urllib.request.Request(
                endpoint,
                data=encoded,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "shuorenhua-bench/0.2",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                text = body["choices"][0]["message"]["content"].strip()
                if not text:
                    raise RuntimeError("provider returned an empty response")
                return text, {
                    "provider_request_id": body.get("id"),
                    "usage": body.get("usage", {}),
                    "finish_reason": body["choices"][0].get("finish_reason"),
                }
            except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError) as exc:
                last_error = exc
                if attempt + 1 < self.config.retries:
                    time.sleep(2**attempt)
        raise RuntimeError(f"generation failed after {self.config.retries} attempts: {last_error}")

