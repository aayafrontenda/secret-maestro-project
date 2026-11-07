"""The backend contract (backend/docs/ml-contract.md): request and response models and `evaluate`."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from pydantic import BaseModel, Field

from .facts import extract_facts
from .generic import GenericCriterion, evaluate_generic
from .ingest import parse_role, parse_time
from .llm import LLMClient
from .presets import extra_guidelines, match_standard
from .probes import Context
from .rules import DECIDERS, Decision
from .schemas import Message, Transcript
from .texts import rationale

LANGUAGES = {"RU": "ru", "KZ": "kk", "KK": "kk", "EN": "en"}

# ---------- request ----------


class TranscriptMessage(BaseModel):
    index: int = Field(ge=0)
    timestamp: str | None = None
    speaker: str
    text: str


class Criterion(BaseModel):
    code: str
    title: str
    rule: str
    section: str | None = None
    answer_type: Literal["yes_no", "scale"]
    scale_max: int | None = None
    scale_steps: list[dict[str, Any]] | None = None
    weight: float = 0
    allow_na: bool = False
    na_rule: str | None = None
    is_flag: bool = False


class EvaluateRequest(BaseModel):
    conversation_id: str
    channel: str = "agent chat"
    language: str = "RU"
    transcript: list[TranscriptMessage]
    criteria: list[Criterion]
    guidelines: list[str] = Field(
        default_factory=list, description="General rules from the checklist editor that apply to every criterion"
    )


# ---------- response ----------


class Range(BaseModel):
    from_index: int
    to_index: int


class CriterionResult(BaseModel):
    code: str
    answer: Literal["yes", "no", "na"] | int
    explanation: str = ""
    evidence: list[int] = Field(default_factory=list)
    checked_range: Range | None = None
    na_reason: str | None = None
    method: Literal["standard", "generic"] = Field(description="Built-in logic or the generic evaluator")
    standard_id: str | None = Field(default=None, description="Which standard criterion was recognised")
    facts: dict[str, bool] = Field(default_factory=dict, description="Answers to the narrow questions")
    review: "Review | None" = Field(default=None, description="Second-opinion check, when a check model is configured")


class Review(BaseModel):
    """Cascade check: the same criterion scored independently by a second model."""

    agrees: bool = Field(description="Both models gave the same answer")
    needs_review: bool = Field(description="The models disagree: send this criterion to a supervisor")
    second_answer: Literal["yes", "no", "na"] | int
    second_model: str


CriterionResult.model_rebuild()


class ModelInfo(BaseModel):
    provider: str = "ollama"
    name: str
    generic_name: str | None = Field(default=None, description="Model used for criteria without built-in rules, if different")
    check_name: str | None = Field(default=None, description="Second model used for the cascade check, if configured")


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0


class EvaluateResponse(BaseModel):
    conversation_id: str
    results: list[CriterionResult]
    model: ModelInfo
    usage: Usage
    duration_ms: int


# ---------- evaluation ----------


def to_transcript(request: EvaluateRequest) -> Transcript:
    messages = [
        Message(
            id=f"M{m.index}",
            role=parse_role(m.speaker),
            text=m.text.strip() or "[empty]",
            timestamp=parse_time(m.timestamp),
            time_text=m.timestamp,
        )
        for m in sorted(request.transcript, key=lambda m: m.index)
    ]
    return Transcript(chat_id=request.conversation_id, messages=messages)


def _index(message_id: str | None) -> int | None:
    return int(message_id[1:]) if message_id else None


def _scale_values(criterion: Criterion) -> list[int]:
    values = [int(step["value"]) for step in criterion.scale_steps or [] if "value" in step]
    if not values and criterion.scale_max is not None:
        values = list(range(criterion.scale_max + 1))
    return sorted(set(values), reverse=True)


def _fit_answer(answer: Any, criterion: Criterion) -> Any:
    """Keep the answer inside what the criterion allows, in case its settings were edited."""
    if answer == "na" and not criterion.allow_na:
        return 0 if criterion.answer_type == "scale" else "no"
    if criterion.answer_type == "scale" and isinstance(answer, int):
        values = _scale_values(criterion)
        if values and answer not in values:
            return min(values, key=lambda v: abs(v - answer))
    return answer


def _checked_range(ctx: Context, decision: Decision, preset_id: str) -> Range | None:
    """Where a missed action was expected, or the span checked for a violation that was not found."""
    messages = ctx.transcript.messages
    missed = decision.answer == "no" or decision.expected_at is not None
    if not missed:
        return None
    start = decision.expected_at or ctx.facts.first_operator_id or messages[0].id
    end = start if preset_id == "01" else messages[-1].id
    return Range(from_index=_index(start), to_index=_index(end))


def _standard_result(ctx: Context, criterion: Criterion, preset_id: str, language: str) -> CriterionResult:
    decision = DECIDERS[preset_id](ctx)
    text = rationale(preset_id, decision.answer, decision.facts, decision.na_reason, language)
    return CriterionResult(
        code=criterion.code,
        answer=_fit_answer(decision.answer, criterion),
        explanation=text,
        evidence=[_index(i) for i in decision.evidence],
        checked_range=_checked_range(ctx, decision, preset_id),
        na_reason=text if decision.answer == "na" else None,
        method="standard",
        standard_id=preset_id,
        facts=decision.facts,
    )


def _generic_result(
    ctx: Context, criterion: Criterion, language: str, guidelines: list[str], others: list[str] | None = None
) -> CriterionResult:
    labels = {int(s["value"]): str(s.get("label", "")) for s in criterion.scale_steps or [] if "value" in s}
    spec = GenericCriterion(
        key=criterion.code,
        title=criterion.title,
        rule=criterion.rule,
        answer_type=criterion.answer_type,
        allow_na=criterion.allow_na,
        na_rule=criterion.na_rule,
        is_flag=criterion.is_flag,
        scale=[(v, labels.get(v, "")) for v in _scale_values(criterion)],
        others=others or [],
    )
    result = evaluate_generic(ctx, spec, language, guidelines)
    answer = _fit_answer(result.answer, criterion)
    checked = None
    if answer == "no" and not result.evidence:
        messages = ctx.transcript.messages
        start = ctx.facts.first_operator_id or messages[0].id
        checked = Range(from_index=_index(start), to_index=_index(messages[-1].id))
    return CriterionResult(
        code=criterion.code,
        answer=answer,
        explanation=result.explanation,
        evidence=[_index(i) for i in result.evidence],
        checked_range=checked,
        na_reason=result.explanation if answer == "na" else None,
        method="generic",
    )


def _answer_all(
    request: EvaluateRequest, llm: LLMClient, generic_llm: LLMClient | None, language: str
) -> tuple[list[CriterionResult], list]:
    """One full pass over the checklist with one model (and its generic model). Returns results and traces."""
    transcript = to_transcript(request)
    guidelines = [g.strip() for g in request.guidelines if g and g.strip()]
    ctx = Context(
        transcript=transcript,
        facts=extract_facts(transcript, language),
        llm=llm,
        channel=request.channel,
        guidelines=extra_guidelines(guidelines),
    )
    # Same chat and the same trace list (so usage counts both models), another model.
    gctx = ctx if generic_llm is None else Context(
        transcript=transcript, facts=ctx.facts, llm=generic_llm, channel=request.channel,
        guidelines=ctx.guidelines, traces=ctx.traces,
    )

    results = []
    for criterion in request.criteria:
        preset_id = match_standard(criterion.rule, criterion.answer_type, criterion.is_flag, _scale_values(criterion))
        if preset_id is not None:
            results.append(_standard_result(ctx, criterion, preset_id, language))
        else:
            others = [c.title for c in request.criteria if c.code != criterion.code and c.title]
            results.append(_generic_result(gctx, criterion, language, guidelines, others))
    return results, [t for attempts in ctx.traces.values() for t in attempts]


def evaluate(
    request: EvaluateRequest,
    llm: LLMClient,
    generic_llm: LLMClient | None = None,
    check_llm: LLMClient | None = None,
) -> EvaluateResponse:
    """Answer every criterion of the request. Raises LLMUnavailable or LLMOutputError on failure.

    `generic_llm`, if given, scores the criteria without built-in rules (usually a stronger model);
    the built-in criteria keep using `llm`.
    `check_llm`, if given, scores the whole checklist again in parallel; every criterion gets a
    `review` saying whether the two models agree. A disagreement marks it for a supervisor.
    """
    started = time.perf_counter()
    language = LANGUAGES.get(request.language.strip().upper(), "ru")
    if check_llm is None:
        results, traces = _answer_all(request, llm, generic_llm, language)
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            main = pool.submit(_answer_all, request, llm, generic_llm, language)
            check = pool.submit(_answer_all, request, check_llm, None, language)
            results, traces = main.result()
            second, check_traces = check.result()
        traces = traces + check_traces
        by_code = {r.code: r for r in second}
        for r in results:
            other = by_code.get(r.code)
            if other is not None:
                agrees = r.answer == other.answer
                r.review = Review(agrees=agrees, needs_review=not agrees, second_answer=other.answer, second_model=check_llm.model)

    return EvaluateResponse(
        conversation_id=request.conversation_id,
        results=results,
        model=ModelInfo(
            name=llm.model,
            generic_name=generic_llm.model if generic_llm is not None else None,
            check_name=check_llm.model if check_llm is not None else None,
        ),
        usage=Usage(
            prompt_tokens=sum(t.prompt_tokens or 0 for t in traces),
            completion_tokens=sum(t.completion_tokens or 0 for t in traces),
            calls=len(traces),
            cost_usd=0.0,
        ),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
