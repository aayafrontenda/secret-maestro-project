import json

from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import func, select

from app.api.deps import SessionDep, SettingsDep
from app.models import Dialog
from app.services.results_export import build_results, validate

router = APIRouter(prefix="/results", tags=["results"])


@router.get("")
async def results(
    session: SessionDep,
    settings: SettingsDep,
    group_id: str | None = Query(default=None, description="Dataset group, e.g. DEV; all if empty"),
    team: str | None = Query(default=None, description="team_name; TEAM_NAME by default"),
    mode: str | None = Query(default=None, pattern="^(local|external_api|hybrid)$"),
    model: str | None = Query(default=None, description="model.name; detected by default"),
    download: bool = False,
):
    """results.json in the organizers' format 1.0: one entry per dialog of the set."""
    doc = await build_results(
        session,
        group_id=group_id,
        team_name=team or settings.team_name,
        mode=mode,
        model_name=model,
    )
    if not download:
        return doc
    return Response(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="results.json"'},
    )


@router.get("/check")
async def check(
    session: SessionDep,
    settings: SettingsDep,
    group_id: str | None = None,
    expected: int | None = Query(default=None, ge=0),
):
    """Validate the export against the appendix rules before committing it."""
    doc = await build_results(session, group_id=group_id, team_name=settings.team_name)
    statuses = [r["status"] for r in doc["results"]]
    return {
        "group_id": group_id,
        "records": len(statuses),
        "ok": statuses.count("ok"),
        "errors": statuses.count("error"),
        "model": doc["model"],
        "problems": validate(doc, expected),
        "not_evaluated": [r["conversation_id"] for r in doc["results"] if r["status"] == "error"],
    }


@router.get("/groups")
async def groups(session: SessionDep):
    """Dataset groups with dialog counts, for the export picker."""
    rows = (
        await session.execute(
            select(Dialog.dataset_group_id, func.count())
            .group_by(Dialog.dataset_group_id)
            .order_by(Dialog.dataset_group_id)
        )
    ).all()
    return [{"group_id": g, "dialogs": n} for g, n in rows]
