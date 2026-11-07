from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import AnswerValue, ORMModel


class EvaluationCreate(BaseModel):
    dialog_id: str
    checklist_id: int | None = Field(default=None, description="Defaults to the default checklist")


class EvaluationBatchCreate(BaseModel):
    dialog_ids: list[str] | None = Field(default=None, description="Omit to evaluate every dialog")
    checklist_id: int | None = None
    # Skip dialogs that already have a completed evaluation with this checklist version.
    skip_evaluated: bool = False

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.dialog_ids is not None and len(self.dialog_ids) == 0:
            raise ValueError("dialog_ids must be omitted or non-empty")
        return self


class EvaluationBatchResult(BaseModel):
    batch_id: str
    checklist_id: int
    evaluation_ids: list[int]
    queued: int
    skipped: int


class EvidenceItem(BaseModel):
    message_index: int
    timestamp: str | None = None
    speaker: str | None = None
    text: str | None = None


class CheckedRange(BaseModel):
    from_index: int
    to_index: int


class AppealBrief(ORMModel):
    id: int
    status: str
    comment: str
    previous_answer: Any
    new_answer: Any | None
    decision_reason: str | None
    created_at: datetime
    decided_at: datetime | None


class CriterionResultOut(ORMModel):
    id: int
    criterion_code: str
    criterion_title: str
    position: int
    section: str | None
    answer_type: str
    is_flag: bool
    weight: float
    answer: Any
    score: float | None
    effective_weight: float | None
    explanation: str
    evidence: list[EvidenceItem]
    checked_range: CheckedRange | None
    na_reason: str | None
    normalization_note: str | None
    final_answer: Any
    final_score: float | None
    final_effective_weight: float | None
    appeals: list[AppealBrief] = []


class SectionOut(BaseModel):
    name: str
    points: float
    max_points: float
    criteria: list[str]


class EvaluationOut(ORMModel):
    id: int
    dialog_id: str
    checklist_id: int | None
    checklist_snapshot: dict[str, Any]
    status: str
    error: str | None
    batch_id: str | None
    provider: str | None
    model_name: str | None
    usage: dict[str, Any] | None
    original_total: float | None
    original_sections: list[SectionOut] | None
    grave_error: bool
    final_total: float | None
    final_sections: list[SectionOut] | None
    final_grave_error: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    results: list[CriterionResultOut]


class EvaluationListItem(ORMModel):
    id: int
    dialog_id: str
    checklist_id: int | None
    status: str
    error: str | None
    batch_id: str | None
    original_total: float | None
    final_total: float | None
    grave_error: bool
    final_grave_error: bool
    created_at: datetime
    completed_at: datetime | None


# --- appeals ---


class AppealCreate(BaseModel):
    criterion_result_id: int
    comment: str = Field(min_length=1, max_length=4000)


class AppealDecision(BaseModel):
    decision: Literal["confirm", "change"]
    new_answer: AnswerValue | None = None
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.decision == "change" and self.new_answer is None:
            raise ValueError("new_answer is required when decision is 'change'")
        return self


class AppealOut(ORMModel):
    id: int
    evaluation_id: int
    criterion_result_id: int
    criterion_code: str
    criterion_title: str
    dialog_id: str
    comment: str
    status: str
    previous_answer: Any
    new_answer: Any | None
    decision_reason: str | None
    created_at: datetime
    decided_at: datetime | None


class AppealDetail(AppealOut):
    """What the reviewer sees: the disputed verdict, the evidence and the transcript fragment."""

    explanation: str
    evidence: list[EvidenceItem]
    checked_range: CheckedRange | None
    original_score: float | None
    weight: float
    answer_type: str
    scale_max: int | None
    allow_na: bool
    is_flag: bool
    fragment: list[dict[str, Any]] = Field(description="Transcript messages around the evidence")
    evaluation_original_total: float | None
    evaluation_final_total: float | None
