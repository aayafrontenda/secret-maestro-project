"""Data models and the result contract."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Role(StrEnum):
    CLIENT = "client"
    OPERATOR = "operator"
    SYSTEM = "system"
    BOT = "bot"


class Message(BaseModel):
    id: str
    role: Role
    text: str
    timestamp: datetime | None = None


class Transcript(BaseModel):
    chat_id: str
    messages: list[Message]


class Evidence(BaseModel):
    message_id: str
    role: Role
    quote: str = Field(description="Text of the cited message, taken from the transcript by code")


class AttemptTrace(BaseModel):
    probe: str
    prompt_sha256: str
    raw_response: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    duration_ms: int
    error: str | None = None


class CriterionResult(BaseModel):
    criterion_id: str
    name: str
    weight: int
    status: Literal["scored", "failed"]
    answer: Literal["yes", "no", "na"] | int | None = Field(
        default=None, description="yes/no/na or a scale level; null when status is failed"
    )
    raw_points: float | None = Field(default=None, description="Points before N/A redistribution")
    points: float | None = Field(default=None, description="Points in the final score out of 100")
    rationale: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    expected_at: str | None = Field(default=None, description="Message where a missed action was expected")
    facts: dict[str, bool] = Field(default_factory=dict, description="Answers to the narrow questions")
    error: str | None = None
    attempts: list[AttemptTrace] = Field(default_factory=list)


class GrossViolation(BaseModel):
    flag: bool
    insult: bool = False
    off_company_offer: bool = False
    confidential_disclosure: bool = False


class ScoreResult(BaseModel):
    chat_id: str
    status: Literal["scored", "partial"] = Field(description="partial: at least one criterion was not scored")
    final_score: float | None = Field(description="0-100; null if the score cannot be computed")
    gross_violation: GrossViolation | None = Field(description="null if criterion 08 was not scored")
    criteria: list[CriterionResult]
    output_language: Literal["ru", "kk", "en"]
    model: str
    llm_calls: int
    duration_ms: int
