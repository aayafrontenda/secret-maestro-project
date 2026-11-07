from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api import serializers as ser
from app.api.deps import SessionDep
from app.schemas.appeal import AppealDecision
from app.services import appeals as appeal_service
from app.services import evaluations as evaluation_service

router = APIRouter(prefix="/appeals", tags=["appeals"])


class AppealBody(BaseModel):
    evaluation_id: int
    conversation_id: str | None = None
    criterion_id: str
    comment: str = Field(min_length=1, max_length=4000)


class DecisionBody(BaseModel):
    action: str = Field(description="confirm | change")
    answer: Any | None = None
    reason: str = Field(min_length=1, max_length=4000)


@router.get("")
async def list_appeals(
    session: SessionDep,
    evaluation_id: int | None = None,
    status_filter: str | None = Query(
        default=None, alias="status", description="open | confirmed | changed"
    ),
    limit: int = Query(default=500, ge=1, le=2000),
):
    internal = None
    if status_filter:
        if status_filter not in ser.UI_TO_APPEAL_STATUS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "status: open | confirmed | changed"
            )
        internal = ser.UI_TO_APPEAL_STATUS[status_filter].value
    rows, _ = await appeal_service.list_appeals(
        session, status=internal, evaluation_id=evaluation_id, limit=limit
    )
    return [ser.appeal(a) for a in reversed(rows)]


@router.get("/{appeal_id}")
async def get_appeal(appeal_id: int, session: SessionDep):
    a = await appeal_service.get_appeal(session, appeal_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Апелляция не найдена")
    return ser.appeal(a)


@router.post("")
async def create_appeal(body: AppealBody, session: SessionDep):
    """Dispute one criterion verdict. Reviewers pick it up from GET /appeals?status=open."""
    ev = await evaluation_service.get_evaluation(session, body.evaluation_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оценка не найдена")
    result = next((r for r in ev.results if r.criterion_code == body.criterion_id), None)
    if result is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Критерий {body.criterion_id} не найден в оценке"
        )
    try:
        appeal = await appeal_service.create_appeal(session, ev, result.id, body.comment)
    except appeal_service.AppealError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await session.commit()
    return ser.appeal(appeal)


@router.post("/{appeal_id}/decision")
async def decide_appeal(appeal_id: int, body: DecisionBody, session: SessionDep):
    """Reviewer confirms or changes the verdict; the evaluation's final total is recalculated."""
    a = await appeal_service.get_appeal(session, appeal_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Апелляция не найдена")
    if body.action not in ("confirm", "change"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "action: confirm | change")
    try:
        decision = AppealDecision(
            decision=body.action,  # type: ignore[arg-type]
            new_answer=body.answer if body.action == "change" else None,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    try:
        await appeal_service.decide_appeal(session, a, decision)
    except appeal_service.AppealError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await session.commit()
    a = await appeal_service.get_appeal(session, appeal_id)
    return ser.appeal(a)  # type: ignore[arg-type]
