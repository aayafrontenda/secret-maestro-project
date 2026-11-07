from typing import Any

from fastapi import APIRouter, Body, HTTPException, status

from app.api import serializers as ser
from app.api.deps import MLDep, SessionDep
from app.services import checklists as checklist_service
from app.services import simulation as simulation_service
from app.services.checklist_document import (
    DocumentError,
    document_to_checklist_in,
    load_default_document,
)

router = APIRouter(prefix="/checklists", tags=["checklists"])


@router.get("/active")
async def active_checklist(session: SessionDep):
    """The checklist document used for new evaluations (latest version)."""
    checklist = await checklist_service.ensure_default_checklist(session)
    doc = await checklist_service.current_document(session, checklist)
    await session.commit()
    return doc


@router.get("/active/versions")
async def checklist_versions(session: SessionDep):
    checklist = await checklist_service.ensure_default_checklist(session)
    await checklist_service.current_document(session, checklist)
    await session.commit()
    return [
        {
            "version": v.version,
            "name": v.name,
            "updated_at": v.document.get("updated_at") or ser.iso(v.created_at),
            "criteria": len(v.document.get("criteria", [])),
        }
        for v in await checklist_service.list_versions(session, checklist.id)
    ]


@router.get("/active/versions/{version}")
async def checklist_version(version: int, session: SessionDep):
    """A specific version's document (what an old evaluation was scored against)."""
    checklist = await checklist_service.ensure_default_checklist(session)
    doc = await checklist_service.get_version_document(session, checklist.id, version)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Версии v{version} нет")
    return doc


@router.put("/active")
async def save_checklist(session: SessionDep, body: dict[str, Any] = Body(...)):
    """Save the edited document as a new version (version + 1). Past evaluations keep theirs."""
    checklist = await checklist_service.ensure_default_checklist(session)
    try:
        data = document_to_checklist_in(body)
    except DocumentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(exc.errors)) from exc
    await checklist_service.update_checklist(session, checklist, data, document=body)
    doc = await checklist_service.current_document(session, checklist)
    await session.commit()
    return doc


@router.post("/active/simulate")
async def simulate_checklist(session: SessionDep, ml: MLDep, body: dict[str, Any] = Body(...)):
    """Dry run of a draft on already evaluated dialogs. Nothing is saved.

    Body: `{"document": <checklist document>, "limit": 10}`. Only criteria whose wording,
    type, scale or N/A rule changed are sent to the model; the rest of the answers are reused.
    """
    raw = body.get("document") if isinstance(body.get("document"), dict) else body
    try:
        data = document_to_checklist_in(raw)
    except DocumentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(exc.errors)) from exc
    checklist = await checklist_service.ensure_default_checklist(session)
    active = await checklist_service.snapshot(session, checklist)
    result = await simulation_service.simulate(
        session, checklist, active, raw, data, ml, limit=body.get("limit") or 10
    )
    await session.rollback()
    return result


@router.post("/active/reset")
async def reset_checklist(session: SessionDep):
    """New version from the original PDF checklist (data/checklist.default.json)."""
    checklist = await checklist_service.ensure_default_checklist(session)
    default = load_default_document()
    await checklist_service.update_checklist(
        session, checklist, document_to_checklist_in(default), document=default
    )
    doc = await checklist_service.current_document(session, checklist)
    await session.commit()
    return doc
