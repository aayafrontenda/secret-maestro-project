import asyncio
import logging
from pathlib import Path

from alembic.config import Config

from alembic import command

log = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.attributes["database_url"] = database_url
    return cfg


def _upgrade(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")


async def run_migrations(database_url: str) -> None:
    """Apply pending Alembic migrations. Runs in a thread because Alembic is synchronous."""
    if database_url.startswith("sqlite"):
        path = database_url.split("///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    log.info("applying database migrations")
    await asyncio.to_thread(_upgrade, database_url)
