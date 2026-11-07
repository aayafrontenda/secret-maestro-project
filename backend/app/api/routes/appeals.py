from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import SessionDep
from app.models import Appeal
from app.schemas.common import Page
from app.schemas.evaluation import AppealDecision, AppealDetail, AppealOut
from app.services import appeals as appeal_service
from app.services.dialogs import transcript_fragment

router = APIRouter(prefix="/appeals", tags=["appeals"])


def _out(a: Appeal) -> AppealOut:
    return AppealOut(
        id=a.id,
        evaluation_id=a.evaluation_id,
        criterion_result_id=a.criterion_result_id,
        criterion_code=a.criterion_result.criterion_code,
        criterion_title=a.criterion_result.criterion_title,
        dialog_id=a.evaluation.dialog_id,
        comment=a.comment,
        status=a.status.value,
        previous_answer=a.previous_answer,
        new_answer=a.new_answer,
        decision_reason=a.decision_reason,
        created_at=a.created_at,
        decided_at=a.decided_at,
    )


def _detail(a: Appeal) -> AppealDetail:
    r = a.criterion_result
    ev = a.evaluation
    spec = next((c for c in ev.checklist_snapshot["criteria"] if c["code"] == r.criterion_code), {})
    indexes = [e["message_index"] for e in r.evidence]
    if r.checked_range:
        indexes += [r.checked_range["from_index"], r.checked_range["to_index"]]
    return AppealDetail(
        **_out(a).model_dump(),
        explanation=r.explanation,
        evidence=r.evidence,
        checked_range=r.checked_range,
        original_score=r.score,
        weight=r.weight,
        answer_type=r.answer_type,
        scale_max=spec.get("scale_max"),
        allow_na=bool(spec.get("allow_na")),
        is_flag=r.is_flag,
        fragment=transcript_fragment(ev.dialog.transcript, indexes),
        evaluation_original_total=ev.original_total,
        evaluation_final_total=ev.final_total,
    )


@router.get("", response_model=Page[AppealOut])
async def list_appeals(
    session: SessionDep,
    status_filter: str | None = Query(
        default=None, alias="status", description="pending|confirmed|changed"
    ),
    evaluation_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    rows, total = await appeal_service.list_appeals(
        session, status=status_filter, evaluation_id=evaluation_id, limit=limit, offset=offset
    )
    return Page(items=[_out(a) for a in rows], total=total, limit=limit, offset=offset)


@router.get("/{appeal_id}", response_model=AppealDetail)
async def get_appeal(appeal_id: int, session: SessionDep):
    a = await appeal_service.get_appeal(session, appeal_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "appeal not found")
    return _detail(a)


@router.post("/{appeal_id}/decision", response_model=AppealDetail)
async def decide(appeal_id: int, body: AppealDecision, session: SessionDep):
    """Reviewer confirms or changes the verdict; the evaluation's final total is recalculated."""
    a = await appeal_service.get_appeal(session, appeal_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "appeal not found")
    try:
        a = await appeal_service.decide_appeal(session, a, body)
    except appeal_service.AppealError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await session.commit()
    a = await appeal_service.get_appeal(session, appeal_id)
    return _detail(a)  # type: ignore[arg-type]
