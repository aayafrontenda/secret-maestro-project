import json

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


def test_a_prompt_that_fills_the_window_is_resent_with_a_larger_one(monkeypatch):
    windows = []

    def handler(request):
        num_ctx = json.loads(request.content)["options"]["num_ctx"]
        windows.append(num_ctx)
        # Simulate Ollama cutting the prompt to fit a small window.
        prompt_tokens = 9000 if num_ctx > 9000 else num_ctx - 10
        return httpx.Response(200, json={**OK, "prompt_eval_count": prompt_tokens})

    client = OllamaClient(model="m", num_ctx=8192)
    client.http = httpx.Client(transport=httpx.MockTransport(handler))
    client.complete("s", "u", {})
    assert windows == [8192, 16384]
    client.complete("s", "u", {})
    assert windows[-1] == 16384  # the larger window is kept, so the model is not reloaded


def test_window_is_sized_for_cyrillic_text():
    windows = []

    def handler(request):
        windows.append(json.loads(request.content)["options"]["num_ctx"])
        return httpx.Response(200, json=OK)

    client = OllamaClient(model="m", num_ctx=8192)
    client.http = httpx.Client(transport=httpx.MockTransport(handler))
    client.complete("s", "я" * 30000, {})
    assert windows[0] >= 15000


def test_client_errors_are_not_retried(monkeypatch):
    client = client_with([httpx.Response(404, text="model not found")], monkeypatch)
    with pytest.raises(LLMUnavailable, match="404"):
        client.complete("s", "u", {})


def test_cut_off_answer_is_repeated_with_a_larger_limit():
    sent = []
    replies = iter([{**OK, "done_reason": "length"}, OK])

    def handler(request):
        sent.append(json.loads(request.content)["options"]["num_predict"])
        return httpx.Response(200, json=next(replies))

    client = OllamaClient(model="m", num_predict=384)
    client.http = httpx.Client(transport=httpx.MockTransport(handler))
    assert client.complete("s", "u", {}).content.startswith("{")
    assert sent == [384, 768]


def test_per_call_think_overrides_the_client_and_raises_the_token_limit():
    import json as _json

    sent = []

    def handler(request):
        sent.append(_json.loads(request.content))
        return httpx.Response(200, json=OK)

    client = OllamaClient(model="m", think=False, num_predict=384, think_predict=4096)
    client.http = httpx.Client(transport=httpx.MockTransport(handler))
    client.complete("s", "u", {})
    client.complete("s", "u", {}, think=True)
    client.complete("s", "u", {}, think=False)
    assert [p["think"] for p in sent] == [False, True, False]
    assert [p["options"]["num_predict"] for p in sent] == [384, 4096, 384]
