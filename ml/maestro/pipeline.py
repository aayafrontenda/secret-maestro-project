"""Score one transcript end to end."""

from __future__ import annotations

import time
from typing import Callable

from .checklist import CRITERIA, WEIGHTED
from .facts import extract_facts
from .llm import LLMClient, LLMOutputError
from .probes import Context
from .rules import DECIDERS
from .schemas import CriterionResult, Evidence, GrossViolation, ScoreResult, Transcript
from .scoring import compute
from .texts import TEXTS, Language, rationale

QUOTE_LIMIT = 400
Progress = Callable[[int, int, str], None]


def _evidence(ctx: Context, message_ids: list[str]) -> list[Evidence]:
    items = []
    for message_id in message_ids:
        message = ctx.message(message_id)
        if message is None:
            continue
        quote = message.text if len(message.text) <= QUOTE_LIMIT else message.text[: QUOTE_LIMIT - 1] + "…"
        items.append(Evidence(message_id=message.id, role=message.role, quote=quote))
    return items


def score_transcript(
    transcript: Transcript,
    llm: LLMClient,
    output_language: Language = "ru",
    on_progress: Progress | None = None,
) -> ScoreResult:
    """Score a chat. Raises LLMUnavailable if the model backend cannot be reached."""
    started = time.perf_counter()
    ctx = Context(transcript=transcript, facts=extract_facts(transcript), llm=llm)
    results: list[CriterionResult] = []

    for index, criterion in enumerate(CRITERIA):
        if on_progress:
            on_progress(index, len(CRITERIA), criterion.id)
        known_probes = set(ctx.traces)
        base = {"criterion_id": criterion.id, "name": criterion.name, "weight": criterion.weight}
        try:
            decision = DECIDERS[criterion.id](ctx)
        except LLMOutputError as exc:
            result = CriterionResult(
                **base, status="failed", rationale=TEXTS[output_language]["failed"], error=str(exc)
            )
        else:
            result = CriterionResult(
                **base,
                status="scored",
                answer=decision.answer,
                rationale=rationale(criterion.id, decision.answer, decision.facts, decision.na_reason, output_language),
                evidence=_evidence(ctx, decision.evidence),
                expected_at=decision.expected_at,
                facts=decision.facts,
            )
        result.attempts = [trace for key in ctx.traces if key not in known_probes for trace in ctx.traces[key]]
        results.append(result)
    if on_progress:
        on_progress(len(CRITERIA), len(CRITERIA), "")

    by_id = {r.criterion_id: r for r in results}
    weighted_ok = all(by_id[c.id].status == "scored" for c in WEIGHTED)
    final_score = None
    if weighted_ok:
        breakdown = compute({c.id: by_id[c.id].answer for c in WEIGHTED})
        final_score = breakdown.final_score
        for c in WEIGHTED:
            by_id[c.id].raw_points = breakdown.raw_points[c.id]
            by_id[c.id].points = breakdown.points[c.id]

    gross = by_id["08"]
    gross_violation = (
        GrossViolation(flag=gross.answer == "yes", **{k: v for k, v in gross.facts.items()})
        if gross.status == "scored"
        else None
    )
    return ScoreResult(
        chat_id=transcript.chat_id,
        status="scored" if all(r.status == "scored" for r in results) else "partial",
        final_score=final_score,
        gross_violation=gross_violation,
        criteria=results,
        output_language=output_language,
        model=llm.model,
        llm_calls=sum(len(traces) for traces in ctx.traces.values()),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
