from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Appeal, CriterionResult, Evaluation
from app.models.appeal import AppealStatus
from app.models.evaluation import EvaluationStatus
from app.schemas.evaluation import AppealDecision
from app.services import evaluations as evaluation_service
from app.services.scoring import CriterionSpec, ScoringError, normalize_answer


class AppealError(ValueError):
    pass


def _appeal_options():
    return (
        selectinload(Appeal.criterion_result),
        selectinload(Appeal.evaluation).selectinload(Evaluation.dialog),
    )


async def get_appeal(session: AsyncSession, appeal_id: int) -> Appeal | None:
    return await session.scalar(
        select(Appeal).where(Appeal.id == appeal_id).options(*_appeal_options())
    )


async def list_appeals(
    session: AsyncSession,
    *,
    status: str | None = None,
    evaluation_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Appeal], int]:
    stmt = select(Appeal).options(*_appeal_options())
    if status:
        stmt = stmt.where(Appeal.status == AppealStatus(status))
    if evaluation_id is not None:
        stmt = stmt.where(Appeal.evaluation_id == evaluation_id)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await session.scalars(stmt.order_by(Appeal.id.desc()).limit(limit).offset(offset))
    ).all()
    return list(rows), total


async def create_appeal(
    session: AsyncSession, evaluation: Evaluation, criterion_result_id: int, comment: str
) -> Appeal:
    if evaluation.status != EvaluationStatus.completed:
        raise AppealError("only completed evaluations can be appealed")
    result = next((r for r in evaluation.results if r.id == criterion_result_id), None)
    if result is None:
        raise AppealError("criterion result does not belong to this evaluation")
    open_appeal = await session.scalar(
        select(Appeal.id).where(
            Appeal.criterion_result_id == criterion_result_id, Appeal.status == AppealStatus.pending
        )
    )
    if open_appeal:
        raise AppealError(f"criterion already has a pending appeal (#{open_appeal})")
    appeal = Appeal(
        evaluation_id=evaluation.id,
        criterion_result_id=result.id,
        comment=comment,
        status=AppealStatus.pending,
        previous_answer=result.final_answer,
    )
    session.add(appeal)
    await session.flush()
    return await get_appeal(session, appeal.id)  # type: ignore[return-value]


async def decide_appeal(session: AsyncSession, appeal: Appeal, decision: AppealDecision) -> Appeal:
    if appeal.status != AppealStatus.pending:
        raise AppealError("appeal has already been decided")

    evaluation = await evaluation_service.get_evaluation(session, appeal.evaluation_id)
    if evaluation is None:
        raise AppealError("evaluation not found")
    result: CriterionResult = next(
        r for r in evaluation.results if r.id == appeal.criterion_result_id
    )

    if decision.decision == "change":
        spec_dict = next(
            c
            for c in evaluation.checklist_snapshot["criteria"]
            if c["code"] == result.criterion_code
        )
        spec = CriterionSpec.from_dict(spec_dict)
        try:
            new_answer, note = normalize_answer(spec, decision.new_answer)
        except ScoringError as exc:
            raise AppealError(str(exc)) from exc
        if note and "N/A is not allowed" in note:
            raise AppealError(f"N/A is not allowed for criterion {result.criterion_code}")
        if new_answer == result.final_answer:
            raise AppealError("new answer equals the current verdict; use 'confirm' instead")
        result.final_answer = new_answer
        appeal.new_answer = new_answer
        appeal.status = AppealStatus.changed
        evaluation_service.recalculate_final(evaluation)
    else:
        appeal.status = AppealStatus.confirmed

    appeal.decision_reason = decision.reason
    appeal.decided_at = datetime.now(UTC)
    await session.flush()
    return await get_appeal(session, appeal.id)  # type: ignore[return-value]
