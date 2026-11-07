from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Checklist, ChecklistVersion, Criterion
from app.schemas.checklist import ChecklistIn, CriterionIn
from app.services.checklist_document import (
    document_from_checklist,
    document_to_checklist_in,
    load_default_document,
)


def default_checklist_in() -> ChecklistIn:
    """The eight criteria from the Freedom Broker PDF (data/checklist.default.json)."""
    return document_to_checklist_in(load_default_document())


def _apply_criteria(checklist: Checklist, criteria: list[CriterionIn]) -> None:
    checklist.criteria = [
        Criterion(
            code=c.code,
            position=i,
            title=c.title,
            rule=c.rule,
            section=c.section,
            answer_type=c.answer_type,
            scale_max=c.scale_max,
            scale_steps=[s.model_dump() for s in c.scale_steps] if c.scale_steps else None,
            weight=c.weight,
            allow_na=c.allow_na,
            na_rule=c.na_rule,
            is_flag=c.is_flag,
        )
        for i, c in enumerate(criteria)
    ]


def _stamp_document(checklist: Checklist, document: dict[str, Any] | None) -> dict[str, Any]:
    doc = dict(document) if document else document_from_checklist(checklist)
    doc["version"] = checklist.version
    doc["name"] = checklist.name
    doc["updated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return doc


async def _store_version(
    session: AsyncSession, checklist: Checklist, document: dict[str, Any] | None
) -> ChecklistVersion:
    doc = _stamp_document(checklist, document)
    row = ChecklistVersion(
        checklist_id=checklist.id, version=checklist.version, name=checklist.name, document=doc
    )
    session.add(row)
    await session.flush()
    return row


async def create_checklist(
    session: AsyncSession,
    data: ChecklistIn,
    *,
    make_default: bool = False,
    document: dict[str, Any] | None = None,
) -> Checklist:
    checklist = Checklist(name=data.name, description=data.description)
    _apply_criteria(checklist, data.criteria)
    session.add(checklist)
    await session.flush()
    if make_default or not await session.scalar(
        select(Checklist.id).where(Checklist.is_default.is_(True))
    ):
        await set_default(session, checklist.id)
    await session.refresh(checklist, attribute_names=["criteria", "is_default"])
    await _store_version(session, checklist, document)
    return checklist


async def update_checklist(
    session: AsyncSession,
    checklist: Checklist,
    data: ChecklistIn,
    *,
    document: dict[str, Any] | None = None,
) -> Checklist:
    """Replace the configuration and record it as a new version."""
    checklist.name = data.name
    checklist.description = data.description
    checklist.version += 1
    # Delete old rows first so re-used codes do not trip the unique constraint mid-flush.
    for old in list(checklist.criteria):
        await session.delete(old)
    checklist.criteria = []
    await session.flush()
    _apply_criteria(checklist, data.criteria)
    await session.flush()
    await session.refresh(checklist, attribute_names=["criteria"])
    await _store_version(session, checklist, document)
    return checklist


async def set_default(session: AsyncSession, checklist_id: int) -> None:
    await session.execute(
        update(Checklist).values(is_default=False).where(Checklist.is_default.is_(True))
    )
    await session.execute(
        update(Checklist).values(is_default=True).where(Checklist.id == checklist_id)
    )


async def get_checklist(session: AsyncSession, checklist_id: int) -> Checklist | None:
    return await session.scalar(
        select(Checklist)
        .where(Checklist.id == checklist_id)
        .options(selectinload(Checklist.criteria))
    )


async def get_default_checklist(session: AsyncSession) -> Checklist | None:
    return await session.scalar(
        select(Checklist)
        .where(Checklist.is_default.is_(True))
        .options(selectinload(Checklist.criteria))
    )


async def list_checklists(session: AsyncSession) -> list[Checklist]:
    return list(
        (
            await session.scalars(
                select(Checklist).options(selectinload(Checklist.criteria)).order_by(Checklist.id)
            )
        ).all()
    )


async def ensure_default_checklist(session: AsyncSession) -> Checklist:
    existing = await get_default_checklist(session)
    if existing:
        return existing
    any_checklist = await session.scalar(select(Checklist).order_by(Checklist.id).limit(1))
    if any_checklist:
        await set_default(session, any_checklist.id)
        return await get_checklist(session, any_checklist.id)  # type: ignore[return-value]
    return await create_checklist(
        session, default_checklist_in(), make_default=True, document=load_default_document()
    )


# --- versions (UI document per version) ---------------------------------------------------------


async def list_versions(session: AsyncSession, checklist_id: int) -> list[ChecklistVersion]:
    stmt = (
        select(ChecklistVersion)
        .where(ChecklistVersion.checklist_id == checklist_id)
        .order_by(ChecklistVersion.version)
    )
    return list((await session.scalars(stmt)).all())


async def get_version_document(
    session: AsyncSession, checklist_id: int, version: int
) -> dict[str, Any] | None:
    row = await session.scalar(
        select(ChecklistVersion).where(
            ChecklistVersion.checklist_id == checklist_id, ChecklistVersion.version == version
        )
    )
    return row.document if row else None


async def current_document(session: AsyncSession, checklist: Checklist) -> dict[str, Any]:
    doc = await get_version_document(session, checklist.id, checklist.version)
    if doc is None:
        # Checklist created without a document (e.g. seeded from the CLI): record one now.
        row = await _store_version(session, checklist, None)
        doc = row.document
    return doc


async def snapshot(session: AsyncSession, checklist: Checklist) -> dict[str, Any]:
    """Immutable copy stored on each evaluation (normalised criteria + the UI document)."""
    return {
        "id": checklist.id,
        "name": checklist.name,
        "version": checklist.version,
        "criteria": [
            {
                "code": c.code,
                "position": c.position,
                "title": c.title,
                "rule": c.rule,
                "section": c.section,
                "answer_type": c.answer_type,
                "scale_max": c.scale_max,
                "scale_steps": c.scale_steps,
                "weight": c.weight,
                "allow_na": c.allow_na,
                "na_rule": c.na_rule,
                "is_flag": c.is_flag,
            }
            for c in sorted(checklist.criteria, key=lambda x: x.position)
        ],
        "document": await current_document(session, checklist),
    }
