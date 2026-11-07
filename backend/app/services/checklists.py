from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Checklist, Criterion
from app.schemas.checklist import ChecklistIn, CriterionIn

# Initial configuration from the Freedom Broker "Chat quality checklist" PDF.
DEFAULT_CHECKLIST = ChecklistIn(
    name="Freedom Broker — Chat Quality (default)",
    description="Eight criteria for evaluating an operator in a chat. Weights sum to 100; "
    "N/A weight is redistributed among applicable criteria.",
    criteria=[
        CriterionIn(
            code="c1",
            title="Установление контакта",
            section="Начало и понимание запроса",
            answer_type="yes_no",
            weight=10,
            allow_na=False,
            rule="Да — оператор поздоровался на языке клиента и представился в первом ответе.",
        ),
        CriterionIn(
            code="c2",
            title="Выявление потребности",
            section="Начало и понимание запроса",
            answer_type="yes_no",
            weight=15,
            allow_na=True,
            rule="Да — оператор учёл известные детали и уточнил недостающее до ответа.",
            na_rule="N/A — данных для ответа хватало с самого начала.",
        ),
        CriterionIn(
            code="c3",
            title="Идентификация",
            section="Безопасность и решение",
            answer_type="yes_no",
            weight=20,
            allow_na=True,
            rule="Да — проверка личности подтверждена до раскрытия данных или защищённого "
            "действия. Если проверка требовалась, но не подтверждена в чате — Нет.",
            na_rule="N/A — запрос не требовал идентификации (например, общий вопрос о тарифах).",
        ),
        CriterionIn(
            code="c4",
            title="Корректная и полная консультация",
            section="Безопасность и решение",
            answer_type="scale",
            scale_max=20,
            weight=20,
            allow_na=True,
            scale_steps=[
                {
                    "value": 20,
                    "label": "Все существенные вопросы закрыты или дан корректный следующий шаг.",
                },
                {"value": 15, "label": "Основной вопрос решён, пропущена второстепенная деталь."},
                {
                    "value": 10,
                    "label": "Часть запроса закрыта, существенный вопрос остался открытым.",
                },
                {
                    "value": 5,
                    "label": "Есть общая подсказка, но клиенту всё ещё непонятно, как действовать.",
                },
                {"value": 0, "label": "Ответа по существу нет или ключевая рекомендация ошибочна."},
            ],
            rule="Оцените ответ или следующий шаг по шкале 0–20.",
            na_rule="N/A — чат закончился до того, как клиент сформулировал запрос.",
        ),
        CriterionIn(
            code="c5",
            title="Эмпатия и клиентоориентированность",
            section="Ведение и завершение диалога",
            answer_type="yes_no",
            weight=15,
            allow_na=False,
            rule="Да — оператор вежлив и, если клиент выразил недовольство или описал неудобство, "
            "отреагировал на конкретную проблему.",
        ),
        CriterionIn(
            code="c6",
            title="Управление диалогом, скорость и грамотность",
            section="Ведение и завершение диалога",
            answer_type="scale",
            scale_max=10,
            weight=15,
            allow_na=False,
            scale_steps=[
                {
                    "value": 10,
                    "label": "Ответы ясные и связные. Если было явное ожидание, "
                    "оператор предупредил.",
                },
                {
                    "value": 7,
                    "label": "Один заметный сбой, но клиент может понять ответ и продолжить.",
                },
                {
                    "value": 4,
                    "label": "Клиенту приходится переспрашивать из-за формулировок "
                    "или порядка ответов.",
                },
                {
                    "value": 0,
                    "label": "Из-за бессвязных или противоречивых реплик ход диалога непонятен.",
                },
            ],
            rule="Оцените ясность, порядок ответов и предупреждение об ожидании по шкале 0–10.",
        ),
        CriterionIn(
            code="c7",
            title="Завершение",
            section="Ведение и завершение диалога",
            answer_type="yes_no",
            weight=5,
            allow_na=True,
            rule="Да — оператор подвёл итог или предложил дальнейшую помощь и попрощался.",
            na_rule="N/A — чат оборвался до возможности его завершить.",
        ),
        CriterionIn(
            code="c8",
            title="Грубые ошибки",
            section="Грубые нарушения",
            answer_type="yes_no",
            weight=0,
            allow_na=False,
            is_flag=True,
            rule="Да — выявлено оскорбление клиента, предложение платной услуги в обход компании "
            "или раскрытие конфиденциальной информации. Нет — ни одно из трёх не выявлено.",
        ),
    ],
)


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


async def create_checklist(
    session: AsyncSession, data: ChecklistIn, *, make_default: bool = False
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
    return checklist


async def update_checklist(
    session: AsyncSession, checklist: Checklist, data: ChecklistIn
) -> Checklist:
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
    return await create_checklist(session, DEFAULT_CHECKLIST, make_default=True)


def snapshot(checklist: Checklist) -> dict[str, Any]:
    """Immutable copy stored on each evaluation."""
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
    }
