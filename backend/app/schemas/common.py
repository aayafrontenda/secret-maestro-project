from typing import Annotated, Literal

from pydantic import Field

AnswerValue = Annotated[
    Literal["yes", "no", "na"] | int | float,
    Field(description='"yes" | "no" | "na" | number (scale criteria)'),
]
