"""Client for the organizer's dataset API and parser for its response format."""

import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.schemas.dialog import DialogIn


class OrganizerError(RuntimeError):
    pass


class OrganizerDataset(BaseModel):
    dataset_group_id: str | None = None
    total_records: int | None = None
    records: list[DialogIn]


def parse_dataset(payload: Any) -> OrganizerDataset:
    """Accepts the organizer envelope, a bare `data` object, or a bare list of records."""
    if isinstance(payload, list):
        payload = {"records": payload}
    if not isinstance(payload, dict):
        raise OrganizerError("dataset must be a JSON object or array")
    if "isSuccess" in payload or "data" in payload:
        if payload.get("isSuccess") is False:
            raise OrganizerError(f"organizer API error: {payload.get('error') or 'unknown'}")
        payload = payload.get("data") or {}
    try:
        return OrganizerDataset.model_validate(payload)
    except ValidationError as exc:
        raise OrganizerError(f"invalid dataset format: {exc.errors()[:3]}") from exc


def load_dataset_file(path: Path | str) -> OrganizerDataset:
    with open(path, encoding="utf-8") as f:
        return parse_dataset(json.load(f))


async def fetch_dataset(api_url: str, group_id: str, timeout_s: float = 60.0) -> OrganizerDataset:
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
        try:
            resp = await client.get(api_url, params={"group_id": group_id})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OrganizerError(f"organizer API request failed: {exc}") from exc
        try:
            payload = resp.json()
        except ValueError as exc:
            raise OrganizerError("organizer API returned non-JSON body") from exc
    return parse_dataset(payload)
