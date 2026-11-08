import asyncio
import logging

import httpx
from pydantic import ValidationError

from app.ml.base import MLClientError
from app.ml.schemas import (
    MLEvaluateRequest,
    MLEvaluateResponse,
    MLSuggestRequest,
    MLSuggestResponse,
)

log = logging.getLogger(__name__)


class HttpMLClient:
    """Calls the ML team's service: POST {base_url}/evaluate."""

    name = "http"

    def __init__(self, base_url: str, timeout_s: float = 180.0, max_retries: int = 2) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s)
        self._max_retries = max(0, max_retries)

    async def evaluate(self, request: MLEvaluateRequest) -> MLEvaluateResponse:
        payload = request.model_dump(mode="json")
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.post("/evaluate", json=payload)
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning("ML request failed (attempt %d): %s", attempt + 1, exc)
            else:
                if resp.status_code >= 500:
                    last_exc = MLClientError(
                        f"ML service error {resp.status_code}: {resp.text[:500]}"
                    )
                    log.warning("ML service 5xx (attempt %d): %s", attempt + 1, resp.status_code)
                elif resp.status_code >= 400:
                    raise MLClientError(
                        f"ML service rejected request {resp.status_code}: {resp.text[:500]}"
                    )
                else:
                    try:
                        return MLEvaluateResponse.model_validate(resp.json())
                    except (ValueError, ValidationError) as exc:
                        raise MLClientError(
                            f"ML service returned an invalid response: {exc}"
                        ) from exc
            if attempt < self._max_retries:
                await asyncio.sleep(min(2**attempt, 8))
        raise MLClientError(
            f"ML service unavailable after {self._max_retries + 1} attempts: {last_exc}"
        )

    async def suggest(self, request: MLSuggestRequest) -> MLSuggestResponse:
        """One attempt: the user is waiting on the dialog card and can press the button again."""
        try:
            resp = await self._client.post("/suggest", json=request.model_dump(mode="json"))
        except httpx.HTTPError as exc:
            raise MLClientError(f"ML service unavailable: {exc}") from exc
        if resp.status_code >= 400:
            raise MLClientError(f"ML service error {resp.status_code}: {resp.text[:500]}")
        try:
            return MLSuggestResponse.model_validate(resp.json())
        except (ValueError, ValidationError) as exc:
            raise MLClientError(f"ML service returned an invalid response: {exc}") from exc

    async def status(self) -> tuple[bool, str | None]:
        """Reachable, and the model the service answers with now (its /health reports it).

        The service may run Qwen locally or a cloud model, and falls back to Qwen when the cloud is
        down, so the name is asked each time rather than configured here.
        """
        try:
            resp = await self._client.get("/health", timeout=5.0)
        except httpx.HTTPError:
            return False, None
        try:
            model = resp.json().get("model")
        except (ValueError, AttributeError):
            model = None
        return resp.status_code < 500, model if isinstance(model, str) and model else None

    async def health(self) -> bool:
        return (await self.status())[0]

    async def aclose(self) -> None:
        await self._client.aclose()
