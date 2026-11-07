"""Contract between the backend and the ML evaluation service.

The backend sends one request per (dialog, checklist); the ML service answers every criterion.
Scoring (weights, N/A redistribution, totals) is done by the backend, not by the model.
See docs/ml-contract.md.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import AnswerValue


class MLTranscriptMessage(BaseModel):
    index: int
    timestamp: str
    speaker: str
    text: str


class MLCriterion(BaseModel):
    code: str
    title: str
    rule: str
    section: str | None = None
    answer_type: str  # yes_no | scale
    scale_max: int | None = None
    scale_steps: list[dict[str, Any]] | None = None
    weight: float
    allow_na: bool
    na_rule: str | None = None
    is_flag: bool = False


class MLEvaluateRequest(BaseModel):
    conversation_id: str
    channel: str
    language: str
    transcript: list[MLTranscriptMessage]
    criteria: list[MLCriterion]


class MLRange(BaseModel):
    from_index: int = Field(ge=0)
    to_index: int = Field(ge=0)


class MLCriterionResult(BaseModel):
    code: str
    answer: AnswerValue
    explanation: str = ""
    evidence: list[int] = Field(
        default_factory=list, description="Transcript message indexes supporting the verdict"
    )
    checked_range: MLRange | None = Field(
        default=None, description="Transcript span inspected when an expected action is missing"
    )
    na_reason: str | None = None


class MLModelInfo(BaseModel):
    provider: str = "unknown"
    name: str = "unknown"


class MLUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0


class MLEvaluateResponse(BaseModel):
    conversation_id: str | None = None
    results: list[MLCriterionResult]
    model: MLModelInfo = Field(default_factory=MLModelInfo)
    usage: MLUsage | None = None
