from typing import Protocol

from app.ml.schemas import MLEvaluateRequest, MLEvaluateResponse


class MLClientError(RuntimeError):
    """The ML service could not produce a usable answer."""


class MLClient(Protocol):
    name: str

    async def evaluate(self, request: MLEvaluateRequest) -> MLEvaluateResponse: ...

    async def health(self) -> bool: ...

    async def aclose(self) -> None: ...


class GatedMLClient:
    """Runs evaluations under a shared lock: one GPU, one request at a time."""

    def __init__(self, inner: MLClient, gate) -> None:
        self._inner = inner
        self._gate = gate
        self.name = inner.name

    def __getattr__(self, item):
        return getattr(self._inner, item)

    async def evaluate(self, request: MLEvaluateRequest) -> MLEvaluateResponse:
        async with self._gate:
            return await self._inner.evaluate(request)

    async def health(self) -> bool:
        return await self._inner.health()

    async def aclose(self) -> None:
        await self._inner.aclose()
