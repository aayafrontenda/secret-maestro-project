"""Several evaluation providers at once; the active one can be switched at runtime.

Cloud (OpenAI-compatible API), local (the ML team's service on this machine) and the
built-in mock are created when configured; the UI picks which one grades new evaluations.
The choice survives restarts in a small JSON file next to the database.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from app.ml.base import MLClient
from app.ml.schemas import MLEvaluateRequest, MLEvaluateResponse

log = logging.getLogger(__name__)

CLOUD_MODEL = re.compile(r"^(gpt|o\d|chatgpt|gemini|claude|glm|deepseek|kimi|grok|mistral-large)", re.I)


@dataclass
class Provider:
    id: str  # openai | http | mock
    kind: str  # cloud | local | demo
    model: str | None
    endpoint: str | None


class SwitchableMLClient:
    def __init__(
        self,
        clients: dict[str, MLClient],
        providers: dict[str, Provider],
        default: str,
        state_file: Path | None = None,
    ) -> None:
        if default not in clients:
            raise RuntimeError(f"ML provider '{default}' is not configured")
        self._clients = clients
        self._providers = providers
        self._state_file = state_file
        self.active = self._load() or default

    # --- selection ------------------------------------------------------------------------------

    def _load(self) -> str | None:
        if not self._state_file or not self._state_file.exists():
            return None
        try:
            chosen = json.loads(self._state_file.read_text()).get("ml_provider")
        except (OSError, ValueError):
            return None
        return chosen if chosen in self._clients else None

    def switch(self, provider: str) -> None:
        if provider not in self._clients:
            raise KeyError(provider)
        self.active = provider
        if self._state_file:
            try:
                self._state_file.parent.mkdir(parents=True, exist_ok=True)
                self._state_file.write_text(json.dumps({"ml_provider": provider}))
            except OSError as exc:
                log.warning("could not persist ML provider choice: %s", exc)
        log.info("ML provider switched to %s", provider)

    async def describe(self) -> dict[str, Any]:
        items = []
        for pid, p in self._providers.items():
            client = self._clients[pid]
            try:
                status = getattr(client, "status", None)
                if status is not None:
                    # The ML service names its model; its URL (e.g. http://ml:8001 in Docker)
                    # does not tell whether that model is local, the name does.
                    reachable, model = await status()
                    if model:
                        kind = "cloud" if CLOUD_MODEL.match(model.rsplit("/", 1)[-1]) else "local"
                        p = replace(p, model=model, kind=kind)
                else:
                    reachable = await client.health()
            except Exception:  # noqa: BLE001
                reachable = False
            items.append({**asdict(p), "active": pid == self.active, "reachable": reachable})
        return {"active": self.active, "providers": items}

    # --- MLClient -------------------------------------------------------------------------------

    @property
    def current(self) -> MLClient:
        return self._clients[self.active]

    @property
    def name(self) -> str:
        return self.current.name

    def __getattr__(self, item: str) -> Any:
        return getattr(self._clients[self.__dict__["active"]], item)

    async def evaluate(self, request: MLEvaluateRequest) -> MLEvaluateResponse:
        return await self.current.evaluate(request)

    async def health(self) -> bool:
        return await self.current.health()

    def suggester(self) -> MLClient | None:
        """A client that can suggest operator replies: the active one if it can, else the ML service."""
        for client in (self.current, self._clients.get("http")):
            if client is not None and hasattr(client, "suggest"):
                return client
        return None

    async def aclose(self) -> None:
        for c in self._clients.values():
            try:
                await c.aclose()
            except Exception as exc:  # noqa: BLE001
                log.warning("closing ML client failed: %s", exc)
