import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ml.base import MLClient, MLClientError
from app.ml.schemas import MLCriterion, MLEvaluateRequest, MLEvaluateResponse, MLTranscriptMessage
from app.models import Checklist, CriterionResult, Dialog, Evaluation
from app.models.evaluation import EvaluationStatus
from app.services import checklists as checklist_service
from app.services.scoring import CriterionSpec, ScoreReport, ScoringError, score

log = logging.getLogger(__name__)


class EvaluationError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


# --- creation -------------------------------------------------------------------------------


async def create_evaluation(
    session: AsyncSession, dialog: Dialog, checklist: Checklist, *, batch_id: str | None = None
) -> Evaluation:
    ev = Evaluation(
        dialog_id=dialog.id,
        checklist_id=checklist.id,
        checklist_snapshot=await checklist_service.snapshot(session, checklist),
        status=EvaluationStatus.queued,
        batch_id=batch_id,
    )
    session.add(ev)
    await session.flush()
    return ev


async def create_batch(
    session: AsyncSession,
    dialogs: list[Dialog],
    checklist: Checklist,
    *,
    skip_evaluated: bool = False,
) -> tuple[str, list[Evaluation], int]:
    batch_id = str(uuid.uuid4())
    skipped = 0
    already: set[str] = set()
    if skip_evaluated:
        # Only a completed evaluation with the *current* checklist version counts.
        stmt = select(Evaluation.dialog_id, Evaluation.checklist_snapshot).where(
            Evaluation.checklist_id == checklist.id,
            Evaluation.status == EvaluationStatus.completed,
            Evaluation.dialog_id.in_([d.id for d in dialogs]),
        )
        for dialog_id, snapshot in (await session.execute(stmt)).all():
            if snapshot.get("version") == checklist.version:
                already.add(dialog_id)
    created: list[Evaluation] = []
    for d in dialogs:
        if d.id in already:
            skipped += 1
            continue
        created.append(await create_evaluation(session, d, checklist, batch_id=batch_id))
    return batch_id, created, skipped


# --- pipeline -------------------------------------------------------------------------------


def build_ml_request(dialog: Dialog, snapshot: dict[str, Any]) -> MLEvaluateRequest:
    return MLEvaluateRequest(
        conversation_id=dialog.id,
        channel=dialog.channel,
        language=dialog.language,
        transcript=[MLTranscriptMessage(**m) for m in dialog.transcript],
        criteria=[
            MLCriterion(**{k: v for k, v in c.items() if k != "position"})
            for c in snapshot["criteria"]
        ],
    )


def _enrich_evidence(transcript: list[dict], indexes: list[int]) -> list[dict[str, Any]]:
    items = []
    seen: set[int] = set()
    for i in indexes:
        if i in seen or i < 0 or i >= len(transcript):
            continue
        seen.add(i)
        m = transcript[i]
        items.append(
            {
                "message_index": i,
                "timestamp": m["timestamp"],
                "speaker": m["speaker"],
                "text": m["text"],
            }
        )
    return items


def _clamp_range(transcript: list[dict], rng: dict[str, int] | None) -> dict[str, int] | None:
    if not rng or not transcript:
        return None
    last = len(transcript) - 1
    lo = min(max(0, rng["from_index"]), last)
    hi = min(max(lo, rng["to_index"]), last)
    return {"from_index": lo, "to_index": hi}


def apply_scores(ev: Evaluation, report: ScoreReport, *, final: bool) -> None:
    by_code = {c.code: c for c in report.criteria}
    for r in ev.results:
        cs = by_code[r.criterion_code]
        if final:
            r.final_answer = cs.answer
            r.final_score = cs.points
            r.final_effective_weight = cs.effective_weight
        else:
            r.answer = cs.answer
            r.score = cs.points
            r.effective_weight = cs.effective_weight
            if cs.normalization_note:
                r.normalization_note = cs.normalization_note
    sections = [
        {"name": s.name, "points": s.points, "max_points": s.max_points, "criteria": s.criteria}
        for s in report.sections
    ]
    if final:
        ev.final_total = report.total
        ev.final_sections = sections
        ev.final_grave_error = report.grave_error
    else:
        ev.original_total = report.total
        ev.original_sections = sections
        ev.grave_error = report.grave_error


def specs_from_snapshot(snapshot: dict[str, Any]) -> list[CriterionSpec]:
    return [CriterionSpec.from_dict(c) for c in snapshot["criteria"]]


def _materialize_results(
    ev: Evaluation, dialog: Dialog, response: MLEvaluateResponse
) -> dict[str, Any]:
    """Create CriterionResult rows from the ML response; returns raw answers by code."""
    by_code = {r.code: r for r in response.results}
    criteria = ev.checklist_snapshot["criteria"]
    missing = [c["code"] for c in criteria if c["code"] not in by_code]
    if missing:
        raise EvaluationError(f"ML response is missing criteria: {', '.join(missing)}")
    unknown = sorted(set(by_code) - {c["code"] for c in criteria})
    if unknown:
        log.warning(
            "ML response has unknown criteria %s for evaluation %s; ignored", unknown, ev.id
        )

    answers: dict[str, Any] = {}
    ev.results = []
    for c in criteria:
        r = by_code[c["code"]]
        answers[c["code"]] = r.answer
        ev.results.append(
            CriterionResult(
                criterion_code=c["code"],
                criterion_title=c["title"],
                position=c["position"],
                section=c.get("section"),
                answer_type=c["answer_type"],
                is_flag=bool(c.get("is_flag")),
                weight=float(c.get("weight") or 0),
                answer=r.answer,
                final_answer=r.answer,
                explanation=r.explanation or "",
                evidence=_enrich_evidence(dialog.transcript, r.evidence),
                checked_range=_clamp_range(
                    dialog.transcript, r.checked_range.model_dump() if r.checked_range else None
                ),
                na_reason=r.na_reason,
            )
        )
    return answers


async def run_evaluation(session: AsyncSession, evaluation_id: int, ml: MLClient) -> Evaluation:
    """Execute one queued evaluation end-to-end. Commits on success and on failure."""
    ev = await session.scalar(
        select(Evaluation)
        .where(Evaluation.id == evaluation_id)
        .options(selectinload(Evaluation.results), selectinload(Evaluation.dialog))
    )
    if ev is None:
        raise EvaluationError(f"evaluation {evaluation_id} not found")
    if ev.status == EvaluationStatus.completed:
        return await get_evaluation(session, evaluation_id)  # type: ignore[return-value]

    ev.status = EvaluationStatus.running
    ev.started_at = _now()
    ev.error = None
    await session.commit()

    try:
        request = build_ml_request(ev.dialog, ev.checklist_snapshot)
        response = await ml.evaluate(request)
        answers = _materialize_results(ev, ev.dialog, response)
        report = score(specs_from_snapshot(ev.checklist_snapshot), answers)
        apply_scores(ev, report, final=False)
        apply_scores(ev, report, final=True)
        ev.provider = response.model.provider
        ev.model_name = response.model.name
        ev.usage = response.usage.model_dump() if response.usage else None
        ev.status = EvaluationStatus.completed
        ev.completed_at = _now()
        await session.commit()
        log.info(
            "evaluation %s completed: total=%s grave=%s", ev.id, ev.original_total, ev.grave_error
        )
    except (MLClientError, EvaluationError, ScoringError) as exc:
        await session.rollback()
        await _mark_failed(session, evaluation_id, str(exc))
        log.warning("evaluation %s failed: %s", evaluation_id, exc)
    except Exception as exc:  # noqa: BLE001 — a worker must never die on one bad evaluation
        await session.rollback()
        await _mark_failed(session, evaluation_id, f"{type(exc).__name__}: {exc}")
        log.exception("evaluation %s crashed", evaluation_id)
    return await get_evaluation(session, evaluation_id)  # type: ignore[return-value]


async def _mark_failed(session: AsyncSession, evaluation_id: int, error: str) -> None:
    ev = await session.get(Evaluation, evaluation_id)
    if ev is None:
        return
    ev.status = EvaluationStatus.failed
    ev.error = error[:4000]
    ev.completed_at = _now()
    await session.commit()


# --- recalculation after appeals ----------------------------------------------------------------


def recalculate_final(ev: Evaluation) -> None:
    """Recompute final scores from each criterion's final_answer."""
    answers = {r.criterion_code: r.final_answer for r in ev.results}
    report = score(specs_from_snapshot(ev.checklist_snapshot), answers)
    apply_scores(ev, report, final=True)


# --- queries ------------------------------------------------------------------------------------


def _full_options():
    return (
        selectinload(Evaluation.results).selectinload(CriterionResult.appeals),
        selectinload(Evaluation.dialog),
    )


async def get_evaluation(session: AsyncSession, evaluation_id: int) -> Evaluation | None:
    return await session.scalar(
        select(Evaluation).where(Evaluation.id == evaluation_id).options(*_full_options())
    )


async def list_evaluations(
    session: AsyncSession,
    *,
    dialog_id: str | None = None,
    checklist_id: int | None = None,
    batch_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Evaluation], int]:
    stmt = select(Evaluation)
    if dialog_id:
        stmt = stmt.where(Evaluation.dialog_id == dialog_id)
    if checklist_id is not None:
        stmt = stmt.where(Evaluation.checklist_id == checklist_id)
    if batch_id:
        stmt = stmt.where(Evaluation.batch_id == batch_id)
    if status:
        stmt = stmt.where(Evaluation.status == EvaluationStatus(status))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await session.scalars(stmt.order_by(Evaluation.id.desc()).limit(limit).offset(offset))
    ).all()
    return list(rows), total


async def pending_evaluation_ids(session: AsyncSession) -> list[int]:
    """Evaluations left queued/running by a previous process (crash recovery)."""
    stmt = (
        select(Evaluation.id)
        .where(Evaluation.status.in_([EvaluationStatus.queued, EvaluationStatus.running]))
        .order_by(Evaluation.id)
    )
    return list((await session.scalars(stmt)).all())


async def batch_progress(session: AsyncSession, batch_id: str) -> dict[str, int]:
    stmt = (
        select(Evaluation.status, func.count())
        .where(Evaluation.batch_id == batch_id)
        .group_by(Evaluation.status)
    )
    counts = {s.value: 0 for s in EvaluationStatus}
    for status, n in (await session.execute(stmt)).all():
        counts[status.value if isinstance(status, EvaluationStatus) else status] = n
    counts["total"] = sum(counts.values())
    return counts
