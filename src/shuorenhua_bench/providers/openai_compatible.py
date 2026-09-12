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

    def __post_init__(self):
        if not self.system_id or not self.model or self.retries < 1 or self.timeout_seconds <= 0:
            raise ValueError("invalid provider identity, retries or timeout")
        if self.temperature < 0 or not 0 < self.top_p <= 1 or self.max_tokens < 1:
            raise ValueError("invalid decoding configuration")
        if not self.base_url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("use HTTPS or a local inference endpoint")


class OpenAICompatibleProvider:
    """Bounded retries, no retry on auth/client errors, no silent truncation."""

    def __init__(self, config: ProviderConfig):
        self.config = config

    def generate(self, *, system_prompt: str, user_prompt: str) -> tuple[str, dict[str, Any]]:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"missing API key environment variable: {self.config.api_key_env}")
        payload = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_prompt}],
            "temperature": self.config.temperature, "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
        }
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        started = time.monotonic()
        for attempt in range(self.config.retries):
            request = urllib.request.Request(
                self.config.base_url.rstrip("/") + "/chat/completions", data=encoded,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                         "User-Agent": "shuorenhua-bench/0.3"}, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt + 1 == self.config.retries:
                    raise RuntimeError(f"provider HTTP {exc.code}; response not recorded") from None
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                delay = min(float(retry_after), 60) if retry_after.isdigit() else 2**attempt
                time.sleep(delay)
                continue
            except urllib.error.URLError:
                if attempt + 1 == self.config.retries:
                    raise RuntimeError("provider connection failed; response not recorded") from None
                time.sleep(2**attempt)
                continue
            try:
                choice = body["choices"][0]
                content = choice["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("empty or non-text content")
                if choice.get("finish_reason") != "stop":
                    raise ValueError("completion did not finish normally")
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RuntimeError(f"invalid provider completion: {exc}") from None
            return content.strip(), {
                "provider_request_id": body.get("id"), "resolved_model": body.get("model"),
                "system_fingerprint": body.get("system_fingerprint"), "usage": body.get("usage", {}),
                "finish_reason": choice.get("finish_reason"), "attempts": attempt + 1,
                "latency_seconds": time.monotonic() - started,
            }
        raise RuntimeError("provider retry budget exhausted")
