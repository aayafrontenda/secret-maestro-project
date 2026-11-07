import httpx
import pytest

from maestro import llm as llm_module
from maestro.llm import LLMUnavailable, OllamaClient

OK = {"message": {"content": '{"why": "x", "answer": true, "message": "none"}'}, "prompt_eval_count": 50, "eval_count": 10}


def client_with(responses, monkeypatch):
    monkeypatch.setattr(llm_module, "RETRY_DELAYS", (0.0, 0.0))
    calls = iter(responses)

    def handler(request):
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    client = OllamaClient(model="m")
    client.http = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_runner_crash_is_retried(monkeypatch):
    client = client_with([httpx.Response(500, text="runner crashed"), httpx.Response(200, json=OK)], monkeypatch)
    assert client.complete("s", "u", {}).content.startswith("{")


def test_connection_errors_are_retried_then_reported(monkeypatch):
    error = httpx.ConnectError("refused")
    client = client_with([error, error, error], monkeypatch)
    with pytest.raises(LLMUnavailable, match="after 3 attempts"):
        client.complete("s", "u", {})


def test_client_errors_are_not_retried(monkeypatch):
    client = client_with([httpx.Response(404, text="model not found")], monkeypatch)
    with pytest.raises(LLMUnavailable, match="404"):
        client.complete("s", "u", {})
