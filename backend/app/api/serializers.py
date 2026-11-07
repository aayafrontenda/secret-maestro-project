"""Response shapes (docs/API_CONTRACT.md)."""

from datetime import datetime
from typing import Any

from app.models import Appeal, Dialog, Evaluation
from app.models.appeal import AppealStatus
from app.services.checklist_document import document_from_snapshot

APPEAL_STATUS = {
    AppealStatus.pending: "open",
    AppealStatus.confirmed: "confirmed",
    AppealStatus.changed: "changed",
}
UI_TO_APPEAL_STATUS = {v: k for k, v in APPEAL_STATUS.items()}


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def dialog_record(d: Dialog) -> dict[str, Any]:
    """The organizer record shape, plus group_id."""
    return {
        "conversation_id": d.id,
        "channel": d.channel,
        "language": d.language,
        "group_id": d.dataset_group_id,
        "transcript": [
            {"timestamp": m["timestamp"], "speaker": m["speaker"], "text": m["text"]}
            for m in d.transcript
        ],
        "audio_url": d.audio_url,
    }


def review_status(ev: Evaluation | None, appeals_open: int = 0) -> str:
    """none: not evaluated; appeal: waits for a reviewer's decision; reviewed: closed;
    to_review: evaluated, nobody has checked it yet."""
    if ev is None:
        return "none"
    if appeals_open:
        return "appeal"
    return "reviewed" if ev.reviewed_at else "to_review"


def review(ev: Evaluation) -> dict[str, Any] | None:
    if not ev.reviewed_at:
        return None
    return {"reviewed_at": iso(ev.reviewed_at), "by": ev.reviewed_by, "note": ev.review_note}


def dialog_row(
    d: Dialog, ev: Evaluation | None, appeals_open: int = 0, appeals_total: int = 0
) -> dict[str, Any]:
    return {
        "conversation_id": d.id,
        "channel": d.channel,
        "language": d.language,
        "group_id": d.dataset_group_id,
        "turns": d.message_count,
        "evaluation": "done" if ev else "none",
        "total": ev.final_total if ev else None,
        "gross_error": bool(ev.final_grave_error) if ev else False,
        "checklist_version": ev.checklist_snapshot.get("version") if ev else None,
        "evaluated_at": iso(ev.completed_at) if ev else None,
        "appeals_open": appeals_open,
        "appeals_total": appeals_total,
        "review_status": review_status(ev, appeals_open),
        "reviewed_at": iso(ev.reviewed_at) if ev else None,
        "reviewed_by": ev.reviewed_by if ev else None,
    }


def evaluation(ev: Evaluation) -> dict[str, Any]:
    doc = document_from_snapshot(ev.checklist_snapshot)
    usage = ev.usage or {}
    latency_ms = None
    if ev.started_at and ev.completed_at:
        latency_ms = int((ev.completed_at - ev.started_at).total_seconds() * 1000)
    results = [
        {
            "criterion_id": r.criterion_code,
            # The model's verdict; the UI applies appeal decisions on top of it.
            "answer": r.answer,
            "explanation": r.explanation,
            "na_reason": r.na_reason,
            "evidence": [
                {"msg": e["message_index"], "quote": e.get("text", "")} for e in r.evidence
            ],
            "checked_range": (
                [r.checked_range["from_index"], r.checked_range["to_index"]]
                if r.checked_range
                else None
            ),
            "confidence": None,
            # Backend-computed extras.
            "final_answer": r.final_answer,
            "points": r.score,
            "final_points": r.final_score,
            "effective_weight": r.effective_weight,
            "normalization_note": r.normalization_note,
        }
        for r in ev.results
    ]
    return {
        "evaluation_id": ev.id,
        "conversation_id": ev.dialog_id,
        "checklist_id": doc.get("id", "chat-quality"),
        "checklist_version": ev.checklist_snapshot.get("version"),
        "checklist": doc,
        "status": ev.status.value,
        "error": ev.error,
        "batch_id": ev.batch_id,
        "model": ev.model_name or ev.provider or "unknown",
        "is_mock": ev.provider == "mock",
        "created_at": iso(ev.created_at),
        "completed_at": iso(ev.completed_at),
        "latency_ms": latency_ms,
        "cost_usd": usage.get("cost_usd"),
        "tokens": {
            "input": usage.get("prompt_tokens", 0),
            "output": usage.get("completion_tokens", 0),
        },
        "results": results,
        # Backend-computed totals (the UI recomputes the same numbers client-side).
        "total": ev.original_total,
        "final_total": ev.final_total,
        "gross_error": ev.grave_error,
        "final_gross_error": ev.final_grave_error,
        "sections": ev.final_sections,
        "review": review(ev),
    }


def evaluation_brief(ev: Evaluation) -> dict[str, Any]:
    return {
        "evaluation_id": ev.id,
        "conversation_id": ev.dialog_id,
        "status": ev.status.value,
        "error": ev.error,
        "batch_id": ev.batch_id,
        "checklist_version": ev.checklist_snapshot.get("version"),
        "total": ev.original_total,
        "final_total": ev.final_total,
        "gross_error": ev.final_grave_error,
        "created_at": iso(ev.created_at),
        "completed_at": iso(ev.completed_at),
        "reviewed_at": iso(ev.reviewed_at),
    }


def appeal(a: Appeal) -> dict[str, Any]:
    decided = a.status != AppealStatus.pending
    return {
        "appeal_id": a.id,
        "evaluation_id": a.evaluation_id,
        "conversation_id": a.evaluation.dialog_id,
        "criterion_id": a.criterion_result.criterion_code,
        "criterion_name": a.criterion_result.criterion_title,
        "original_answer": a.previous_answer,
        "comment": a.comment,
        "status": APPEAL_STATUS[a.status],
        "created_at": iso(a.created_at),
        "decision": (
            {
                "action": "change" if a.status == AppealStatus.changed else "confirm",
                "answer": a.new_answer,
                "reason": a.decision_reason,
                "decided_at": iso(a.decided_at),
                "by": a.decided_by,
            }
            if decided
            else None
        ),
    }
