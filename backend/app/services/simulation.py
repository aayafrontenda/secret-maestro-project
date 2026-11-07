"""Dry run of a checklist draft on dialogs that are already evaluated.

Before a new checklist version is published, the draft is applied to a sample of completed
evaluations: only the changed criteria go to the model, the other answers are reused, and the
result is compared with the current answers and with the reviewers' appeal decisions. Nothing
is stored; the evaluations stay as they are.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ml.base import MLClient, MLClientError
from app.ml.schemas import MLCriterion, MLEvaluateRequest, MLTranscriptMessage
from app.models import Checklist, Evaluation
from app.models.appeal import AppealStatus
from app.models.evaluation import CriterionResult, EvaluationStatus
from app.schemas.checklist import ChecklistIn
from app.services.evaluations import _guidelines
from app.services.scoring import CriterionSpec, ScoringError, normalize_answer, score

log = logging.getLogger(__name__)

# Fields the model sees: a change in any of them needs a new answer. Weight and section only
# change the score, which is recomputed without the model.
ML_FIELDS = (
    "title",
    "rule",
    "answer_type",
    "scale_max",
    "scale_steps",
    "allow_na",
    "na_rule",
    "is_flag",
)
MAX_LIMIT = 30
CONCURRENCY = 4


def draft_criteria(data: ChecklistIn) -> list[dict[str, Any]]:
    """The draft in the snapshot's shape (what an evaluation would store)."""
    out = []
    for i, c in enumerate(data.criteria):
        d = c.model_dump(mode="json")
        d["position"] = i
        out.append(d)
    return out


def _ml_view(c: dict[str, Any]) -> dict[str, Any]:
    view = {k: c.get(k) for k in ML_FIELDS}
    steps = view.get("scale_steps") or None
    view["scale_steps"] = (
        sorted(((int(s["value"]), (s.get("label") or "").strip()) for s in steps), reverse=True)
        if steps
        else None
    )
    for k in ("title", "rule", "na_rule"):
        view[k] = (view[k] or "").strip()
    return view


def changed_criteria(
    active: list[dict[str, Any]], draft: list[dict[str, Any]], guidelines_changed: bool
) -> list[dict[str, Any]]:
    """Draft criteria the model must answer again, each with why."""
    old = {c["code"]: c for c in active}
    out = []
    for c in draft:
        prev = old.get(c["code"])
        if prev is None:
            out.append({"criterion_id": c["code"], "criterion_name": c["title"], "reason": "new"})
        elif _ml_view(prev) != _ml_view(c):
            fields = [k for k in ML_FIELDS if _ml_view(prev)[k] != _ml_view(c)[k]]
            out.append(
                {
                    "criterion_id": c["code"],
                    "criterion_name": c["title"],
                    "reason": "edited",
                    "fields": fields,
                }
            )
        elif guidelines_changed:
            out.append(
                {"criterion_id": c["code"], "criterion_name": c["title"], "reason": "guidelines"}
            )
    return out


async def _sample(session: AsyncSession, codes: set[str], limit: int) -> list[Evaluation]:
    """Latest completed evaluation per dialog; ones with decided appeals on the changed
    criteria first, since those are where the reviewers' answer is known."""
    rows = (
        await session.scalars(
            select(Evaluation)
            .where(Evaluation.status == EvaluationStatus.completed)
            .order_by(Evaluation.id.desc())
            .limit(500)
            .options(
                selectinload(Evaluation.results).selectinload(CriterionResult.appeals),
                selectinload(Evaluation.dialog),
            )
        )
    ).all()
    latest: dict[str, Evaluation] = {}
    for ev in rows:
        latest.setdefault(ev.dialog_id, ev)

    def decided(ev: Evaluation) -> int:
        return sum(
            1 for r in ev.results if r.criterion_code in codes and _human_answer(r) is not None
        )

    return sorted(latest.values(), key=lambda ev: (-decided(ev), -ev.id))[:limit]


def _human_answer(r: CriterionResult) -> Any | None:
    """The reviewer's answer when an appeal on this result was decided, else None."""
    for a in r.appeals:
        if a.status in (AppealStatus.changed, AppealStatus.confirmed):
            return r.final_answer
    return None


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, int | float) and isinstance(b, int | float):
        return float(a) == float(b)
    return a == b


async def simulate(
    session: AsyncSession,
    checklist: Checklist,
    active_snapshot: dict[str, Any],
    draft_doc: dict[str, Any],
    data: ChecklistIn,
    ml: MLClient,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    limit = max(1, min(int(limit), MAX_LIMIT))
    draft = draft_criteria(data)
    draft_by_code = {c["code"]: c for c in draft}
    specs = [CriterionSpec.from_dict(c) for c in draft]
    spec_by_code = {s.code: s for s in specs}
    guidelines = _guidelines({"document": draft_doc})
    guidelines_changed = guidelines != _guidelines(active_snapshot)
    changed = changed_criteria(active_snapshot["criteria"], draft, guidelines_changed)
    changed_codes = {c["criterion_id"] for c in changed}

    evals = await _sample(session, changed_codes, limit)
    sem = asyncio.Semaphore(CONCURRENCY)
    model: dict[str, Any] | None = None
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}

    async def run_one(ev: Evaluation) -> dict[str, Any]:
        nonlocal model
        by_code = {r.criterion_code: r for r in ev.results}
        # Changed criteria, plus any draft criterion this (older) evaluation has no answer for.
        need = [c for c in draft if c["code"] in changed_codes or c["code"] not in by_code]
        new: dict[str, Any] = {}
        explanations: dict[str, str] = {}
        if need:
            request = MLEvaluateRequest(
                guidelines=guidelines,
                conversation_id=ev.dialog.id,
                channel=ev.dialog.channel,
                language=ev.dialog.language,
                transcript=[MLTranscriptMessage(**m) for m in ev.dialog.transcript],
                criteria=[
                    MLCriterion(**{k: v for k, v in c.items() if k != "position"}) for c in need
                ],
            )
            async with sem:
                response = await ml.evaluate(request)
            model = response.model.model_dump()
            if response.usage:
                usage["prompt_tokens"] += response.usage.prompt_tokens or 0
                usage["completion_tokens"] += response.usage.completion_tokens or 0
                usage["cost_usd"] += response.usage.cost_usd or 0.0
            got = {r.code: r for r in response.results}
            for c in need:
                r = got.get(c["code"])
                if r is None:
                    raise MLClientError(f"no answer for {c['code']}")
                new[c["code"]], _ = normalize_answer(spec_by_code[c["code"]], r.answer)
                explanations[c["code"]] = r.explanation or ""

        answers = {
            code: new[code] if code in new else by_code[code].final_answer for code in draft_by_code
        }
        report = score(specs, answers)
        changes = []
        for code in new:
            old_r = by_code.get(code)
            old = old_r.final_answer if old_r else None
            human = _human_answer(old_r) if old_r else None
            item = {
                "criterion_id": code,
                "criterion_name": draft_by_code[code]["title"],
                "old_answer": old,
                "new_answer": new[code],
                "model_answer": old_r.answer if old_r else None,
                "human_answer": human,
                "changed": old_r is None or not _same(old, new[code]),
                "explanation": explanations.get(code, ""),
            }
            changes.append(item)
        return {
            "conversation_id": ev.dialog_id,
            "evaluation_id": ev.id,
            "language": ev.dialog.language,
            "old_total": ev.final_total,
            "new_total": report.total,
            "grave_error": report.grave_error,
            "changes": changes,
        }

    async def guarded(ev: Evaluation) -> dict[str, Any]:
        try:
            return await run_one(ev)
        except (MLClientError, ScoringError) as exc:
            log.warning("simulation of %s failed: %s", ev.dialog_id, exc)
            return {"conversation_id": ev.dialog_id, "evaluation_id": ev.id, "error": str(exc)}

    dialogs = list(await asyncio.gather(*(guarded(ev) for ev in evals)))
    ok = [d for d in dialogs if "error" not in d]

    per: dict[str, dict[str, Any]] = {
        c["criterion_id"]: {
            **c,
            "fields": c.get("fields", []),
            "evaluated": 0,
            "changed": 0,
            "human_decided": 0,
            "agree_before": 0,
            "agree_after": 0,
        }
        for c in changed
    }
    for d in ok:
        for ch in d["changes"]:
            s = per.get(ch["criterion_id"])
            if s is None:
                continue
            s["evaluated"] += 1
            s["changed"] += int(ch["changed"])
            if ch["human_answer"] is not None:
                s["human_decided"] += 1
                s["agree_before"] += int(_same(ch["model_answer"], ch["human_answer"]))
                s["agree_after"] += int(_same(ch["new_answer"], ch["human_answer"]))

    deltas = [
        d["new_total"] - d["old_total"]
        for d in ok
        if d["new_total"] is not None and d["old_total"] is not None
    ]
    return {
        "checklist_version": checklist.version,
        "changed_criteria": changed,
        "guidelines_changed": guidelines_changed,
        "sample": len(dialogs),
        "dialogs_changed": sum(1 for d in ok if any(ch["changed"] for ch in d["changes"])),
        "score_changed": sum(1 for x in deltas if abs(x) >= 0.005),
        "avg_delta": round(sum(deltas) / len(deltas), 2) if deltas else None,
        "criteria": list(per.values()),
        "dialogs": dialogs,
        "failed": len(dialogs) - len(ok),
        "model": model,
        "usage": usage,
        "duration_ms": int((time.perf_counter() - t0) * 1000),
    }
