from fastapi import APIRouter, HTTPException, status

from app.api.deps import SessionDep
from app.models import Checklist
from app.schemas.checklist import ChecklistIn, ChecklistOut, ChecklistSummary
from app.services import checklists as checklist_service

router = APIRouter(prefix="/checklists", tags=["checklists"])


def _summary(c: Checklist) -> ChecklistSummary:
    s = ChecklistSummary.model_validate(c)
    s.criteria_count = len(c.criteria)
    s.total_weight = round(sum(x.weight for x in c.criteria if not x.is_flag), 2)
    return s


def _out(c: Checklist) -> ChecklistOut:
    out = ChecklistOut.model_validate(c)
    out.criteria_count = len(c.criteria)
    out.total_weight = round(sum(x.weight for x in c.criteria if not x.is_flag), 2)
    return out


async def _get_or_404(session, checklist_id: int) -> Checklist:
    c = await checklist_service.get_checklist(session, checklist_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "checklist not found")
    return c


@router.get("", response_model=list[ChecklistSummary])
async def list_checklists(session: SessionDep):
    return [_summary(c) for c in await checklist_service.list_checklists(session)]


@router.get("/default", response_model=ChecklistOut)
async def get_default(session: SessionDep):
    c = await checklist_service.get_default_checklist(session)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no default checklist")
    return _out(c)


@router.get("/{checklist_id}", response_model=ChecklistOut)
async def get_checklist(checklist_id: int, session: SessionDep):
    return _out(await _get_or_404(session, checklist_id))


@router.post("", response_model=ChecklistOut, status_code=status.HTTP_201_CREATED)
async def create_checklist(body: ChecklistIn, session: SessionDep, make_default: bool = False):
    c = await checklist_service.create_checklist(session, body, make_default=make_default)
    await session.commit()
    return _out(await _get_or_404(session, c.id))


@router.put("/{checklist_id}", response_model=ChecklistOut)
async def update_checklist(checklist_id: int, body: ChecklistIn, session: SessionDep):
    """Replace the checklist configuration. Past evaluations keep their own snapshot."""
    c = await _get_or_404(session, checklist_id)
    await checklist_service.update_checklist(session, c, body)
    await session.commit()
    return _out(await _get_or_404(session, checklist_id))


@router.post(
    "/{checklist_id}/duplicate", response_model=ChecklistOut, status_code=status.HTTP_201_CREATED
)
async def duplicate_checklist(checklist_id: int, session: SessionDep, name: str | None = None):
    src = await _get_or_404(session, checklist_id)
    data = ChecklistIn(
        name=name or f"{src.name} (copy)",
        description=src.description,
        criteria=[
            {
                "code": x.code,
                "title": x.title,
                "rule": x.rule,
                "section": x.section,
                "answer_type": x.answer_type,
                "scale_max": x.scale_max,
                "scale_steps": x.scale_steps,
                "weight": x.weight,
                "allow_na": x.allow_na,
                "na_rule": x.na_rule,
                "is_flag": x.is_flag,
            }
            for x in src.criteria
        ],
    )
    c = await checklist_service.create_checklist(session, data)
    await session.commit()
    return _out(await _get_or_404(session, c.id))


@router.post("/{checklist_id}/default", response_model=ChecklistOut)
async def make_default(checklist_id: int, session: SessionDep):
    await _get_or_404(session, checklist_id)
    await checklist_service.set_default(session, checklist_id)
    await session.commit()
    return _out(await _get_or_404(session, checklist_id))


@router.delete("/{checklist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_checklist(checklist_id: int, session: SessionDep):
    c = await _get_or_404(session, checklist_id)
    if c.is_default:
        raise HTTPException(status.HTTP_409_CONFLICT, "cannot delete the default checklist")
    await session.delete(c)
    await session.commit()
