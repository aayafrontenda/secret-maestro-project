import re
from typing import Protocol

from app.ml.schemas import MLEvaluateRequest, MLEvaluateResponse

# Model names of cloud APIs (an OpenRouter-style "google/gemini-..." prefix is ignored).
CLOUD_MODEL = re.compile(
    r"^(gpt|o\d|chatgpt|gemini|claude|glm|deepseek|kimi|grok|mistral-large)", re.I
)


def is_cloud_model(name: str | None) -> bool:
    return bool(name) and bool(CLOUD_MODEL.match(name.rsplit("/", 1)[-1]))


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
        attr = getattr(self._inner, item)
        if item == "suggest":
            # Optional capability (the ML service has it, other providers do not): gate it too.
            async def gated_suggest(request):
                async with self._gate:
                    return await attr(request)

            return gated_suggest
        return attr

    async def evaluate(self, request: MLEvaluateRequest) -> MLEvaluateResponse:
        async with self._gate:
            return await self._inner.evaluate(request)

    async def health(self) -> bool:
        return await self._inner.health()

    async def aclose(self) -> None:
        await self._inner.aclose()
