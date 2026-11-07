import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.db import dispose_engine, get_session_factory
from app.core.logging import setup_logging
from app.core.migrations import run_migrations
from app.ml import build_ml_client
from app.services.checklists import ensure_default_checklist
from app.services.queue import EvaluationQueue

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
        app.state.ml = build_ml_client(settings)
        app.state.queue = EvaluationQueue(
            session_factory, app.state.ml, workers=settings.queue_workers
        )
        await app.state.queue.start()
        log.info(
            "%s started (ml=%s, workers=%d)",
            settings.app_name,
            app.state.ml.name,
            settings.queue_workers,
        )
        try:
            yield
        finally:
            await app.state.queue.stop()
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

    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    async def root():
        return {"service": settings.app_name, "docs": "/docs", "api": "/api/v1"}

    return app


app = create_app()
