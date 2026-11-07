from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel

AnswerType = Literal["yes_no", "scale"]


class ScaleStep(BaseModel):
    value: int = Field(ge=0)
    label: str = ""


class CriterionIn(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9_\-]+$",
        description="Stable key within the checklist (e.g. c1). Used in the ML contract.",
    )
    title: str = Field(min_length=1, max_length=200)
    rule: str = Field(default="", description="How to decide Yes/No or the scale level")
    section: str | None = Field(default=None, max_length=200)
    answer_type: AnswerType
    scale_max: int | None = Field(default=None, gt=0)
    scale_steps: list[ScaleStep] | None = None
    weight: float = Field(ge=0)
    allow_na: bool = False
    na_rule: str | None = Field(default=None, description="When N/A applies")
    is_flag: bool = Field(
        default=False, description="Flag-only criterion: no points, reported separately"
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.answer_type == "scale":
            if self.scale_max is None:
                raise ValueError("scale criteria require scale_max")
            if self.scale_steps:
                values = [s.value for s in self.scale_steps]
                if max(values) != self.scale_max:
                    raise ValueError("the top scale step must equal scale_max")
                if len(set(values)) != len(values):
                    raise ValueError("scale steps must be unique")
            if self.is_flag:
                raise ValueError("flag criteria must be yes_no")
        else:
            self.scale_max = None
            self.scale_steps = None
        if self.is_flag:
            self.weight = 0.0
        elif self.weight <= 0:
            raise ValueError("non-flag criteria need a positive weight")
        return self


class ChecklistIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    criteria: list[CriterionIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        codes = [c.code for c in self.criteria]
        if len(set(codes)) != len(codes):
            raise ValueError("criterion codes must be unique within a checklist")
        if not any(not c.is_flag for c in self.criteria):
            raise ValueError("a checklist needs at least one scored criterion")
        return self


class CriterionOut(ORMModel):
    id: int
    code: str
    position: int
    title: str
    rule: str
    section: str | None
    answer_type: AnswerType
    scale_max: int | None
    scale_steps: list[ScaleStep] | None
    weight: float
    allow_na: bool
    na_rule: str | None
    is_flag: bool


class ChecklistSummary(ORMModel):
    id: int
    name: str
    description: str | None
    is_default: bool
    version: int
    created_at: datetime
    updated_at: datetime
    criteria_count: int = 0
    total_weight: float = 0.0


class ChecklistOut(ChecklistSummary):
    criteria: list[CriterionOut]
