import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

DATA = Path(__file__).resolve().parents[1] / "data" / "dev_dataset.json"


@pytest.fixture
def dev_dataset() -> dict:
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """App wired to a fresh temporary SQLite DB with the mock ML provider."""
    from app.core.config import Settings

    # Pin every setting to its default via env vars (they win over a developer's .env).
    for name, field in Settings.model_fields.items():
        default = field.default
        monkeypatch.setenv(
            name.upper(),
            ""
            if default is None
            else str(default).lower()
            if isinstance(default, bool)
            else str(default),
        )
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("ML_PROVIDER", "mock")
    monkeypatch.setenv("QUEUE_WORKERS", "2")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    from app.core import config, db

    config.get_settings.cache_clear()
    await db.dispose_engine()

    from app.main import create_app

    app = create_app(config.get_settings())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c

    await db.dispose_engine()
    config.get_settings.cache_clear()


@pytest.fixture
async def seeded(client: AsyncClient, dev_dataset: dict) -> AsyncClient:
    """Client with the 65 dev dialogs imported."""
    r = await client.post("/api/datasets/upload", json={"name": "DEV", "payload": dev_dataset})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture(autouse=True)
def _backend_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    # Environment variables set above take precedence over any developer .env file.
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
