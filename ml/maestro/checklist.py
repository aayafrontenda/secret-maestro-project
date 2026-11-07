"""Checklist definition: weights, answer types and allowed values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Answer = Literal["yes", "no", "na"] | int


@dataclass(frozen=True)
class Criterion:
    id: str
    name: str
    weight: int
    na_allowed: bool
    levels: tuple[int, ...] = ()  # non-empty only for scale criteria

    @property
    def is_scale(self) -> bool:
        return bool(self.levels)


CRITERIA: tuple[Criterion, ...] = (
    Criterion("01", "Establishing contact", 10, na_allowed=False),
    Criterion("02", "Needs discovery", 15, na_allowed=True),
    Criterion("03", "Identification", 20, na_allowed=True),
    Criterion("04", "Correct and complete consultation", 20, na_allowed=True, levels=(0, 5, 10, 15, 20)),
    Criterion("05", "Empathy and customer focus", 15, na_allowed=False),
    Criterion("06", "Dialogue management, speed and literacy", 15, na_allowed=False, levels=(0, 4, 7, 10)),
    Criterion("07", "Closing", 5, na_allowed=True),
    Criterion("08", "Gross violations", 0, na_allowed=False),
)

BY_ID: dict[str, Criterion] = {c.id: c for c in CRITERIA}
WEIGHTED: tuple[Criterion, ...] = tuple(c for c in CRITERIA if c.weight > 0)


def is_valid_answer(criterion: Criterion, answer: object) -> bool:
    if answer == "na":
        return criterion.na_allowed
    if criterion.is_scale:
        return isinstance(answer, int) and not isinstance(answer, bool) and answer in criterion.levels
    return answer in ("yes", "no")
