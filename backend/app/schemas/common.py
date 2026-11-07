from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

AnswerValue = Annotated[
    Literal["yes", "no", "na"] | int | float,
    Field(description='"yes" | "no" | "na" | number (scale criteria)'),
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class Message(BaseModel):
    detail: str
