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


FIELD_NAMES = {
    "conversation_id": "conversation_id",
    "channel": "channel",
    "language": "language",
    "transcript": "transcript",
    "speaker": "speaker",
    "timestamp": "timestamp",
    "text": "text",
}


def _describe(errors: list[dict[str, Any]]) -> str:
    """One readable line for the UI instead of pydantic's dump."""
    first = errors[0]
    loc = [p for p in first.get("loc", ()) if p != "records"]
    if not loc:
        return "запись без обязательных полей"
    parts = []
    if isinstance(loc[0], int):
        parts.append(f"запись {loc[0] + 1}")
        loc = loc[1:]
    if loc and loc[0] == "transcript" and len(loc) > 1 and isinstance(loc[1], int):
        parts.append(f"реплика {loc[1] + 1}")
        loc = [loc[0], *loc[2:]]
    field = loc[-1] if loc else None
    what = "нет поля" if first.get("type") == "missing" else "неверное поле"
    if field is not None:
        parts.append(f"{what} «{FIELD_NAMES.get(str(field), field)}»")
    more = f" (и ещё ошибок: {len(errors) - 1})" if len(errors) > 1 else ""
    return ", ".join(parts) + more


def parse_dataset(payload: Any) -> OrganizerDataset:
    """Accepts the organizer envelope, a bare `data` object, or a bare list of records."""
    if isinstance(payload, list):
        payload = {"records": payload}
    if not isinstance(payload, dict):
        raise OrganizerError("Ожидается JSON-объект или массив записей")
    if "isSuccess" in payload or "data" in payload:
        if payload.get("isSuccess") is False:
            raise OrganizerError(
                f"Организаторы вернули ошибку: {payload.get('error') or 'без текста'}"
            )
        payload = payload.get("data") or {}
    if not isinstance(payload.get("records"), list) or not payload["records"]:
        raise OrganizerError(
            "В файле нет записей: ожидается data.records[] как в ответе API организаторов"
        )
    try:
        return OrganizerDataset.model_validate(payload)
    except ValidationError as exc:
        raise OrganizerError(f"Неверный формат набора: {_describe(exc.errors())}") from exc


def load_dataset_file(path: Path | str) -> OrganizerDataset:
    with open(path, encoding="utf-8") as f:
        return parse_dataset(json.load(f))


def dataset_url(api_url: str, group_id: str) -> str:
    """Set group_id on the organizer URL, keeping its other query params (api-version, sig, ...).

    The organizer gives a signed URL that already ends with `&group_id=DEV`; passing `params=`
    to httpx would replace the whole query string and drop the signature.
    """
    url = httpx.URL(api_url)
    return str(url.copy_set_param("group_id", group_id))


async def fetch_dataset(api_url: str, group_id: str, timeout_s: float = 60.0) -> OrganizerDataset:
    # Messages never include the URL: it carries the organizers' signature.
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
        try:
            resp = await client.get(dataset_url(api_url, group_id))
        except httpx.TimeoutException as exc:
            raise OrganizerError("API организаторов не ответило вовремя") from exc
        except httpx.HTTPError as exc:
            raise OrganizerError(f"API организаторов недоступно ({type(exc).__name__})") from exc
    if resp.status_code == 404:
        raise OrganizerError(f"Набор «{group_id}» не найден у организаторов")
    if resp.status_code >= 400:
        detail = ""
        try:
            body = resp.json()
            detail = (
                (body.get("error") or body.get("message") or "") if isinstance(body, dict) else ""
            )
        except ValueError:
            pass
        raise OrganizerError(
            f"API организаторов ответило {resp.status_code}" + (f": {detail}" if detail else "")
        )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise OrganizerError("API организаторов вернуло не JSON") from exc
    return parse_dataset(payload)
