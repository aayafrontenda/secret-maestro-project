"""Checklist scoring rules.

Implements the calculation order from the Freedom Broker checklist:

1. Applicability: N/A is only accepted where the criterion allows it.
2. Yes gives the full weight, No gives zero. Scale answers map proportionally so that the top
   step gives the full weight.
3. N/A criteria are excluded and their weight is redistributed proportionally among the
   applicable ones, so the maximum stays at 100.
4. Flag-only criteria (grave errors) carry no points and are reported separately.
5. The total is rounded to two decimals; if no weighted applicable criteria remain, no total
   is produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Answer = Literal["yes", "no", "na"] | int | float
TOTAL_MAX = 100.0


class ScoringError(ValueError):
    pass


@dataclass(frozen=True)
class CriterionSpec:
    code: str
    title: str
    answer_type: Literal["yes_no", "scale"]
    weight: float = 0.0
    allow_na: bool = False
    is_flag: bool = False
    section: str | None = None
    scale_max: int | None = None
    scale_steps: tuple[int, ...] | None = None
    position: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CriterionSpec:
        steps = data.get("scale_steps")
        step_values: tuple[int, ...] | None = None
        if steps:
            step_values = tuple(
                sorted({int(s["value"] if isinstance(s, dict) else s) for s in steps}, reverse=True)
            )
        return cls(
            code=data["code"],
            title=data.get("title", data["code"]),
            answer_type=data["answer_type"],
            weight=float(data.get("weight") or 0.0),
            allow_na=bool(data.get("allow_na", False)),
            is_flag=bool(data.get("is_flag", False)),
            section=data.get("section"),
            scale_max=data.get("scale_max"),
            scale_steps=step_values,
            position=int(data.get("position", 0)),
        )


@dataclass
class CriterionScore:
    code: str
    answer: Answer
    applicable: bool
    ratio: float | None  # share of the criterion's weight earned (0..1), None if N/A
    weight: float
    effective_weight: float | None  # weight after N/A redistribution
    points: float | None  # ratio * effective_weight
    normalization_note: str | None = None


@dataclass
class SectionScore:
    name: str
    points: float
    max_points: float
    criteria: list[str] = field(default_factory=list)


@dataclass
class ScoreReport:
    total: float | None
    max_total: float
    criteria: list[CriterionScore]
    sections: list[SectionScore]
    grave_error: bool
    flags: dict[str, bool]


def normalize_answer(spec: CriterionSpec, raw: Any) -> tuple[Answer, str | None]:
    """Coerce a model/user answer into a valid answer for the criterion.

    Returns the normalized answer and a note when something had to be corrected.
    """
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in {"n/a", "na", "not applicable", "none", "null", ""}:
            raw = "na"
        elif token in {"yes", "да", "true", "иә"}:
            raw = "yes"
        elif token in {"no", "нет", "false", "жоқ"}:
            raw = "no"
        else:
            raw = token

    if raw == "na":
        if spec.allow_na:
            return "na", None
        fallback: Answer = "no" if spec.answer_type == "yes_no" else 0
        return fallback, f"N/A is not allowed for '{spec.code}'; treated as {fallback!r}"

    if spec.answer_type == "yes_no":
        if isinstance(raw, bool):
            return ("yes" if raw else "no"), None
        if raw in ("yes", "no"):
            return raw, None
        if isinstance(raw, int | float):
            return ("yes" if raw > 0 else "no"), f"numeric answer {raw!r} coerced to yes/no"
        raise ScoringError(f"invalid yes/no answer for '{spec.code}': {raw!r}")

    # scale
    if spec.scale_max is None or spec.scale_max <= 0:
        raise ScoringError(f"scale criterion '{spec.code}' has no positive scale_max")
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        raise ScoringError(f"invalid scale answer for '{spec.code}': {raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ScoringError(f"invalid scale answer for '{spec.code}': {raw!r}") from exc

    note = None
    clamped = min(max(value, 0.0), float(spec.scale_max))
    if clamped != value:
        note = f"scale answer {value} clamped to [0, {spec.scale_max}]"
        value = clamped
    if spec.scale_steps:
        nearest = min(spec.scale_steps, key=lambda s: (abs(s - value), -s))
        if nearest != value:
            note = f"scale answer {value} snapped to nearest step {nearest}"
            value = float(nearest)
    if value.is_integer():
        return int(value), note
    return value, note


def _ratio(spec: CriterionSpec, answer: Answer) -> float | None:
    if answer == "na":
        return None
    if spec.answer_type == "yes_no":
        return 1.0 if answer == "yes" else 0.0
    assert spec.scale_max  # validated in normalize_answer
    return float(answer) / float(spec.scale_max)


def score(specs: list[CriterionSpec], answers: dict[str, Any]) -> ScoreReport:
    """Compute per-criterion points and the weighted total for a set of answers.

    `answers` maps criterion code -> raw answer. Missing answers raise ScoringError.
    """
    missing = [s.code for s in specs if s.code not in answers]
    if missing:
        raise ScoringError(f"missing answers for criteria: {', '.join(missing)}")

    normalized: dict[str, tuple[Answer, str | None]] = {
        s.code: normalize_answer(s, answers[s.code]) for s in specs
    }

    weighted = [s for s in specs if not s.is_flag and s.weight > 0]
    applicable = [s for s in weighted if normalized[s.code][0] != "na"]
    applicable_weight = sum(s.weight for s in applicable)
    scale = TOTAL_MAX / applicable_weight if applicable_weight > 0 else None

    criteria: list[CriterionScore] = []
    flags: dict[str, bool] = {}
    for spec in sorted(specs, key=lambda s: (s.position, s.code)):
        answer, note = normalized[spec.code]
        if spec.is_flag:
            flags[spec.code] = answer == "yes"
            criteria.append(
                CriterionScore(
                    code=spec.code,
                    answer=answer,
                    applicable=answer != "na",
                    ratio=None,
                    weight=0.0,
                    effective_weight=None,
                    points=None,
                    normalization_note=note,
                )
            )
            continue

        ratio = _ratio(spec, answer)
        is_applicable = ratio is not None and spec.weight > 0
        effective_weight = (
            round(spec.weight * scale, 4) if (is_applicable and scale is not None) else None
        )
        points = (
            round(ratio * effective_weight, 2)
            if (ratio is not None and effective_weight is not None)
            else None
        )
        criteria.append(
            CriterionScore(
                code=spec.code,
                answer=answer,
                applicable=is_applicable,
                ratio=ratio,
                weight=spec.weight,
                effective_weight=effective_weight,
                points=points,
                normalization_note=note,
            )
        )

    total: float | None = None
    if applicable:
        exact = sum(
            (_ratio(s, normalized[s.code][0]) or 0.0) * s.weight * (scale or 0.0)
            for s in applicable
        )
        total = round(exact, 2)

    sections = _sections(specs, criteria)
    grave = any(flags.values())
    return ScoreReport(
        total=total,
        max_total=TOTAL_MAX if applicable else 0.0,
        criteria=criteria,
        sections=sections,
        grave_error=grave,
        flags=flags,
    )


def _sections(specs: list[CriterionSpec], scored: list[CriterionScore]) -> list[SectionScore]:
    by_code = {c.code: c for c in scored}
    order: list[str] = []
    buckets: dict[str, SectionScore] = {}
    for spec in sorted(specs, key=lambda s: (s.position, s.code)):
        if not spec.section or spec.is_flag:
            continue
        if spec.section not in buckets:
            buckets[spec.section] = SectionScore(name=spec.section, points=0.0, max_points=0.0)
            order.append(spec.section)
        cs = by_code[spec.code]
        bucket = buckets[spec.section]
        bucket.criteria.append(spec.code)
        if cs.points is not None and cs.effective_weight is not None:
            bucket.points = round(bucket.points + cs.points, 2)
            bucket.max_points = round(bucket.max_points + cs.effective_weight, 2)
    return [buckets[name] for name in order]
