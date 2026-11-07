"""Attention queue and bot handoff insights."""

from httpx import AsyncClient

from app.ml.base import MLClientError
from app.ml.schemas import MLCriterionResult, MLEvaluateRequest, MLEvaluateResponse

API = "/api"


class ScriptedML:
    """good: full marks; bad: zero everywhere; grave: good + flag raised; fail: error;
    sloppy: N/A where not allowed (the backend corrects it)."""

    name = "scripted"

    def __init__(self, plan: dict[str, str]) -> None:
        self.plan = plan

    async def evaluate(self, request: MLEvaluateRequest) -> MLEvaluateResponse:
        mode = self.plan.get(request.conversation_id, "good")
        if mode == "fail":
            raise MLClientError("model down")
        results = []
        for c in request.criteria:
            if c.is_flag:
                answer = "yes" if mode == "grave" else "no"
            elif c.answer_type == "scale":
                top = max(s["value"] for s in c.scale_steps)
                answer = 0 if mode == "bad" else top
            else:
                answer = "no" if mode == "bad" else "yes"
            if mode == "sloppy" and not c.allow_na and not c.is_flag:
                answer = "na"
            results.append(
                MLCriterionResult(
                    code=c.code, answer=answer, explanation=f"{mode} {c.code}", evidence=[1]
                )
            )
        return MLEvaluateResponse(conversation_id=request.conversation_id, results=results)

    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


def _use(client: AsyncClient, ml) -> None:
    client.app.state.ml = ml  # type: ignore[attr-defined]
    client.app.state.queue._ml = ml  # type: ignore[attr-defined]


async def _evaluate(client: AsyncClient, dialog_id: str) -> dict:
    r = await client.post(f"{API}/evaluations", json={"conversation_id": dialog_id})
    return r.json()


async def test_attention_queue_orders_by_severity(seeded: AsyncClient):
    _use(
        seeded,
        ScriptedML(
            {
                "p1-ru-001": "grave",
                "p1-ru-002": "bad",
                "p1-ru-003": "good",
                "p1-ru-004": "fail",
                "p1-ru-005": "sloppy",
            }
        ),
    )
    for i in range(1, 7):
        await _evaluate(seeded, f"p1-ru-00{i}")
    good = await _evaluate(seeded, "p1-ru-006")
    r = await seeded.post(
        f"{API}/appeals",
        json={
            "evaluation_id": good["evaluation_id"],
            "criterion_id": "c01",
            "comment": "I greeted the client",
        },
    )
    assert r.status_code in (200, 201), r.text

    data = (await seeded.get(f"{API}/attention")).json()
    ids = [i["conversation_id"] for i in data["items"]]
    assert ids[:2] == ["p1-ru-001", "p1-ru-004"]
    assert "p1-ru-003" not in ids
    assert set(ids) == {"p1-ru-001", "p1-ru-002", "p1-ru-004", "p1-ru-005", "p1-ru-006"}

    by_id = {i["conversation_id"]: i for i in data["items"]}
    grave = by_id["p1-ru-001"]["reasons"][0]
    assert grave["kind"] == "grave" and grave["criterion_id"] == "c08"
    assert grave["evidence"]["msg"] == 1
    low = next(r for r in by_id["p1-ru-002"]["reasons"] if r["kind"] == "low_score")
    assert low["total"] == 0 and len(low["weakest"]) == 2
    assert by_id["p1-ru-004"]["reasons"][0]["kind"] == "failed"
    assert {r["kind"] for r in by_id["p1-ru-005"]["reasons"]} >= {"model_fix"}
    assert by_id["p1-ru-006"]["reasons"] == [{"kind": "appeal", "count": 1}]
    assert data["counts"]["grave"] == 1 and data["counts"]["total"] == 5

    strict = (await seeded.get(f"{API}/attention", params={"threshold": 0})).json()
    assert all(r["kind"] != "low_score" for i in strict["items"] for r in i["reasons"])


async def test_failed_rerun_keeps_previous_verdict(seeded: AsyncClient):
    _use(seeded, ScriptedML({"p1-ru-001": "grave"}))
    await _evaluate(seeded, "p1-ru-001")
    _use(seeded, ScriptedML({"p1-ru-001": "fail"}))
    await _evaluate(seeded, "p1-ru-001")
    item = (await seeded.get(f"{API}/attention")).json()["items"][0]
    assert item["status"] == "completed" and item["reasons"][0]["kind"] == "grave"


# --- bot handoffs -----------------------------------------------------------------------------


async def test_handoff_summary_from_import(seeded: AsyncClient):
    data = (await seeded.get(f"{API}/insights/handoffs")).json()
    assert data["dialogs"] == 65 and data["with_bot"] == 64 and data["escalated"] == 64
    assert data["avg_wait_s"] > 0 and data["job"]["available"] is False
    topics = {t["topic"]: t for t in data["by_topic"]}
    assert topics["Сделки и ценные бумаги"]["count"] >= 10
    assert sum(r["count"] for r in data["by_reason"]) == 64

    one = (await seeded.get(f"{API}/dialogs/p1-ru-001/handoff")).json()
    assert one["handoff_index"] == 8 and one["first_operator_index"] == 9
    assert one["wait_s"] == 37 and one["topic"] == "Тарифы и комиссии"
    assert one["question"].startswith("Где посмотреть мой тариф")
    assert "отчёта брокера" in one["bot_answer"] and "Кабинет" in one["operator_answer"]
    assert one["source"] == "heuristic"

    assert (await seeded.get(f"{API}/dialogs/p4-ru-002/handoff")).json() is None
    assert (await seeded.get(f"{API}/dialogs/nope/handoff")).status_code == 404


async def test_analyze_requires_llm(seeded: AsyncClient):
    r = await seeded.post(f"{API}/insights/handoffs/analyze")
    assert r.status_code == 409 and "OPENAI_API_KEY" in r.json()["error"]


async def test_llm_handoff_analysis_and_knowledge_base(seeded: AsyncClient):
    import json

    import httpx

    from app.ml.openai import OpenAIChat

    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        user = body["messages"][1]["content"]
        seen.append(user)
        automatable = "p1-ru-001" in user
        content = {
            "topic": "Тарифы и комиссии",
            "reason": "incomplete_answer",
            "bot_gap": "Бот не знал, где тариф в веб-версии.",
            "automatable": automatable,
            "suggested_bot_answer": "Откройте вкладку «Кабинет», тариф под ФИО."
            if automatable
            else "",
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 500, "completion_tokens": 80},
            },
        )

    analyzer = seeded.app.state.handoff  # type: ignore[attr-defined]
    analyzer._chat = OpenAIChat(
        api_key="k",
        base_url="https://api.test/v1",
        model="gpt-test",
        price_input_per_1m=2,
        price_output_per_1m=8,
        transport=httpx.MockTransport(handler),
    )
    analyzer._mask = True
    r = await seeded.post(f"{API}/insights/handoffs/analyze", json={})
    assert r.status_code == 202 and r.json()["total"] == 64
    await analyzer._task
    status = (await seeded.get(f"{API}/insights/handoffs")).json()
    assert status["job"]["done"] == 64 and status["job"]["running"] is False
    assert status["job"]["cost_usd"] > 0
    assert status["llm_analysed"] == 64 and status["automatable"] == 1

    one = (await seeded.get(f"{API}/dialogs/p1-ru-001/handoff")).json()
    assert one["source"] == "llm" and one["automatable"] is True
    assert one["bot_gap"].startswith("Бот не знал")
    assert one["wait_s"] == 37  # deterministic part kept

    # Already analysed -> nothing to do unless forced.
    assert (await seeded.post(f"{API}/insights/handoffs/analyze", json={})).json()["total"] == 0

    kb = (await seeded.get(f"{API}/insights/handoffs/knowledge")).json()
    assert [k["conversation_id"] for k in kb] == ["p1-ru-001"]
    assert kb[0]["origin"] == "llm_draft" and "Кабинет" in kb[0]["answer"]
    r = await seeded.get(f"{API}/insights/handoffs/knowledge", params={"format": "jsonl"})
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert json.loads(r.text.splitlines()[0])["conversation_id"] == "p1-ru-001"


async def test_knowledge_base_uses_good_operator_answers_without_llm(seeded: AsyncClient):
    _use(seeded, ScriptedML({}))
    await _evaluate(seeded, "p1-ru-001")
    await _evaluate(seeded, "p1-ru-009")  # account check: never a bot answer
    kb = (await seeded.get(f"{API}/insights/handoffs/knowledge")).json()
    assert [k["conversation_id"] for k in kb] == ["p1-ru-001"]
    assert kb[0]["origin"] == "operator" and kb[0]["operator_score"] == 100


async def test_reimport_keeps_llm_analysis_when_transcript_unchanged(
    seeded: AsyncClient, dev_dataset: dict
):
    from app.core.db import get_session_factory
    from app.models import Dialog

    async with get_session_factory()() as s:
        d = await s.get(Dialog, "p1-ru-001")
        d.handoff = {**d.handoff, "bot_gap": "x"}
        d.handoff_source = "llm"
        await s.commit()
    await seeded.post(f"{API}/datasets/upload", json={"name": "DEV", "payload": dev_dataset})
    one = (await seeded.get(f"{API}/dialogs/p1-ru-001/handoff")).json()
    assert one["source"] == "llm" and one["bot_gap"] == "x"


# --- review workflow ----------------------------------------------------------------------------


async def _row(client: AsyncClient, dialog_id: str) -> dict:
    rows = (await client.get(f"{API}/dialogs")).json()
    return next(r for r in rows if r["conversation_id"] == dialog_id)


async def test_review_workflow(seeded: AsyncClient):
    _use(seeded, ScriptedML({"p1-ru-001": "grave"}))
    assert (await _row(seeded, "p1-ru-001"))["review_status"] == "none"
    ev = await _evaluate(seeded, "p1-ru-001")
    assert (await _row(seeded, "p1-ru-001"))["review_status"] == "to_review"
    assert ev["review"] is None

    # An open appeal blocks closing the dialog.
    a = (
        await seeded.post(
            f"{API}/appeals",
            json={"evaluation_id": ev["evaluation_id"], "criterion_id": "c08", "comment": "No."},
        )
    ).json()
    assert (await _row(seeded, "p1-ru-001"))["review_status"] == "appeal"
    r = await seeded.post(f"{API}/evaluations/{ev['evaluation_id']}/review", json={"by": "Dana"})
    assert r.status_code == 409 and "апелляции" in r.json()["error"]

    # Deciding the last appeal recalculates and closes it, with the reviewer's name.
    d = await seeded.post(
        f"{API}/appeals/{a['appeal_id']}/decision",
        json={"action": "change", "answer": "no", "reason": "Not a violation.", "by": "Dana"},
    )
    assert d.status_code == 200 and d.json()["decision"]["by"] == "Dana"
    row = await _row(seeded, "p1-ru-001")
    assert row["review_status"] == "reviewed" and row["reviewed_by"] == "Dana"
    assert row["gross_error"] is False
    full = (await seeded.get(f"{API}/evaluations/{ev['evaluation_id']}")).json()
    assert full["review"]["by"] == "Dana" and full["final_gross_error"] is False

    # Reopen, then close by hand; reviewed dialogs leave the attention queue.
    r = await seeded.delete(f"{API}/evaluations/{ev['evaluation_id']}/review")
    assert r.json()["review"] is None
    assert (await _row(seeded, "p1-ru-001"))["review_status"] == "to_review"
    _use(seeded, ScriptedML({"p1-ru-002": "bad"}))
    bad = await _evaluate(seeded, "p1-ru-002")
    ids = [i["conversation_id"] for i in (await seeded.get(f"{API}/attention")).json()["items"]]
    assert "p1-ru-002" in ids
    r = await seeded.post(
        f"{API}/evaluations/{bad['evaluation_id']}/review", json={"by": "Dana", "note": "Coached."}
    )
    assert r.status_code == 200 and r.json()["review"]["note"] == "Coached."
    data = (await seeded.get(f"{API}/attention")).json()
    assert "p1-ru-002" not in [i["conversation_id"] for i in data["items"]]
    data = (await seeded.get(f"{API}/attention", params={"include_reviewed": True})).json()
    item = next(i for i in data["items"] if i["conversation_id"] == "p1-ru-002")
    assert item["reviewed_by"] == "Dana"

    # A re-evaluation starts unreviewed.
    await _evaluate(seeded, "p1-ru-002")
    assert (await _row(seeded, "p1-ru-002"))["review_status"] == "to_review"


class CheckedML(ScriptedML):
    """Full marks, but the check model disagrees on the first scale criterion."""

    async def evaluate(self, request: MLEvaluateRequest) -> MLEvaluateResponse:
        from app.ml.schemas import MLReview

        response = await super().evaluate(request)
        scale = next(c.code for c in request.criteria if c.answer_type == "scale")
        for r in response.results:
            disputed = r.code == scale
            r.review = MLReview(
                agrees=not disputed, needs_review=disputed,
                second_answer=0 if disputed else r.answer, second_model="checker",
            )
        return response


async def test_disputed_criteria_reach_the_card_and_the_attention_queue(seeded: AsyncClient):
    _use(seeded, CheckedML({}))
    ev = await _evaluate(seeded, "p1-ru-001")
    card = (await seeded.get(f"{API}/dialogs/p1-ru-001/evaluation")).json()
    flagged = [r for r in card["results"] if r["needs_review"]]
    assert len(flagged) == 1 and flagged[0]["second_opinion"] == {"answer": 0, "model": "checker"}

    data = (await seeded.get(f"{API}/attention")).json()
    item = next(i for i in data["items"] if i["conversation_id"] == "p1-ru-001")
    disputed = next(r for r in item["reasons"] if r["kind"] == "disputed")
    assert disputed["count"] == 1 and disputed["criteria"][0]["second_answer"] == 0
    assert data["counts"]["disputed"] >= 1
    assert ev["evaluation_id"]
