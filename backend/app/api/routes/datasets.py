import json
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import SessionDep, SettingsDep
from app.services import dialogs as dialog_service
from app.services.organizer import OrganizerError, fetch_dataset, parse_dataset

router = APIRouter(prefix="/datasets", tags=["datasets"])


class ImportBody(BaseModel):
    group_id: str = Field(min_length=1, max_length=64)


class UploadBody(BaseModel):
    name: str | None = None
    payload: Any = Field(
        description="Organizer response envelope, its data object, or a record list"
    )


@router.post("/import")
async def import_dataset(body: ImportBody, session: SessionDep, settings: SettingsDep):
    """Fetch a dataset from the organizer API by group_id (the backend does the GET, no CORS)."""
    if not settings.organizer_api_url:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ORGANIZER_API_URL не настроен на бэкенде. Загрузите JSON-файл.",
        )
    group_id = body.group_id.strip()
    try:
        dataset = await fetch_dataset(
            settings.organizer_api_url, group_id, settings.organizer_api_timeout_s
        )
    except OrganizerError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    group = dataset.dataset_group_id or group_id
    _, _, ids = await dialog_service.upsert_dialogs(
        session, dataset.records, source="organizer_api", dataset_group_id=group
    )
    await session.commit()
    return {"group_id": group, "imported": len(ids)}


def _parse(payload: Any):
    if isinstance(payload, str | bytes):
        try:
            payload = json.loads(payload)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Файл не похож на JSON"
            ) from exc
    try:
        return parse_dataset(payload)
    except OrganizerError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/upload")
async def upload_dataset(body: UploadBody, session: SessionDep):
    """Dataset from a JSON document (the organizer file as-is or a bare list of records)."""
    dataset = _parse(body.payload)
    group = dataset.dataset_group_id or (body.name or "UPLOAD").strip().upper()
    _, _, ids = await dialog_service.upsert_dialogs(
        session, dataset.records, source="file", dataset_group_id=group
    )
    await session.commit()
    return {"group_id": group, "imported": len(ids)}


@router.post("/upload-file")
async def upload_dataset_file(file: UploadFile, session: SessionDep):
    """Same as /upload, but as a multipart file (handy for curl)."""
    dataset = _parse(await file.read())
    name = (file.filename or "UPLOAD").rsplit(".", 1)[0].upper()
    group = dataset.dataset_group_id or name
    _, _, ids = await dialog_service.upsert_dialogs(
        session, dataset.records, source="file", dataset_group_id=group
    )
    await session.commit()
    return {"group_id": group, "imported": len(ids)}
