"""HTTP service for the backend: POST /evaluate, POST /suggest and GET /health (backend/docs/ml-contract.md).

Run it with `uv run maestro serve` (port 8001 by default).
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .contract import EvaluateRequest, EvaluateResponse, evaluate
from .ingest import IngestError
from .llm import (
    FallbackClient,
    LLMClient,
    LLMOutputError,
    LLMUnavailable,
    client_from_env,
    generic_client_from_env,
)
from .suggest import SuggestRequest, SuggestResponse, suggest

log = logging.getLogger("maestro")


def create_app(
    client_factory: Callable[[], LLMClient] = client_from_env,
    generic_factory: Callable[[], LLMClient | None] = generic_client_from_env,
) -> FastAPI:
    app = FastAPI(title="MAESTRO ML service", version="0.2.0")
    llm = client_factory()
    generic_llm = generic_factory()
    if generic_llm is not None:
        # A cloud model that is down or out of credit must not fail evaluations: Qwen takes over.
        generic_llm = FallbackClient(generic_llm, llm)
    # One GPU: run model calls one chat at a time. The backend's workers simply wait here.
    gpu = threading.Lock()

    @app.get("/health")
    def health() -> JSONResponse:
        status = llm.health() if hasattr(llm, "health") else {"ok": True, "model": llm.model}
        return JSONResponse(status, status_code=200 if status["ok"] else 503)

    @app.post("/evaluate", response_model=EvaluateResponse)
    def evaluate_dialog(request: EvaluateRequest) -> EvaluateResponse:
        if not request.transcript:
            raise HTTPException(422, "transcript is empty")
        if not request.criteria:
            raise HTTPException(422, "criteria list is empty")
        with gpu:
            try:
                response = evaluate(request, llm, generic_llm)
            except IngestError as exc:
                raise HTTPException(422, str(exc)) from exc
            except LLMUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            except LLMOutputError as exc:
                # The backend retries 5xx; a fresh attempt usually gets a usable answer.
                raise HTTPException(502, f"model gave no usable answer: {exc}") from exc
        log.info(
            "%s: %d criteria, %d calls, %.1fs",
            request.conversation_id, len(response.results), response.usage.calls, response.duration_ms / 1000,
        )
        return response

    @app.post("/suggest", response_model=SuggestResponse)
    def suggest_reply(request: SuggestRequest) -> SuggestResponse:
        """The operator message that would have met a failed criterion (asked from the dialog card)."""
        if not request.transcript:
            raise HTTPException(422, "transcript is empty")
        # Writing a reply is open-ended text: a stronger generic model, when configured, writes it better.
        writer = generic_llm or llm
        with gpu:
            try:
                response = suggest(request, writer)
            except LLMUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            except LLMOutputError as exc:
                raise HTTPException(502, f"model gave no usable answer: {exc}") from exc
        log.info("%s: suggestion for %s, %.1fs", request.conversation_id, request.criterion.code, response.duration_ms / 1000)
        return response

    return app
