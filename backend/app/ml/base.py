from typing import Protocol

from app.ml.schemas import MLEvaluateRequest, MLEvaluateResponse


class MLClientError(RuntimeError):
    """The ML service could not produce a usable answer."""


class MLClient(Protocol):
    name: str

    async def evaluate(self, request: MLEvaluateRequest) -> MLEvaluateResponse: ...

    async def health(self) -> bool: ...

    async def aclose(self) -> None: ...
