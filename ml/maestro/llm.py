"""LLM client interface and the local Ollama implementation."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

# On 19 hand-labelled DEV dialogs (before the ml/openai-comparison rule changes): qwen3.5:9b agreed
# with the labels on 82.2% of answers at about 24 s per dialog; qwen3.5:4b on 71.1% at about 14 s
# (RTX 4070 Laptop, 8 GB).
DEFAULT_MODEL = "qwen3.5:9b"
MAX_NUM_CTX = 32768
MAX_NUM_PREDICT = 1536  # ceiling when an answer is cut off and the request is repeated with a larger limit
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

    # think: per-call override of the thinking mode; None keeps the client's setting.
    def complete(self, system: str, user: str, schema: dict[str, Any], think: bool | None = None) -> LLMResponse: ...


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


OPTIONAL_PARAMS = ("temperature", "seed", "reasoning_effort")


def _rejected_param(response: httpx.Response) -> str | None:
    """Which optional parameter a 400 complains about. OpenAI sets error.param; the Gemini
    OpenAI-compatible endpoint wraps the error in a list and names the field only in the message."""
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, list):
        body = body[0] if body else {}
    error = body.get("error") or {} if isinstance(body, dict) else {}
    if error.get("param") in OPTIONAL_PARAMS:
        return error["param"]
    message = str(error.get("message", ""))
    return next((name for name in OPTIONAL_PARAMS if f'"{name}"' in message or f"'{name}'" in message), None)


class OpenAIClient:
    """OpenAI Chat Completions with JSON-schema output. Same interface as OllamaClient.

    Used to compare cloud models with the local ones on the same pipeline; the key comes from
    OPENAI_API_KEY and is never written anywhere.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        url: str = "https://api.openai.com/v1",
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
        seed: int = 42,
        timeout: float = 120,
    ):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.url = url.rstrip("/")
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.seed = seed
        self.http = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {self.api_key}"})
        # Parameters this model rejected; dropped from later requests.
        self._unsupported: set[str] = set()

    @classmethod
    def from_env(cls, **overrides: Any) -> "OpenAIClient":
        settings: dict[str, Any] = {
            "model": os.getenv("MAESTRO_OPENAI_MODEL", "gpt-4.1-mini"),
            "url": os.getenv("MAESTRO_OPENAI_URL", "https://api.openai.com/v1"),
            "reasoning_effort": os.getenv("MAESTRO_OPENAI_REASONING") or None,
            "timeout": float(os.getenv("MAESTRO_TIMEOUT", "120")),
        }
        settings.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**settings)

    def health(self) -> dict[str, Any]:
        if not self.api_key:
            return {"ok": False, "model": self.model, "error": "OPENAI_API_KEY is not set"}
        try:
            response = self.http.get(f"{self.url}/models/{self.model}", timeout=10)
        except httpx.HTTPError as exc:
            return {"ok": False, "model": self.model, "error": f"OpenAI is not reachable: {exc}"}
        if response.is_error:
            return {"ok": False, "model": self.model, "error": f"{response.status_code}: {response.text[:200]}"}
        return {"ok": True, "model": self.model}

    def _payload(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema, "strict": False}},
            "max_completion_tokens": self.max_tokens,
            "temperature": 0,
            "seed": self.seed,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        for key in self._unsupported:
            payload.pop(key, None)
        return payload

    def complete(self, system: str, user: str, schema: dict[str, Any], think: bool | None = None) -> LLMResponse:
        # Per-call thinking is not mapped for OpenAI: reasoning models always reason at
        # reasoning_effort (MAESTRO_OPENAI_REASONING), other models never do.
        started = time.perf_counter()
        last_error = ""
        delays = iter((*RETRY_DELAYS, 30.0))
        while True:
            payload = self._payload(system, user, schema)
            try:
                response = self.http.post(f"{self.url}/chat/completions", json=payload)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 400:
                    param = _rejected_param(response)
                    # Drop a parameter the model rejects (e.g. reasoning models accept only the default
                    # temperature). Checked against this payload, so parallel calls all retry correctly.
                    if param in OPTIONAL_PARAMS and param in payload:
                        self._unsupported.add(param)
                        continue
                    raise LLMUnavailable(f"OpenAI rejected the request (400): {response.text[:300]}")
                if response.status_code in (401, 402, 403, 404):  # 402: credits depleted, retrying will not help
                    raise LLMUnavailable(f"OpenAI rejected the request ({response.status_code}): {response.text[:300]}")
                if response.status_code < 400:
                    data = response.json()
                    choice = data["choices"][0]
                    if choice.get("finish_reason") == "length":
                        raise LLMOutputError("response was cut off by the token limit")
                    usage = data.get("usage") or {}
                    return LLMResponse(
                        content=choice["message"].get("content") or "",
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                    )
                last_error = f"{response.status_code}: {response.text[:300]}"  # 429 or 5xx: wait and retry
            delay = next(delays, None)
            if delay is None:
                raise LLMUnavailable(f"OpenAI request failed: {last_error}")
            time.sleep(delay)


class OllamaClient:
    def __init__(
        self,
        model: str,
        url: str = "http://127.0.0.1:11434",
        num_ctx: int = 8192,
        num_predict: int = 384,
        think: bool = False,
        think_predict: int = 4096,
        seed: int = 42,
        timeout: float = 300,
        num_gpu: int | None = None,
    ):
        self.model = model
        self.url = url.rstrip("/")
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.think = think
        self.think_predict = think_predict
        self.seed = seed
        self.num_gpu = num_gpu
        self.http = httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls, **overrides: Any) -> "OllamaClient":
        settings: dict[str, Any] = {
            "model": os.getenv("MAESTRO_MODEL", DEFAULT_MODEL),
            "url": os.getenv("MAESTRO_OLLAMA_URL", "http://127.0.0.1:11434"),
            "num_ctx": int(os.getenv("MAESTRO_NUM_CTX", "8192")),
            "num_predict": int(os.getenv("MAESTRO_NUM_PREDICT", "384")),
            "think": os.getenv("MAESTRO_THINK", "false").lower() == "true",
            "think_predict": int(os.getenv("MAESTRO_THINK_PREDICT", "4096")),
            "seed": int(os.getenv("MAESTRO_SEED", "42")),
            "timeout": float(os.getenv("MAESTRO_TIMEOUT", "300")),
            "num_gpu": int(os.environ["MAESTRO_NUM_GPU"]) if os.getenv("MAESTRO_NUM_GPU") else None,
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

    def _request(self, system: str, user: str, schema: dict[str, Any], num_ctx: int, think: bool, num_predict: int) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "think": think,
            "format": schema,
            "keep_alive": -1,  # keep the model in GPU memory; reloading it takes about a minute
            "options": {
                "temperature": 0,
                "seed": self.seed,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        }
        if self.num_gpu is not None:
            # Ollama's own estimate can leave a layer on the CPU even when the model fits in VRAM.
            # Every request must carry the same value, or Ollama reloads the model.
            payload["options"]["num_gpu"] = self.num_gpu
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

    def complete(self, system: str, user: str, schema: dict[str, Any], think: bool | None = None) -> LLMResponse:
        started = time.perf_counter()
        think = self.think if think is None else think
        # Thinking text counts against num_predict; give it room or the answer gets cut off.
        num_predict = self.num_predict if not think else max(self.num_predict, self.think_predict)
        # Start from a window sized to the prompt. Russian and Kazakh text runs at about 2 characters
        # per token for qwen3.5 (measured: 13,621 characters -> 6,847 tokens).
        estimate = (len(system) + len(user)) // 2 + num_predict + 256
        num_ctx = min(max(self.num_ctx, estimate), MAX_NUM_CTX)
        while True:
            data = self._request(system, user, schema, num_ctx, think, num_predict)
            prompt_tokens = data.get("prompt_eval_count")
            # Ollama silently drops the start of a prompt that does not fit, so a prompt
            # that fills the context window is treated as truncated and sent again.
            truncated = prompt_tokens is not None and prompt_tokens + num_predict >= num_ctx
            if truncated and num_ctx < MAX_NUM_CTX:
                num_ctx = min(num_ctx * 2, MAX_NUM_CTX)
                continue
            # A long answer (the generic evaluator writes reasoning and an explanation) can outgrow
            # num_predict; the same request with a larger limit is deterministic, so retry it once larger.
            if not truncated and data.get("done_reason") == "length" and num_predict < MAX_NUM_PREDICT:
                num_predict = min(num_predict * 2, MAX_NUM_PREDICT)
                num_ctx = min(max(num_ctx, (prompt_tokens or 0) + num_predict + 256), MAX_NUM_CTX)
                continue
            break
        if truncated:
            raise LLMOutputError(f"prompt does not fit into {MAX_NUM_CTX} tokens of context")
        # Ollama reloads the model whenever num_ctx changes, so keep a window once it has grown
        # instead of switching back and forth between dialogs of different length.
        self.num_ctx = max(self.num_ctx, num_ctx)
        if data.get("done_reason") == "length":
            raise LLMOutputError("response was cut off by the token limit")
        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            duration_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=prompt_tokens,
            completion_tokens=data.get("eval_count"),
        )


def client_from_env() -> "LLMClient":
    """The main client: MAESTRO_BACKEND=ollama (default) or openai (OpenAI or any OpenAI-compatible API)."""
    if os.getenv("MAESTRO_BACKEND", "ollama").lower() == "openai":
        return OpenAIClient.from_env()
    return OllamaClient.from_env()


def generic_client_from_env() -> "LLMClient | None":
    """Optional separate model for criteria without built-in rules (the generic evaluator).

    MAESTRO_GENERIC_MODEL names it; MAESTRO_GENERIC_URL and MAESTRO_GENERIC_API_KEY default to the
    OpenAI settings. Unset: the main client scores those criteria too.
    """
    model = os.getenv("MAESTRO_GENERIC_MODEL")
    if not model:
        return None
    return OpenAIClient(
        model=model,
        api_key=os.getenv("MAESTRO_GENERIC_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
        url=os.getenv("MAESTRO_GENERIC_URL") or os.getenv("MAESTRO_OPENAI_URL", "https://api.openai.com/v1"),
        reasoning_effort=os.getenv("MAESTRO_GENERIC_REASONING") or None,
    )


def check_client_from_env() -> "LLMClient | None":
    """Optional second model for the cascade check (MAESTRO_CHECK_MODEL). Unset: no check.

    MAESTRO_CHECK_BACKEND=openai (default, any OpenAI-compatible API) or ollama;
    MAESTRO_CHECK_URL / MAESTRO_CHECK_API_KEY default to the OpenAI settings.
    """
    model = os.getenv("MAESTRO_CHECK_MODEL")
    if not model:
        return None
    if os.getenv("MAESTRO_CHECK_BACKEND", "openai").lower() == "ollama":
        return OllamaClient.from_env(model=model, url=os.getenv("MAESTRO_CHECK_URL") or None)
    return OpenAIClient(
        model=model,
        api_key=os.getenv("MAESTRO_CHECK_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
        url=os.getenv("MAESTRO_CHECK_URL") or os.getenv("MAESTRO_OPENAI_URL", "https://api.openai.com/v1"),
        reasoning_effort=os.getenv("MAESTRO_CHECK_REASONING") or None,
    )
