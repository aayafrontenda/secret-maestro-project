import json

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.deps import HandoffDep, SessionDep, SettingsDep
from app.services import dialogs as dialog_service
from app.services import handoff as handoff_service
from app.services.attention import attention_queue

router = APIRouter(tags=["insights"])


@router.get("/attention")
async def attention(
    session: SessionDep,
    settings: SettingsDep,
    threshold: float | None = Query(default=None, ge=0, le=100),
    include_reviewed: bool = Query(default=False, description="Also list already reviewed"),
):
    """Dialogs to review first: grave violations, failed runs, open appeals, low totals,
    verdicts corrected by the backend. Latest evaluation per dialog, highest priority first."""
    return await attention_queue(
        session,
        settings.attention_score_threshold if threshold is None else threshold,
        include_reviewed=include_reviewed,
    )


@router.get("/insights/handoffs")
async def handoffs(session: SessionDep, analyzer: HandoffDep):
    """Bot -> operator handoffs: topics, reasons, wait for the operator, per-dialog details."""
    return {**await handoff_service.summary(session), "job": analyzer.status()}


class AnalyzeIn(BaseModel):
    force: bool = False


@router.post("/insights/handoffs/analyze", status_code=status.HTTP_202_ACCEPTED)
async def analyze_handoffs(analyzer: HandoffDep, body: AnalyzeIn | None = None):
    """Refine every handoff with the LLM in the background (topic, reason, suggested bot answer)."""
    if not analyzer.available:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "LLM не настроена: добавьте OPENAI_API_KEY в backend/.env"
        )
    return await analyzer.start(force=bool(body and body.force))


@router.get("/insights/handoffs/knowledge")
async def handoff_knowledge(
    session: SessionDep,
    format: str = Query(default="json", pattern="^(json|jsonl)$"),
    min_total: float = Query(default=80, ge=0, le=100),
):
    """Question -> answer pairs for the bot's knowledge base (personal data masked)."""
    items = await handoff_service.knowledge_base(session, min_total)
    if format == "jsonl":
        body = "\n".join(json.dumps(i, ensure_ascii=False) for i in items)
        return Response(
            body + ("\n" if body else ""),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="bot-knowledge.jsonl"'},
        )
    return items


@router.get("/dialogs/{dialog_id}/handoff")
async def dialog_handoff(dialog_id: str, session: SessionDep):
    """Handoff analysis of one dialog; null when the bot did not take part."""
    d = await dialog_service.get_dialog(session, dialog_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Диалог {dialog_id} не найден")
    return await handoff_service.dialog_handoff(session, d)
