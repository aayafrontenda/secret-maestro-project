"""Switching the evaluation provider at runtime."""

from pathlib import Path

from httpx import AsyncClient

from app.core.config import Settings
from app.ml import build_ml_clients
from app.ml.mock import MockMLClient
from app.ml.switch import Provider, SwitchableMLClient


class Named(MockMLClient):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.model = f"{name}-model"


def _switch(tmp_path: Path, default: str = "a") -> SwitchableMLClient:
    return SwitchableMLClient(
        {"a": Named("a"), "b": Named("b")},
        {"a": Provider("a", "cloud", "m", None), "b": Provider("b", "local", None, None)},
        default,
        state_file=tmp_path / "rt.json",
    )


async def test_switch_persists_and_delegates(tmp_path: Path):
    ml = _switch(tmp_path)
    assert ml.name == "a" and ml.model == "a-model"
    ml.switch("b")
    assert ml.name == "b" and ml.model == "b-model"
    assert _switch(tmp_path).active == "b"  # restored after a restart
    desc = await ml.describe()
    assert desc["active"] == "b"
    assert [p["id"] for p in desc["providers"]] == ["a", "b"]
    assert desc["providers"][1] == {
        "id": "b",
        "kind": "local",
        "model": None,
        "endpoint": None,
        "active": True,
        "reachable": True,
    }


async def test_unknown_saved_choice_falls_back(tmp_path: Path):
    (tmp_path / "rt.json").write_text('{"ml_provider": "gone"}')
    assert _switch(tmp_path).active == "a"


def test_builds_every_configured_provider(tmp_path: Path):
    from app.ml.openai import OpenAIChat

    chat = OpenAIChat(api_key="k", base_url="https://api.openai.com/v1", model="gpt-x")
    settings = Settings(
        ml_provider="http",
        ml_service_url="http://127.0.0.1:8001",
        openai_api_key="k",
        runtime_state_file=tmp_path / "rt.json",
    )
    ml = build_ml_clients(settings, chat)
    assert ml.active == "http"
    assert {k: (p.kind, p.model) for k, p in ml._providers.items()} == {
        "openai": ("cloud", "gpt-x"),
        "http": ("local", None),
        "mock": ("demo", "heuristics"),
    }


async def test_api(client: AsyncClient):
    data = (await client.get("/api/ml")).json()
    assert data["active"] == "mock" and [p["id"] for p in data["providers"]] == ["mock"]
    r = await client.put("/api/ml", json={"provider": "openai"})
    assert r.status_code == 404 and "openai" in r.json()["error"]
    r = await client.put("/api/ml", json={"provider": "mock"})
    assert r.status_code == 200 and r.json()["active"] == "mock"
