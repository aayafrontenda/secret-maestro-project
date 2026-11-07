"""LLM client interface and the local Ollama implementation."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

MAX_NUM_CTX = 32768
RETRY_DELAYS = (2.0, 10.0)  # seconds between attempts on 5xx or connection errors


class LLMUnavailable(RuntimeError):
    """The backend cannot be reached or rejected the request. Retrying the same prompt will not help."""


class LLMOutputError(ValueError):
    """The model answered, but the answer is unusable. Retrying may help."""


@dataclass(frozen=True)
class LLMResponse:
    content: str
    duration_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse: ...


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating code fences or text around it."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise LLMOutputError(f"response is not JSON: {text[:200]!r}") from None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMOutputError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise LLMOutputError("response is not a JSON object")
    return value


class OllamaClient:
    def __init__(
        self,
        model: str,
        url: str = "http://127.0.0.1:11434",
        num_ctx: int = 8192,
        num_predict: int = 384,
        think: bool = False,
        seed: int = 42,
        timeout: float = 300,
    ):
        self.model = model
        self.url = url.rstrip("/")
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.think = think
        self.seed = seed
        self.http = httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls, **overrides: Any) -> "OllamaClient":
        settings: dict[str, Any] = {
            "model": os.getenv("MAESTRO_MODEL", "qwen3.5:4b"),
            "url": os.getenv("MAESTRO_OLLAMA_URL", "http://127.0.0.1:11434"),
            "num_ctx": int(os.getenv("MAESTRO_NUM_CTX", "8192")),
            "num_predict": int(os.getenv("MAESTRO_NUM_PREDICT", "384")),
            "think": os.getenv("MAESTRO_THINK", "false").lower() == "true",
            "seed": int(os.getenv("MAESTRO_SEED", "42")),
            "timeout": float(os.getenv("MAESTRO_TIMEOUT", "300")),
        }
        settings.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**settings)

    def health(self) -> dict[str, Any]:
        try:
            response = self.http.get(f"{self.url}/api/tags", timeout=3)
            response.raise_for_status()
            names = [item.get("name") for item in response.json().get("models", [])]
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "model": self.model, "error": f"Ollama is not reachable: {exc}"}
        if self.model not in names:
            return {"ok": False, "model": self.model, "error": f"model is not installed; available: {names}"}
        return {"ok": True, "model": self.model}

    def _request(self, system: str, user: str, schema: dict[str, Any], num_ctx: int) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "think": self.think,
            "format": schema,
            "options": {
                "temperature": 0,
                "seed": self.seed,
                "num_ctx": num_ctx,
                "num_predict": self.num_predict,
            },
        }
        last_error = ""
        for delay in (*RETRY_DELAYS, None):
            try:
                response = self.http.post(f"{self.url}/api/chat", json=payload)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code < 500:
                    if response.is_error:
                        raise LLMUnavailable(f"Ollama rejected the request ({response.status_code}): {response.text[:300]}")
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise LLMUnavailable(f"Ollama returned invalid JSON: {exc}") from exc
                # A 5xx usually means the model runner crashed; Ollama restarts it on the next request.
                last_error = f"{response.status_code}: {response.text[:300]}"
            if delay is None:
                break
            time.sleep(delay)
        raise LLMUnavailable(f"Ollama request failed after {len(RETRY_DELAYS) + 1} attempts: {last_error}")

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        started = time.perf_counter()
        # Start from a window sized to the prompt (about 3 characters per token).
        estimate = (len(system) + len(user)) // 3 + self.num_predict + 256
        num_ctx = min(max(self.num_ctx, estimate), MAX_NUM_CTX)
        while True:
            data = self._request(system, user, schema, num_ctx)
            prompt_tokens = data.get("prompt_eval_count")
            # Ollama silently drops the start of a prompt that does not fit, so a prompt
            # that fills the context window is treated as truncated and sent again.
            truncated = prompt_tokens is not None and prompt_tokens + self.num_predict >= num_ctx
            if not truncated or num_ctx >= MAX_NUM_CTX:
                break
            num_ctx = min(num_ctx * 2, MAX_NUM_CTX)
        if truncated:
            raise LLMOutputError(f"prompt does not fit into {MAX_NUM_CTX} tokens of context")
        if data.get("done_reason") == "length":
            raise LLMOutputError("response was cut off by the token limit")
        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            duration_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=prompt_tokens,
            completion_tokens=data.get("eval_count"),
        )
