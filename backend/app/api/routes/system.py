from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import MLDep, QueueDep, SessionDep, SettingsDep

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(session: SessionDep, settings: SettingsDep, ml: MLDep, queue: QueueDep):
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "ml": {
            "provider": ml.name,
            "model": getattr(ml, "model", None),
            "reachable": await ml.health(),
            "pii_masking": getattr(ml, "masks_pii", None),
        },
        "llm_insights": settings.llm_configured,
        "queue": queue.stats(),
        "environment": settings.environment,
    }


@router.get("/queue")
async def queue_stats(queue: QueueDep):
    return queue.stats()
