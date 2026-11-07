import asyncio

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api import serializers as ser
from app.api.deps import QueueDep, SessionDep, SettingsDep
from app.models import Dialog, Evaluation
from app.models.appeal import AppealStatus
from app.models.evaluation import EvaluationStatus
from app.services import checklists as checklist_service
from app.services import dialogs as dialog_service
from app.services import evaluations as evaluation_service

router = APIRouter(prefix="/evaluations", tags=["evaluations"])

# Serialises "find in-flight or create" per dialog so concurrent clicks share one evaluation.
_locks: dict[str, asyncio.Lock] = {}


class EvaluateBody(BaseModel):
    conversation_id: str
    # The UI sends the document id ("chat-quality"); the active checklist is always used.
    checklist_id: str | int | None = None


class BatchBody(BaseModel):
    conversation_ids: list[str] | None = Field(
        default=None, description="Omit to evaluate every dialog"
    )
    only_new: bool = Field(
        default=False,
        description="Skip dialogs already evaluated with the current checklist version",
    )


async def _get_or_404(session, evaluation_id: int) -> Evaluation:
    ev = await evaluation_service.get_evaluation(session, evaluation_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оценка не найдена")
    return ev


@router.post("")
async def evaluate(body: EvaluateBody, session: SessionDep, queue: QueueDep, settings: SettingsDep):
    """Evaluate a dialog with the active checklist.

    The evaluation is queued and this request waits up to EVALUATION_WAIT_S for the verdict.
    If the model is slower than that, the in-progress evaluation is returned with
    status "queued" / "running" and the client should poll GET /evaluations/{id}.
    """
    d = await dialog_service.get_dialog(session, body.conversation_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Диалог {body.conversation_id} не найден")
    checklist = await checklist_service.ensure_default_checklist(session)

    lock = _locks.setdefault(d.id, asyncio.Lock())
    async with lock:
        in_flight = await session.scalar(
            select(Evaluation)
            .where(
                Evaluation.dialog_id == d.id,
                Evaluation.checklist_id == checklist.id,
                Evaluation.status.in_([EvaluationStatus.queued, EvaluationStatus.running]),
            )
            .order_by(Evaluation.id.desc())
        )
        if (
            in_flight is not None
            and in_flight.checklist_snapshot.get("version") == checklist.version
        ):
            ev_id = in_flight.id
        else:
            ev = await evaluation_service.create_evaluation(session, d, checklist)
            await session.commit()
            ev_id = ev.id
            queue.enqueue(ev_id)

    await queue.wait(ev_id, settings.evaluation_wait_s)
    session.expire_all()
    full = await _get_or_404(session, ev_id)
    if full.status == EvaluationStatus.failed:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Оценка не выполнена: {full.error}")
    return ser.evaluation(full)


@router.post("/batch", status_code=status.HTTP_202_ACCEPTED)
async def evaluate_batch(body: BatchBody, session: SessionDep, queue: QueueDep):
    """Queue many dialogs (all when conversation_ids is omitted); poll /evaluations/batch/{id}."""
    checklist = await checklist_service.ensure_default_checklist(session)
    stmt = select(Dialog).order_by(Dialog.id)
    if body.conversation_ids:
        stmt = stmt.where(Dialog.id.in_(body.conversation_ids))
    dialogs = list((await session.scalars(stmt)).all())
    if body.conversation_ids:
        missing = sorted(set(body.conversation_ids) - {d.id for d in dialogs})
        if missing:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Диалоги не найдены: {', '.join(missing)}"
            )
    if not dialogs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нет диалогов для оценки")
    batch_id, created, skipped = await evaluation_service.create_batch(
        session, dialogs, checklist, skip_evaluated=body.only_new
    )
    await session.commit()
    queue.enqueue_many(e.id for e in created)
    return {
        "batch_id": batch_id,
        "checklist_version": checklist.version,
        "queued": len(created),
        "skipped": skipped,
        "evaluation_ids": [e.id for e in created],
    }


@router.get("/batch/{batch_id}")
async def batch_status(batch_id: str, session: SessionDep):
    counts = await evaluation_service.batch_progress(session, batch_id)
    if counts["total"] == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Батч не найден")
    done = counts["completed"] + counts["failed"] + counts["cancelled"]
    return {"batch_id": batch_id, **counts, "done": done, "finished": done == counts["total"]}


@router.post("/batch/{batch_id}/cancel")
async def cancel_batch(batch_id: str, session: SessionDep):
    """Cancel the batch's evaluations that have not started yet; running ones finish."""
    counts = await evaluation_service.batch_progress(session, batch_id)
    if counts["total"] == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Батч не найден")
    cancelled = await evaluation_service.cancel_batch(session, batch_id)
    return {"batch_id": batch_id, "cancelled": cancelled}


@router.get("")
async def list_evaluations(
    session: SessionDep,
    conversation_id: str | None = None,
    batch_id: str | None = None,
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="queued | running | completed | failed | cancelled",
    ),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
    if status_filter and status_filter not in EvaluationStatus.__members__:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "status: queued | running | completed | failed | cancelled",
        )
    rows, _ = await evaluation_service.list_evaluations(
        session,
        dialog_id=conversation_id,
        batch_id=batch_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return [ser.evaluation_brief(ev) for ev in rows]


@router.get("/{evaluation_id}")
async def get_evaluation(evaluation_id: int, session: SessionDep):
    """Full evaluation; poll this while status is queued / running."""
    return ser.evaluation(await _get_or_404(session, evaluation_id))


@router.post("/{evaluation_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_evaluation(evaluation_id: int, session: SessionDep, queue: QueueDep):
    """Re-queue a failed or cancelled evaluation (e.g. after the model came back)."""
    ev = await _get_or_404(session, evaluation_id)
    if ev.status not in (EvaluationStatus.failed, EvaluationStatus.cancelled):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Оценка в статусе {ev.status.value}, повторить можно только failed / cancelled",
        )
    ev.status = EvaluationStatus.queued
    ev.error = None
    await session.commit()
    queue.enqueue(ev.id)
    return ser.evaluation(await _get_or_404(session, evaluation_id))


class ReviewBody(BaseModel):
    by: str | None = Field(default=None, max_length=100, description="Reviewer name")
    note: str | None = Field(default=None, max_length=4000)


@router.post("/{evaluation_id}/review")
async def review_evaluation(
    evaluation_id: int, session: SessionDep, body: ReviewBody | None = None
):
    """Mark the verdict as checked by a supervisor (closes the dialog in the worklist)."""
    ev = await _get_or_404(session, evaluation_id)
    if ev.status != EvaluationStatus.completed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Проверить можно только завершённую оценку")
    if any(a.status == AppealStatus.pending for r in ev.results for a in r.appeals):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Есть открытые апелляции: сначала примите по ним решение"
        )
    body = body or ReviewBody()
    evaluation_service.mark_reviewed(ev, by=body.by, note=body.note)
    await session.commit()
    return ser.evaluation(await _get_or_404(session, evaluation_id))


@router.delete("/{evaluation_id}/review")
async def unreview_evaluation(evaluation_id: int, session: SessionDep):
    """Return the dialog to the worklist."""
    ev = await _get_or_404(session, evaluation_id)
    evaluation_service.clear_review(ev)
    await session.commit()
    return ser.evaluation(await _get_or_404(session, evaluation_id))
