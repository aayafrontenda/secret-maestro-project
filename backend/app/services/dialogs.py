from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Dialog, Evaluation
from app.schemas.dialog import DialogIn
from app.services import handoff


def normalize_transcript(messages: Iterable) -> list[dict]:
    out = []
    for i, m in enumerate(messages):
        data = m.model_dump() if hasattr(m, "model_dump") else dict(m)
        out.append(
            {
                "index": i,
                "timestamp": str(data.get("timestamp", "")),
                "speaker": data["speaker"],
                "text": data["text"],
            }
        )
    return out


async def upsert_dialogs(
    session: AsyncSession,
    records: list[DialogIn],
    *,
    source: str,
    dataset_group_id: str | None,
) -> tuple[int, int, list[str]]:
    """Insert or replace dialogs by conversation_id. Returns (created, updated, ids)."""
    ids = [r.conversation_id for r in records]
    existing = {
        d.id: d for d in (await session.scalars(select(Dialog).where(Dialog.id.in_(ids)))).all()
    }
    created = updated = 0
    for r in records:
        transcript = normalize_transcript(r.transcript)
        d = existing.get(r.conversation_id)
        if d is None:
            d = Dialog(id=r.conversation_id)
            session.add(d)
            created += 1
        else:
            updated += 1
        changed = d.transcript != transcript or d.channel != r.channel
        d.channel = r.channel
        d.language = r.language
        d.transcript = transcript
        d.message_count = len(transcript)
        d.audio_url = r.audio_url
        d.source = source
        d.dataset_group_id = dataset_group_id
        if changed or d.handoff_source is None:
            handoff.refresh(d)
    await session.flush()
    return created, updated, ids


async def get_dialog(
    session: AsyncSession, dialog_id: str, *, with_evaluations: bool = False
) -> Dialog | None:
    stmt = select(Dialog).where(Dialog.id == dialog_id)
    if with_evaluations:
        stmt = stmt.options(selectinload(Dialog.evaluations))
    return await session.scalar(stmt)


async def list_dialogs(
    session: AsyncSession,
    *,
    channel: str | None = None,
    language: str | None = None,
    group_id: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Dialog], int, dict[str, Evaluation]]:
    stmt = select(Dialog)
    if channel:
        stmt = stmt.where(Dialog.channel == channel)
    if language:
        stmt = stmt.where(Dialog.language == language.upper())
    if group_id:
        stmt = stmt.where(Dialog.dataset_group_id == group_id)
    if q:
        stmt = stmt.where(Dialog.id.ilike(f"%{q}%"))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await session.scalars(stmt.order_by(Dialog.id).limit(limit).offset(offset))).all()

    latest: dict[str, Evaluation] = {}
    if rows:
        ids = [d.id for d in rows]
        ev_stmt = (
            select(Evaluation)
            .where(Evaluation.dialog_id.in_(ids))
            .order_by(Evaluation.dialog_id, Evaluation.id.desc())
        )
        for ev in (await session.scalars(ev_stmt)).all():
            latest.setdefault(ev.dialog_id, ev)
    return list(rows), total, latest


def transcript_fragment(transcript: list[dict], indexes: list[int], context: int = 2) -> list[dict]:
    """Messages around the given indexes (used by the reviewer view)."""
    if not transcript:
        return []
    if not indexes:
        return transcript[: min(len(transcript), 2 * context + 1)]
    lo = max(0, min(indexes) - context)
    hi = min(len(transcript) - 1, max(indexes) + context)
    return transcript[lo : hi + 1]
