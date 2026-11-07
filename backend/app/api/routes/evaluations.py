from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import MLDep, QueueDep, SessionDep
from app.models import Dialog
from app.models.evaluation import EvaluationStatus
from app.schemas.common import Page
from app.schemas.evaluation import (
    AppealBrief,
    AppealCreate,
    EvaluationBatchCreate,
    EvaluationBatchResult,
    EvaluationCreate,
    EvaluationListItem,
    EvaluationOut,
)
from app.services import appeals as appeal_service
from app.services import checklists as checklist_service
from app.services import dialogs as dialog_service
from app.services import evaluations as evaluation_service

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


async def _resolve_checklist(session, checklist_id: int | None):
    if checklist_id is None:
        c = await checklist_service.get_default_checklist(session)
        if c is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "no default checklist; create one first")
        return c
    c = await checklist_service.get_checklist(session, checklist_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "checklist not found")
    return c


async def _get_or_404(session, evaluation_id: int):
    ev = await evaluation_service.get_evaluation(session, evaluation_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "evaluation not found")
    return ev


@router.post("", response_model=EvaluationOut, status_code=status.HTTP_202_ACCEPTED)
async def create_evaluation(body: EvaluationCreate, session: SessionDep, queue: QueueDep):
    """Queue an evaluation of one dialog. Poll GET /evaluations/{id} until status is completed."""
    dialog = await dialog_service.get_dialog(session, body.dialog_id)
    if dialog is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dialog not found")
    checklist = await _resolve_checklist(session, body.checklist_id)
    ev = await evaluation_service.create_evaluation(session, dialog, checklist)
    await session.commit()
    queue.enqueue(ev.id)
    return EvaluationOut.model_validate(await _get_or_404(session, ev.id))


@router.post("/sync", response_model=EvaluationOut)
async def evaluate_now(body: EvaluationCreate, session: SessionDep, ml: MLDep):
    """Evaluate one dialog synchronously (blocks until the model answers). Handy for demos."""
    dialog = await dialog_service.get_dialog(session, body.dialog_id)
    if dialog is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dialog not found")
    checklist = await _resolve_checklist(session, body.checklist_id)
    ev = await evaluation_service.create_evaluation(session, dialog, checklist)
    await session.commit()
    ev = await evaluation_service.run_evaluation(session, ev.id, ml)
    return EvaluationOut.model_validate(ev)


@router.post("/batch", response_model=EvaluationBatchResult, status_code=status.HTTP_202_ACCEPTED)
async def create_batch(body: EvaluationBatchCreate, session: SessionDep, queue: QueueDep):
    """Queue evaluations for many dialogs (all of them when dialog_ids is omitted)."""
    checklist = await _resolve_checklist(session, body.checklist_id)
    stmt = select(Dialog).order_by(Dialog.id)
    if body.dialog_ids:
        stmt = stmt.where(Dialog.id.in_(body.dialog_ids))
    dialogs = list((await session.scalars(stmt)).all())
    if body.dialog_ids:
        missing = sorted(set(body.dialog_ids) - {d.id for d in dialogs})
        if missing:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"dialogs not found: {', '.join(missing)}"
            )
    if not dialogs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no dialogs to evaluate")
    batch_id, created, skipped = await evaluation_service.create_batch(
        session, dialogs, checklist, skip_evaluated=body.skip_evaluated
    )
    await session.commit()
    queue.enqueue_many(e.id for e in created)
    return EvaluationBatchResult(
        batch_id=batch_id,
        checklist_id=checklist.id,
        evaluation_ids=[e.id for e in created],
        queued=len(created),
        skipped=skipped,
    )


@router.get("/batch/{batch_id}")
async def batch_status(batch_id: str, session: SessionDep):
    counts = await evaluation_service.batch_progress(session, batch_id)
    if counts["total"] == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "batch not found")
    done = counts["completed"] + counts["failed"]
    return {"batch_id": batch_id, **counts, "done": done, "finished": done == counts["total"]}


@router.get("", response_model=Page[EvaluationListItem])
async def list_evaluations(
    session: SessionDep,
    dialog_id: str | None = None,
    checklist_id: int | None = None,
    batch_id: str | None = None,
    status_filter: str | None = Query(
        default=None, alias="status", description="queued|running|completed|failed"
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    rows, total = await evaluation_service.list_evaluations(
        session,
        dialog_id=dialog_id,
        checklist_id=checklist_id,
        batch_id=batch_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[EvaluationListItem.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{evaluation_id}", response_model=EvaluationOut)
async def get_evaluation(evaluation_id: int, session: SessionDep):
    return EvaluationOut.model_validate(await _get_or_404(session, evaluation_id))


@router.post(
    "/{evaluation_id}/retry", response_model=EvaluationOut, status_code=status.HTTP_202_ACCEPTED
)
async def retry_evaluation(evaluation_id: int, session: SessionDep, queue: QueueDep):
    """Re-queue a failed evaluation."""
    ev = await _get_or_404(session, evaluation_id)
    if ev.status.value != "failed":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"evaluation is {ev.status.value}, not failed"
        )
    ev.status = EvaluationStatus.queued
    ev.error = None
    await session.commit()
    queue.enqueue(ev.id)
    return EvaluationOut.model_validate(await _get_or_404(session, evaluation_id))


@router.delete("/{evaluation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evaluation(evaluation_id: int, session: SessionDep):
    ev = await _get_or_404(session, evaluation_id)
    if ev.status.value in ("queued", "running"):
        raise HTTPException(status.HTTP_409_CONFLICT, "evaluation is still in progress")
    await session.delete(ev)
    await session.commit()


@router.post(
    "/{evaluation_id}/appeals", response_model=AppealBrief, status_code=status.HTTP_201_CREATED
)
async def create_appeal(evaluation_id: int, body: AppealCreate, session: SessionDep):
    """Dispute one criterion verdict. The reviewer picks it up from GET /appeals?status=pending."""
    ev = await _get_or_404(session, evaluation_id)
    try:
        appeal = await appeal_service.create_appeal(
            session, ev, body.criterion_result_id, body.comment
        )
    except appeal_service.AppealError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await session.commit()
    return AppealBrief.model_validate(appeal)
