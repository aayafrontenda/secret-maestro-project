"""Dialogs a supervisor should look at first.

Built from the latest evaluation of every dialog: grave violations, failed runs, open appeals,
low totals and verdicts the backend had to correct. Sorted by priority.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Appeal, Dialog, Evaluation
from app.models.appeal import AppealStatus
from app.models.evaluation import EvaluationStatus

KINDS = ("grave", "failed", "appeal", "low_score", "model_fix")
WEIGHT = {"grave": 1000, "failed": 500, "appeal": 300, "low_score": 100, "model_fix": 50}


def _ratio(points: float | None, weight: float | None) -> float:
    return (points or 0) / weight if weight else 1.0


def _reasons(ev: Evaluation, pending: int, threshold: float) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    if ev.status == EvaluationStatus.failed:
        return [{"kind": "failed", "detail": (ev.error or "")[:300]}]
    for r in ev.results:
        if r.is_flag and r.final_answer == "yes":
            quote = r.evidence[0] if r.evidence else None
            reasons.append(
                {
                    "kind": "grave",
                    "criterion_id": r.criterion_code,
                    "criterion_name": r.criterion_title,
                    "detail": r.explanation,
                    "evidence": (
                        {"msg": quote["message_index"], "quote": quote.get("text", "")}
                        if quote
                        else None
                    ),
                }
            )
    if pending:
        reasons.append({"kind": "appeal", "count": pending})
    if ev.final_total is not None and ev.final_total < threshold:
        scored = [
            r
            for r in ev.results
            if not r.is_flag and r.final_effective_weight and r.final_answer != "na"
        ]
        weakest = sorted(scored, key=lambda r: _ratio(r.final_score, r.final_effective_weight))[:2]
        reasons.append(
            {
                "kind": "low_score",
                "total": ev.final_total,
                "weakest": [
                    {
                        "criterion_id": r.criterion_code,
                        "criterion_name": r.criterion_title,
                        "points": r.final_score,
                        "max_points": r.final_effective_weight,
                    }
                    for r in weakest
                    if _ratio(r.final_score, r.final_effective_weight) < 1
                ],
            }
        )
    for r in ev.results:
        if r.normalization_note:
            reasons.append(
                {
                    "kind": "model_fix",
                    "criterion_id": r.criterion_code,
                    "criterion_name": r.criterion_title,
                    "detail": r.normalization_note,
                }
            )
    return reasons


def _priority(reasons: list[dict[str, Any]], threshold: float) -> float:
    p = 0.0
    for r in reasons:
        p += WEIGHT[r["kind"]]
        if r["kind"] == "low_score":
            p += threshold - r["total"]
    return p


async def attention_queue(
    session: AsyncSession, threshold: float, *, include_reviewed: bool = False
) -> dict[str, Any]:
    latest_id = (
        select(func.max(Evaluation.id))
        .where(Evaluation.status.in_([EvaluationStatus.completed, EvaluationStatus.failed]))
        .group_by(Evaluation.dialog_id)
    )
    evaluations = (
        await session.scalars(
            select(Evaluation)
            .where(Evaluation.id.in_(latest_id))
            .options(selectinload(Evaluation.results), selectinload(Evaluation.dialog))
        )
    ).all()
    # A failed re-run must not hide an earlier completed verdict.
    completed_ids = (
        select(func.max(Evaluation.id))
        .where(Evaluation.status == EvaluationStatus.completed)
        .group_by(Evaluation.dialog_id)
    )
    completed = {
        ev.dialog_id: ev
        for ev in (
            await session.scalars(
                select(Evaluation)
                .where(Evaluation.id.in_(completed_ids))
                .options(selectinload(Evaluation.results), selectinload(Evaluation.dialog))
            )
        ).all()
    }
    pending = dict(
        (
            await session.execute(
                select(Appeal.evaluation_id, func.count())
                .where(Appeal.status == AppealStatus.pending)
                .group_by(Appeal.evaluation_id)
            )
        ).all()
    )

    items = []
    counts = dict.fromkeys(KINDS, 0)
    for ev in evaluations:
        if ev.status == EvaluationStatus.failed and ev.dialog_id in completed:
            ev = completed[ev.dialog_id]
        if ev.reviewed_at and not pending.get(ev.id) and not include_reviewed:
            continue  # a supervisor already checked this verdict
        reasons = _reasons(ev, pending.get(ev.id, 0), threshold)
        if not reasons:
            continue
        for kind in {r["kind"] for r in reasons}:
            counts[kind] += 1
        d: Dialog = ev.dialog
        items.append(
            {
                "conversation_id": d.id,
                "channel": d.channel,
                "language": d.language,
                "evaluation_id": ev.id,
                "status": ev.status.value,
                "total": ev.final_total,
                "checklist_version": ev.checklist_snapshot.get("version"),
                "priority": round(_priority(reasons, threshold), 2),
                "reviewed_at": ev.reviewed_at.isoformat().replace("+00:00", "Z")
                if ev.reviewed_at
                else None,
                "reviewed_by": ev.reviewed_by,
                "reasons": reasons,
            }
        )
    items.sort(key=lambda i: (-i["priority"], i["conversation_id"]))
    return {"threshold": threshold, "counts": {**counts, "total": len(items)}, "items": items}
