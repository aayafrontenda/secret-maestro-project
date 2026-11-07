"""HttpMLClient against a fake ML service (httpx MockTransport)."""

import httpx
import pytest

from app.ml.base import MLClientError
from app.ml.http import HttpMLClient
from app.ml.schemas import MLCriterion, MLEvaluateRequest, MLTranscriptMessage


def _request() -> MLEvaluateRequest:
    return MLEvaluateRequest(
        conversation_id="d1",
        channel="agent chat",
        language="RU",
        transcript=[
            MLTranscriptMessage(index=0, timestamp="00:00", speaker="operator", text="Здравствуйте")
        ],
        criteria=[
            MLCriterion(
                code="c1",
                title="Contact",
                rule="r",
                answer_type="yes_no",
                weight=10,
                allow_na=False,
            )
        ],
    )


def _client(handler) -> HttpMLClient:
    c = HttpMLClient("http://ml.test", timeout_s=5, max_retries=2)
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ml.test")
    return c


async def test_happy_path_parses_contract():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.read()
        return httpx.Response(
            200,
            json={
                "results": [{"code": "c1", "answer": "yes", "explanation": "ok", "evidence": [0]}],
                "model": {"provider": "openai", "name": "gpt-x"},
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "calls": 1,
                    "cost_usd": 0.001,
                },
            },
        )

    client = _client(handler)
    resp = await client.evaluate(_request())
    assert seen["path"] == "/evaluate"
    assert b'"conversation_id":"d1"' in seen["body"]
    assert resp.results[0].answer == "yes"
    assert resp.model.name == "gpt-x"
    assert resp.usage.cost_usd == 0.001


async def test_retries_on_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    import app.ml.http as http_module

    async def no_sleep(_):
        return None

    monkeypatch.setattr(http_module.asyncio, "sleep", no_sleep)
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"results": [{"code": "c1", "answer": "no"}]})

    resp = await _client(handler).evaluate(_request())
    assert calls["n"] == 3
    assert resp.results[0].answer == "no"


async def test_gives_up_after_retries(monkeypatch: pytest.MonkeyPatch):
    import app.ml.http as http_module

    async def no_sleep(_):
        return None

    monkeypatch.setattr(http_module.asyncio, "sleep", no_sleep)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(MLClientError, match="unavailable after 3 attempts"):
        await _client(handler).evaluate(_request())


async def test_4xx_is_not_retried():
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(422, text="bad request")

    with pytest.raises(MLClientError, match="rejected"):
        await _client(handler).evaluate(_request())
    assert calls["n"] == 1


async def test_invalid_payload_is_rejected():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"code": "c1"}]})  # missing answer

    with pytest.raises(MLClientError, match="invalid response"):
        await _client(handler).evaluate(_request())


async def test_health_false_when_down():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert await _client(handler).health() is False
