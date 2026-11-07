import json

import httpx
from fastapi import APIRouter, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import SessionDep, SettingsDep
from app.schemas.common import Page
from app.schemas.dialog import (
    DialogDetail,
    DialogIn,
    DialogSummary,
    EvaluationBrief,
    ImportRequest,
    ImportResult,
)
from app.services import dialogs as dialog_service
from app.services.organizer import OrganizerError, fetch_dataset, parse_dataset

router = APIRouter(prefix="/dialogs", tags=["dialogs"])


@router.get("", response_model=Page[DialogSummary])
async def list_dialogs(
    session: SessionDep,
    channel: str | None = Query(default=None, description='"agent chat" or "voice call"'),
    language: str | None = Query(default=None, description="RU | KZ | EN"),
    group_id: str | None = None,
    q: str | None = Query(default=None, description="Substring match on conversation_id"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    rows, total, latest = await dialog_service.list_dialogs(
        session,
        channel=channel,
        language=language,
        group_id=group_id,
        q=q,
        limit=limit,
        offset=offset,
    )
    items = []
    for d in rows:
        item = DialogSummary.model_validate(d)
        if d.id in latest:
            item.latest_evaluation = EvaluationBrief.model_validate(latest[d.id])
        items.append(item)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{dialog_id}", response_model=DialogDetail)
async def get_dialog(dialog_id: str, session: SessionDep):
    d = await dialog_service.get_dialog(session, dialog_id, with_evaluations=True)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dialog not found")
    detail = DialogDetail.model_validate(d)
    evaluations = sorted(d.evaluations, key=lambda e: e.id, reverse=True)
    detail.evaluations = [EvaluationBrief.model_validate(e) for e in evaluations]
    detail.latest_evaluation = detail.evaluations[0] if detail.evaluations else None
    return detail


@router.post("", response_model=ImportResult, status_code=status.HTTP_201_CREATED)
async def upload_dialogs(payload: DialogIn | list[DialogIn], session: SessionDep):
    """Manually upload one dialog or a list of dialogs (organizer record format)."""
    records = payload if isinstance(payload, list) else [payload]
    created, updated, ids = await dialog_service.upsert_dialogs(
        session, records, source="manual", dataset_group_id=None
    )
    await session.commit()
    return ImportResult(
        dataset_group_id=None, received=len(records), created=created, updated=updated, ids=ids
    )


@router.post("/import", response_model=ImportResult)
async def import_from_organizer(body: ImportRequest, session: SessionDep, settings: SettingsDep):
    """Fetch a dataset from the organizer API by group_id and store it."""
    if not settings.organizer_api_url:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ORGANIZER_API_URL is not configured; use POST /dialogs/import-file instead",
        )
    try:
        dataset = await fetch_dataset(
            settings.organizer_api_url, body.group_id, settings.organizer_api_timeout_s
        )
    except OrganizerError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    group = dataset.dataset_group_id or body.group_id
    created, updated, ids = await dialog_service.upsert_dialogs(
        session, dataset.records, source="organizer_api", dataset_group_id=group
    )
    await session.commit()
    return ImportResult(
        dataset_group_id=group,
        received=len(dataset.records),
        created=created,
        updated=updated,
        ids=ids,
    )


@router.post("/import-file", response_model=ImportResult)
async def import_from_file(file: UploadFile, session: SessionDep):
    """Upload the organizer's JSON response (e.g. invoke.json) as a file."""
    raw = await file.read()
    try:
        dataset = parse_dataset(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid JSON file: {exc}"
        ) from exc
    except OrganizerError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    created, updated, ids = await dialog_service.upsert_dialogs(
        session, dataset.records, source="file", dataset_group_id=dataset.dataset_group_id
    )
    await session.commit()
    return ImportResult(
        dataset_group_id=dataset.dataset_group_id,
        received=len(dataset.records),
        created=created,
        updated=updated,
        ids=ids,
    )


@router.delete("/{dialog_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dialog(dialog_id: str, session: SessionDep):
    d = await dialog_service.get_dialog(session, dialog_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dialog not found")
    await session.delete(d)
    await session.commit()


@router.get("/{dialog_id}/audio")
async def stream_audio(dialog_id: str, session: SessionDep):
    """Proxy the call recording so the browser can play it without CORS issues."""
    d = await dialog_service.get_dialog(session, dialog_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dialog not found")
    if not d.audio_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dialog has no recording")

    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=600.0), follow_redirects=True)
    try:
        req = client.build_request("GET", d.audio_url)
        upstream = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"could not fetch recording: {exc}"
        ) from exc
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"recording source returned {upstream.status_code}"
        )

    async def body():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    headers = {}
    for h in ("content-type", "content-length", "accept-ranges"):
        if h in upstream.headers:
            headers[h] = upstream.headers[h]
    headers.setdefault("content-type", "audio/mpeg")
    return StreamingResponse(body(), headers=headers)
