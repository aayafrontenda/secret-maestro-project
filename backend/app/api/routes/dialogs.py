from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import serializers as ser
from app.api.deps import SessionDep
from app.models import Appeal, Dialog, Evaluation
from app.models.appeal import AppealStatus
from app.models.evaluation import EvaluationStatus
from app.services import dialogs as dialog_service
from app.services import evaluations as evaluation_service
from app.services.audio import resolve_audio

router = APIRouter(prefix="/dialogs", tags=["dialogs"])


async def _get_or_404(session: AsyncSession, dialog_id: str) -> Dialog:
    d = await dialog_service.get_dialog(session, dialog_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Диалог {dialog_id} не найден")
    return d


async def latest_completed(session: AsyncSession, dialog_ids: list[str]) -> dict[str, Evaluation]:
    if not dialog_ids:
        return {}
    stmt = (
        select(Evaluation)
        .where(
            Evaluation.dialog_id.in_(dialog_ids),
            Evaluation.status == EvaluationStatus.completed,
        )
        .order_by(Evaluation.dialog_id, Evaluation.id.desc())
    )
    latest: dict[str, Evaluation] = {}
    for ev in (await session.scalars(stmt)).all():
        latest.setdefault(ev.dialog_id, ev)
    return latest


async def _appeal_counts(
    session: AsyncSession, evaluation_ids: list[int]
) -> dict[int, tuple[int, int]]:
    if not evaluation_ids:
        return {}
    stmt = (
        select(Appeal.evaluation_id, Appeal.status, func.count())
        .where(Appeal.evaluation_id.in_(evaluation_ids))
        .group_by(Appeal.evaluation_id, Appeal.status)
    )
    counts: dict[int, tuple[int, int]] = {}
    for ev_id, st, n in (await session.execute(stmt)).all():
        open_n, total_n = counts.get(ev_id, (0, 0))
        if st == AppealStatus.pending:
            open_n += n
        counts[ev_id] = (open_n, total_n + n)
    return counts


@router.get("")
async def list_dialogs(
    session: SessionDep,
    channel: str | None = Query(default=None, description='"agent chat" | "voice call"'),
    language: str | None = Query(default=None, description="RU | KZ | EN"),
    group_id: str | None = None,
):
    """Rows for the dialog list: latest completed score, checklist version, appeal counters."""
    stmt = select(Dialog).order_by(Dialog.id)
    if channel:
        stmt = stmt.where(Dialog.channel == channel)
    if language:
        stmt = stmt.where(Dialog.language == language.upper())
    if group_id:
        stmt = stmt.where(Dialog.dataset_group_id == group_id)
    dialogs = list((await session.scalars(stmt)).all())
    latest = await latest_completed(session, [d.id for d in dialogs])
    counts = await _appeal_counts(session, [ev.id for ev in latest.values()])
    rows = []
    for d in dialogs:
        ev = latest.get(d.id)
        open_n, total_n = counts.get(ev.id, (0, 0)) if ev else (0, 0)
        rows.append(ser.dialog_row(d, ev, open_n, total_n))
    return rows


@router.get("/{dialog_id}")
async def get_dialog(dialog_id: str, session: SessionDep):
    """The dialog in the organizer's record format (transcript as received)."""
    return ser.dialog_record(await _get_or_404(session, dialog_id))


@router.delete("/{dialog_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dialog(dialog_id: str, session: SessionDep):
    """Remove a dialog with its evaluations and appeals."""
    d = await _get_or_404(session, dialog_id)
    await session.delete(d)
    await session.commit()


@router.get("/{dialog_id}/evaluation")
async def latest_evaluation(dialog_id: str, session: SessionDep):
    """Latest completed evaluation for the dialog, or 404 (the UI then starts one)."""
    await _get_or_404(session, dialog_id)
    ev = (await latest_completed(session, [dialog_id])).get(dialog_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Диалог ещё не оценён")
    full = await evaluation_service.get_evaluation(session, ev.id)
    return ser.evaluation(full)  # type: ignore[arg-type]


@router.get("/{dialog_id}/evaluations")
async def evaluation_history(dialog_id: str, session: SessionDep):
    """All evaluations of the dialog, newest first (including in-progress and failed)."""
    await _get_or_404(session, dialog_id)
    rows, _ = await evaluation_service.list_evaluations(session, dialog_id=dialog_id, limit=500)
    return [ser.evaluation_brief(ev) for ev in rows]


@router.get("/{dialog_id}/audio")
async def get_audio(dialog_id: str, session: SessionDep):
    """Direct media link for a voice call, extracted from the organizer's player page."""
    d = await _get_or_404(session, dialog_id)
    if not d.audio_url:
        return {"url": None, "player_url": None, "expires_at": None}
    resolved = await resolve_audio(d.audio_url)
    return {
        "url": resolved.url,
        "player_url": resolved.player_url,
        "stream_url": f"/api/dialogs/{dialog_id}/audio/stream",
        "expires_at": (
            ser.iso(datetime.fromtimestamp(resolved.expires_at, UTC)) if resolved.url else None
        ),
    }


@router.get("/{dialog_id}/audio/stream")
async def stream_audio(dialog_id: str, session: SessionDep):
    """Proxy the recording bytes through the backend (fallback if the direct link is blocked)."""
    d = await _get_or_404(session, dialog_id)
    if not d.audio_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "У диалога нет записи")
    resolved = await resolve_audio(d.audio_url)
    if not resolved.url:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Не удалось получить ссылку на запись")

    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=600.0), follow_redirects=True)
    try:
        upstream = await client.send(client.build_request("GET", resolved.url), stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Запись недоступна: {exc}") from exc
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Источник записи ответил {upstream.status_code}"
        )

    async def body():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    headers = {
        h: upstream.headers[h]
        for h in ("content-type", "content-length", "accept-ranges")
        if h in upstream.headers
    }
    headers.setdefault("content-type", "audio/mpeg")
    return StreamingResponse(body(), headers=headers)
