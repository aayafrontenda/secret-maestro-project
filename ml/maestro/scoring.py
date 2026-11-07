"""Deterministic score calculation from page 2 of the checklist. No LLM involved."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import floor
from typing import Mapping

from .checklist import BY_ID, WEIGHTED, Answer, Criterion, is_valid_answer


class InvalidAnswer(ValueError):
    pass


@dataclass(frozen=True)
class Breakdown:
    final_score: float | None
    applicable_weight: int
    raw_points: dict[str, float | None]  # before redistribution; None means N/A
    points: dict[str, float | None]  # after redistribution


def round2(value: Fraction) -> float:
    """Round to two decimals, half up, without binary floating point errors."""
    return float(Fraction(floor(value * 100 + Fraction(1, 2)), 100))


def _share(criterion: Criterion, answer: Answer) -> Fraction:
    if criterion.is_scale:
        return Fraction(int(answer), max(criterion.levels))
    return Fraction(1) if answer == "yes" else Fraction(0)


def compute(answers: Mapping[str, Answer]) -> Breakdown:
    """Compute the final score. Criterion 08 is validated but carries no points."""
    for cid, answer in answers.items():
        criterion = BY_ID.get(cid)
        if criterion is None:
            raise InvalidAnswer(f"unknown criterion {cid!r}")
        if not is_valid_answer(criterion, answer):
            raise InvalidAnswer(f"criterion {cid}: invalid value {answer!r}")

    missing = [c.id for c in WEIGHTED if c.id not in answers]
    if missing:
        raise InvalidAnswer(f"missing answers for criteria: {', '.join(missing)}")

    applicable = [c for c in WEIGHTED if answers[c.id] != "na"]
    applicable_weight = sum(c.weight for c in applicable)

    raw: dict[str, float | None] = {c.id: None for c in WEIGHTED}
    points: dict[str, float | None] = {c.id: None for c in WEIGHTED}
    if applicable_weight == 0:
        return Breakdown(None, 0, raw, points)

    total = Fraction(0)
    for c in applicable:
        earned = _share(c, answers[c.id]) * c.weight
        redistributed = earned * 100 / applicable_weight
        total += redistributed
        raw[c.id] = round2(earned)
        points[c.id] = round2(redistributed)

    return Breakdown(round2(total), applicable_weight, raw, points)
