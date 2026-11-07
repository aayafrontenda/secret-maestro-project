import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import BACKEND_ROOT, Settings, get_settings
from app.core.db import dispose_engine, get_session_factory
from app.core.logging import setup_logging
from app.core.migrations import run_migrations
from app.ml import build_llm_chat, build_ml_clients
from app.services import handoff
from app.services.checklists import ensure_default_checklist
from app.services.queue import EvaluationQueue


class RevalidatedStaticFiles(StaticFiles):
    """The frontend changes during the demo: browsers and the Cloudflare edge must check for a new
    version on every load (a cheap 304 when nothing changed) instead of serving a stale copy for hours."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_migrations(settings.database_url)
        session_factory = get_session_factory()
        if settings.seed_default_checklist:
            async with session_factory() as session:
                await ensure_default_checklist(session)
                await session.commit()
        async with session_factory() as session:
            if await handoff.backfill(session):
                await session.commit()
        app.state.llm_chat = build_llm_chat(settings)
        # One local GPU cannot serve the evaluation model and handoff analysis at once
        # (Ollama falls over): local calls of both go through the same lock.
        chat_local = bool(app.state.llm_chat and app.state.llm_chat.is_local)
        gate = asyncio.Lock() if chat_local else None
        app.state.ml = build_ml_clients(settings, app.state.llm_chat, gate)
        app.state.queue = EvaluationQueue(
            session_factory, app.state.ml, workers=settings.queue_workers
        )
        await app.state.queue.start()
        app.state.handoff = handoff.HandoffAnalyzer(
            session_factory,
            app.state.llm_chat,
            mask=settings.pii_masking,
            language=settings.output_language,
            concurrency=1 if chat_local else 4,
            gate=gate,
        )
        log.info(
            "%s started (ml=%s, workers=%d)",
            settings.app_name,
            app.state.ml.name,
            settings.queue_workers,
        )
        try:
            yield
        finally:
            await app.state.handoff.stop()
            await app.state.queue.stop()
            if app.state.llm_chat:
                await app.state.llm_chat.aclose()
            await app.state.ml.aclose()
            await dispose_engine()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Conversation Quality Analytics: checklist configuration, "
            "automatic evaluation, appeals and review."
        ),
        lifespan=lifespan,
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Errors carry both keys: "detail" (FastAPI convention) and "error" (what the UI reads).
    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, exc: HTTPException):
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": message, "detail": exc.detail},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        errors = exc.errors()
        parts = []
        for e in errors:
            loc = ".".join(str(x) for x in e.get("loc", []) if x != "body")
            parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
        safe = [{k: v for k, v in e.items() if k != "ctx"} for e in errors]
        return JSONResponse(
            status_code=422,
            content={"error": "; ".join(parts) or "invalid request", "detail": safe},
        )

    app.include_router(api_router)

    frontend = Path(settings.frontend_dir or BACKEND_ROOT.parent / "frontend")
    if settings.serve_frontend and (frontend / "index.html").is_file():
        # Mounted last, so /api and /docs win; everything else is the static frontend.
        app.mount("/", RevalidatedStaticFiles(directory=frontend, html=True), name="frontend")
        log.info("serving frontend from %s", frontend)
    else:

        @app.get("/", include_in_schema=False)
        async def root():
            return {"service": settings.app_name, "docs": "/docs", "api": "/api"}

    return app


app = create_app()
