"""OpenAIMLClient against a fake Chat Completions API, and PII masking."""

import json
from collections import Counter

import httpx
import pytest

from app.ml import pii
from app.ml.base import MLClientError
from app.ml.openai import OpenAIChat, OpenAIMLClient, response_schema
from app.ml.schemas import MLCriterion, MLEvaluateRequest, MLTranscriptMessage

CRITERIA = [
    MLCriterion(
        code="01", title="Contact", rule="Greeted", answer_type="yes_no", weight=10, allow_na=False
    ),
    MLCriterion(
        code="04",
        title="Consultation",
        rule="Quality",
        answer_type="scale",
        scale_steps=[
            {"value": 20, "label": "full"},
            {"value": 10, "label": "part"},
            {"value": 0, "label": "none"},
        ],
        weight=20,
        allow_na=True,
        na_rule="No request",
    ),
    MLCriterion(
        code="08",
        title="Grave",
        rule="Insult",
        answer_type="yes_no",
        weight=0,
        allow_na=False,
        is_flag=True,
    ),
]


def _request() -> MLEvaluateRequest:
    return MLEvaluateRequest(
        conversation_id="d1",
        channel="agent chat",
        language="RU",
        transcript=[
            MLTranscriptMessage(
                index=0,
                timestamp="00:00",
                speaker="client",
                text="Мой ИИН 900101300123, тел +7 701 123 45 67",
            ),
            MLTranscriptMessage(
                index=1,
                timestamp="00:05",
                speaker="operator",
                text="Здравствуйте! Меня зовут Алина.",
            ),
        ],
        criteria=CRITERIA,
        guidelines=["Bot replies are context."],
    )


def _completion(content: dict) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
    }


GOOD = {
    "01": {
        "evidence": [1],
        "checked_from": None,
        "checked_to": None,
        "explanation": "Поздоровалась.",
        "answer": "yes",
        "na_reason": None,
    },
    "04": {
        "evidence": [],
        "checked_from": 0,
        "checked_to": 9,
        "explanation": "Запроса нет.",
        "answer": "na",
        "na_reason": "Нет запроса",
    },
    "08": {
        "evidence": [],
        "checked_from": None,
        "checked_to": None,
        "explanation": "Нарушений нет.",
        "answer": "no",
        "na_reason": "x",
    },
}


def _client(handler, base_url="https://api.test/v1") -> OpenAIMLClient:
    chat = OpenAIChat(
        api_key="sk-test",
        base_url=base_url,
        model="gpt-test",
        max_retries=2,
        price_input_per_1m=2.0,
        price_output_per_1m=8.0,
        transport=httpx.MockTransport(handler),
    )
    return OpenAIMLClient(chat, mask_pii=True, language="ru")


async def test_evaluates_every_criterion_with_masked_transcript(monkeypatch):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(200, json=_completion(GOOD))

    resp = await _client(handler).evaluate(_request())

    body = seen["body"]
    assert seen["auth"] == "Bearer sk-test"
    user = body["messages"][1]["content"]
    assert "900101300123" not in user and "[IIN]" in user and "[PHONE]" in user
    assert "Bot replies are context." in body["messages"][0]["content"]
    schema = body["response_format"]["json_schema"]["schema"]
    assert schema["required"] == ["01", "04", "08"]
    assert schema["properties"]["04"]["properties"]["answer"]["enum"] == ["20", "10", "0", "na"]
    assert schema["properties"]["01"]["properties"]["answer"]["enum"] == ["yes", "no"]

    by_code = {r.code: r for r in resp.results}
    assert by_code["01"].answer == "yes" and by_code["01"].evidence == [1]
    assert by_code["01"].checked_range is None
    assert by_code["04"].answer == "na" and by_code["04"].na_reason == "Нет запроса"
    assert by_code["04"].checked_range.to_index == 1  # clamped to the transcript
    assert by_code["08"].na_reason is None
    assert resp.model.provider == "openai" and resp.model.name == "gpt-test"
    assert resp.usage.cost_usd == pytest.approx(0.0036)
    assert resp.usage.pii_masked == 2


async def test_scale_answer_is_numeric():
    data = json.loads(json.dumps(GOOD))
    data["04"]["answer"] = "10"
    resp = await _client(lambda r: httpx.Response(200, json=_completion(data))).evaluate(_request())
    assert {r.code: r.answer for r in resp.results}["04"] == 10


async def test_retries_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.ml.openai.asyncio.sleep", _no_sleep)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "slow down"})
        return httpx.Response(200, json=_completion(GOOD))

    resp = await _client(handler).evaluate(_request())
    assert calls["n"] == 2 and len(resp.results) == 3


async def test_rejects_answer_outside_schema():
    data = json.loads(json.dumps(GOOD))
    data["01"]["answer"] = "na"
    with pytest.raises(MLClientError):
        await _client(lambda r: httpx.Response(200, json=_completion(data))).evaluate(_request())


async def test_bad_request_is_not_retried():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad"})

    with pytest.raises(MLClientError):
        await _client(handler).evaluate(_request())
    assert calls["n"] == 1


async def test_local_server_is_not_masked():
    seen = {}

    def handler(req):
        seen["user"] = json.loads(req.content)["messages"][1]["content"]
        return httpx.Response(200, json=_completion(GOOD))

    resp = await _client(handler, base_url="http://localhost:11434/v1").evaluate(_request())
    assert "900101300123" in seen["user"]
    assert resp.model.provider == "local"


def test_schema_has_no_na_when_not_allowed():
    s = response_schema(CRITERIA)
    assert "na" not in s["properties"]["08"]["properties"]["answer"]["enum"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ИИН 900101300123", "ИИН [IIN]"),
        ("карта 4400-4301-2345-6789", "карта [CARD]"),
        ("карта 4111 1111 1111 1111", "карта [CARD]"),
        ("звоните 8 (701) 123-45-67", "звоните [PHONE]"),
        ("пишите a.b@mail.kz", "пишите [EMAIL]"),
        ("счёт KZ86125KZT5004100100", "счёт [IBAN]"),
        ("заявка №12345 от 2024 года", "заявка №12345 от 2024 года"),
    ],
)
def test_pii_mask(text, expected):
    assert pii.mask(text) == expected


def test_pii_counter():
    c: Counter[str] = Counter()
    pii.mask("4111111111111111 и 900101300123", c)
    assert c == {"card": 1, "iin": 1}


async def _no_sleep(_):
    return None


async def test_gated_client_serialises_calls():
    import asyncio

    from app.ml.base import GatedMLClient

    state = {"now": 0, "max": 0}

    class Slow:
        name = "slow"

        async def evaluate(self, request):
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
            await asyncio.sleep(0.01)
            state["now"] -= 1
            return "ok"

        async def health(self):
            return True

        async def aclose(self):
            return None

    gate = asyncio.Lock()
    client = GatedMLClient(Slow(), gate)
    assert client.name == "slow"
    assert await asyncio.gather(*(client.evaluate(_request()) for _ in range(4))) == ["ok"] * 4
    assert state["max"] == 1


def test_ml_is_local():
    from app.core.config import Settings
    from app.ml import ml_is_local

    assert ml_is_local(Settings(ml_provider="http", ml_service_url="http://127.0.0.1:8001"))
    assert not ml_is_local(Settings(ml_provider="http", ml_service_url="https://ml.example.com"))
    assert ml_is_local(Settings(ml_provider="openai", openai_base_url="http://localhost:11434/v1"))
    assert not ml_is_local(Settings(ml_provider="openai"))
    assert not ml_is_local(Settings(ml_provider="mock"))


async def test_reasoning_effort_is_sent():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=_completion(GOOD))

    chat = OpenAIChat(
        api_key="k",
        base_url="https://api.test/v1",
        model="m",
        temperature=None,
        reasoning_effort="low",
        transport=httpx.MockTransport(handler),
    )
    await OpenAIMLClient(chat).evaluate(_request())
    assert seen["body"]["reasoning_effort"] == "low" and "temperature" not in seen["body"]
