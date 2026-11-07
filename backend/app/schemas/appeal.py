from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import AnswerValue


class AppealDecision(BaseModel):
    decision: Literal["confirm", "change"]
    new_answer: AnswerValue | None = None
    reason: str = Field(min_length=1, max_length=4000)
    by: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.decision == "change" and self.new_answer is None:
            raise ValueError("new_answer is required when decision is 'change'")
        return self
