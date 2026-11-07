"""The API contract (docs/API_CONTRACT.md)."""

import json
from pathlib import Path

import pytest
from httpx import AsyncClient

UI = "/api"
DEFAULT_DOC = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "checklist.default.json").read_text("utf-8")
)


@pytest.fixture
async def ui(client: AsyncClient, dev_dataset: dict) -> AsyncClient:
    r = await client.post(f"{UI}/datasets/upload", json={"name": "DEV", "payload": dev_dataset})
    assert r.status_code == 200, r.text
    assert r.json() == {"group_id": "DEV", "imported": 65}
    return client


# --- datasets & dialogs ---------------------------------------------------------------------


async def test_upload_accepts_bare_record_list(client: AsyncClient, dev_dataset: dict):
    r = await client.post(
        f"{UI}/datasets/upload",
        json={"name": "control", "payload": dev_dataset["data"]["records"][:3]},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"group_id": "CONTROL", "imported": 3}


async def test_upload_rejects_garbage_with_error_key(client: AsyncClient):
    r = await client.post(f"{UI}/datasets/upload", json={"payload": {"nope": 1}})
    assert r.status_code == 422
    assert "error" in r.json()


async def test_import_without_organizer_url_is_503(client: AsyncClient):
    r = await client.post(f"{UI}/datasets/import", json={"group_id": "DEV"})
    assert r.status_code == 503
    assert r.json()["error"]


async def test_list_dialogs_rows(ui: AsyncClient):
    r = await ui.get(f"{UI}/dialogs")
    rows = r.json()
    assert len(rows) == 65
    row = next(x for x in rows if x["conversation_id"] == "p1-ru-001")
    assert row == {
        "conversation_id": "p1-ru-001",
        "channel": "agent chat",
        "language": "RU",
        "group_id": "DEV",
        "turns": row["turns"],
        "evaluation": "none",
        "total": None,
        "gross_error": False,
        "checklist_version": None,
        "evaluated_at": None,
        "appeals_open": 0,
        "appeals_total": 0,
        "review_status": "none",
        "reviewed_at": None,
        "reviewed_by": None,
    }
    assert row["turns"] > 0


async def test_get_dialog_is_organizer_record(ui: AsyncClient):
    r = await ui.get(f"{UI}/dialogs/p4-ru-001")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {
        "conversation_id",
        "channel",
        "language",
        "group_id",
        "transcript",
        "audio_url",
    }
    assert set(d["transcript"][0]) == {"timestamp", "speaker", "text"}
    assert d["audio_url"].startswith("https://")

    r = await ui.get(f"{UI}/dialogs/missing")
    assert r.status_code == 404
    assert r.json()["error"]


async def test_audio_for_chat_is_null(ui: AsyncClient):
    r = await ui.get(f"{UI}/dialogs/p1-ru-001/audio")
    assert r.status_code == 200
    assert r.json() == {"url": None, "player_url": None, "expires_at": None}


async def test_audio_for_call_resolves_player_page(
    ui: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    import httpx

    from app.services import audio

    audio.clear_cache()
    page = '<html><audio controls><source src="https://x.crm11.dynamics.com/api/filedownload/1?a=1&amp;sig=abc" type="audio/mpeg"></audio></html>'

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url):
            return httpx.Response(200, text=page, headers={"content-type": "text/html"})

    monkeypatch.setattr(audio.httpx, "AsyncClient", FakeClient)
    r = await ui.get(f"{UI}/dialogs/p4-ru-001/audio")
    assert r.status_code == 200
    body = r.json()
    assert body["url"] == "https://x.crm11.dynamics.com/api/filedownload/1?a=1&sig=abc"
    assert body["player_url"].startswith("https://")
    assert body["expires_at"]
    audio.clear_cache()


async def test_no_evaluation_is_404(ui: AsyncClient):
    r = await ui.get(f"{UI}/dialogs/p1-ru-001/evaluation")
    assert r.status_code == 404


# --- checklist ------------------------------------------------------------------------------


async def test_active_checklist_is_the_ui_document(client: AsyncClient):
    r = await client.get(f"{UI}/checklists/active")
    doc = r.json()
    assert doc["id"] == "chat-quality"
    assert doc["version"] == 1
    assert doc["name"] == DEFAULT_DOC["name"]
    assert [c["id"] for c in doc["criteria"]] == [c["id"] for c in DEFAULT_DOC["criteria"]]
    assert doc["sections"] == DEFAULT_DOC["sections"]
    assert doc["rules"]["rounding"] == 2
    assert doc["criteria"][3]["scale"] == DEFAULT_DOC["criteria"][3]["scale"]

    r = await client.get(f"{UI}/checklists/active/versions")
    assert r.json() == [
        {"version": 1, "name": doc["name"], "updated_at": doc["updated_at"], "criteria": 8}
    ]


async def test_save_creates_new_version_and_reset_restores(client: AsyncClient):
    doc = (await client.get(f"{UI}/checklists/active")).json()
    # Swap c08 (flag) for a new scored criterion and rebalance weights to 100.
    doc["criteria"] = [c for c in doc["criteria"] if c["id"] != "c08"]
    doc["criteria"][0]["weight"] = 5  # c01: 10 -> 5
    doc["criteria"].append(
        {
            "id": "cupsell",
            "code": "08",
            "section": "s3",
            "name": "Предложение продукта",
            "type": "binary",
            "weight": 5,
            "na_allowed": True,
            "na_condition": "Подходящего продукта нет.",
            "description": "Да — оператор предложил релевантный продукт.",
        }
    )
    doc["name"] = "Чек-лист v2"
    r = await client.put(f"{UI}/checklists/active", json=doc)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["version"] == 2
    assert saved["name"] == "Чек-лист v2"
    assert saved["updated_at"]
    assert [c["id"] for c in saved["criteria"]][-1] == "cupsell"

    versions = (await client.get(f"{UI}/checklists/active/versions")).json()
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[1]["criteria"] == 8

    # Old versions stay retrievable.
    v1 = (await client.get(f"{UI}/checklists/active/versions/1")).json()
    assert [c["id"] for c in v1["criteria"]][-1] == "c08"
    assert (await client.get(f"{UI}/checklists/active/versions/9")).status_code == 404

    r = await client.post(f"{UI}/checklists/active/reset")
    assert r.status_code == 200
    assert r.json()["version"] == 3
    assert [c["id"] for c in r.json()["criteria"]] == [c["id"] for c in DEFAULT_DOC["criteria"]]
    assert len((await client.get(f"{UI}/checklists/active/versions")).json()) == 3


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda d: d["criteria"][0].update(weight=50), "sum to"),
        (lambda d: d["criteria"][0].update(name=""), "name is required"),
        (lambda d: d["criteria"][1].update(na_condition=""), "na_condition"),
        (lambda d: d["criteria"][3].update(scale=[{"value": 20}]), "at least 2 steps"),
        (lambda d: d["criteria"][3].update(scale=[{"value": 20}, {"value": 20}]), "unique"),
        (lambda d: d["criteria"].append(dict(d["criteria"][0])), "ids must be unique"),
    ],
)
async def test_save_validation(client: AsyncClient, mutate, fragment):
    doc = (await client.get(f"{UI}/checklists/active")).json()
    mutate(doc)
    r = await client.put(f"{UI}/checklists/active", json=doc)
    assert r.status_code == 422, r.text
    assert fragment in r.json()["error"]
    assert (await client.get(f"{UI}/checklists/active")).json()["version"] == 1


# --- evaluation -----------------------------------------------------------------------------


async def test_evaluate_returns_contract_shape(ui: AsyncClient):
    r = await ui.post(
        f"{UI}/evaluations", json={"conversation_id": "p1-ru-001", "checklist_id": "chat-quality"}
    )
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["status"] == "completed"
    assert isinstance(ev["evaluation_id"], int)
    assert ev["conversation_id"] == "p1-ru-001"
    assert ev["checklist_id"] == "chat-quality"
    assert ev["checklist_version"] == 1
    assert ev["checklist"]["criteria"][0]["id"] == "c01"
    assert ev["model"] and ev["is_mock"] is True
    assert ev["created_at"].endswith("Z")
    assert isinstance(ev["latency_ms"], int)
    assert ev["cost_usd"] == 0
    assert ev["tokens"] == {"input": 0, "output": 0}
    assert len(ev["results"]) == 8
    turns = (await ui.get(f"{UI}/dialogs/p1-ru-001")).json()["transcript"]
    for res in ev["results"]:
        assert res["criterion_id"].startswith("c0")
        assert res["answer"] in ("yes", "no", "na") or isinstance(res["answer"], int)
        assert res["explanation"]
        for e in res["evidence"]:
            assert 0 <= e["msg"] < len(turns)
            assert e["quote"] == turns[e["msg"]]["text"]
        if res["checked_range"]:
            a, b = res["checked_range"]
            assert 0 <= a <= b < len(turns)
        if res["answer"] == "na":
            assert res["na_reason"]
    assert ev["total"] == ev["final_total"]

    # The latest evaluation is now exposed and the list row is updated.
    again = (await ui.get(f"{UI}/dialogs/p1-ru-001/evaluation")).json()
    assert again["evaluation_id"] == ev["evaluation_id"]
    row = next(
        x for x in (await ui.get(f"{UI}/dialogs")).json() if x["conversation_id"] == "p1-ru-001"
    )
    assert row["evaluation"] == "done"
    assert row["total"] == ev["final_total"]
    assert row["checklist_version"] == 1
    assert row["evaluated_at"]


async def test_evaluate_unknown_dialog(ui: AsyncClient):
    r = await ui.post(f"{UI}/evaluations", json={"conversation_id": "ghost"})
    assert r.status_code == 404
    assert "ghost" in r.json()["error"]


async def test_evaluate_waits_and_reuses_in_flight(
    ui: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    import asyncio

    from app.ml.mock import MockMLClient

    slow = MockMLClient(delay_s=0.4)
    ui.app.state.ml = slow  # type: ignore[attr-defined]
    ui.app.state.queue._ml = slow  # type: ignore[attr-defined]

    # Two concurrent requests for the same dialog share one evaluation.
    r1, r2 = await asyncio.gather(
        ui.post(f"{UI}/evaluations", json={"conversation_id": "p1-ru-002"}),
        ui.post(f"{UI}/evaluations", json={"conversation_id": "p1-ru-002"}),
    )
    assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
    assert r1.json()["evaluation_id"] == r2.json()["evaluation_id"]
    assert r1.json()["status"] == "completed"
    history = (await ui.get(f"{UI}/dialogs/p1-ru-002/evaluations")).json()
    assert len(history) == 1


async def test_evaluate_timeout_returns_in_progress(
    ui: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    from app.core import config
    from app.ml.mock import MockMLClient

    monkeypatch.setattr(config.get_settings(), "evaluation_wait_s", 0.05)
    slow = MockMLClient(delay_s=0.5)
    ui.app.state.ml = slow  # type: ignore[attr-defined]
    ui.app.state.queue._ml = slow  # type: ignore[attr-defined]

    r = await ui.post(f"{UI}/evaluations", json={"conversation_id": "p1-ru-003"})
    assert r.status_code == 200
    assert r.json()["status"] in ("queued", "running")
    assert r.json()["results"] == []
    ev_id = r.json()["evaluation_id"]
    # Not yet listed as evaluated; polling the evaluation endpoint shows progress.
    assert (await ui.get(f"{UI}/dialogs/p1-ru-003/evaluation")).status_code == 404
    await ui.app.state.queue.join()  # type: ignore[attr-defined]
    assert (await ui.get(f"{UI}/evaluations/{ev_id}")).json()["status"] == "completed"
    assert (await ui.get(f"{UI}/dialogs/p1-ru-003/evaluation")).status_code == 200


async def test_evaluate_failure_is_502_with_message(ui: AsyncClient):
    class Broken:
        name = "broken"

        async def evaluate(self, request):
            raise RuntimeError("Ollama is down")

        async def health(self):
            return False

        async def aclose(self):
            return None

    ui.app.state.ml = Broken()  # type: ignore[attr-defined]
    ui.app.state.queue._ml = ui.app.state.ml  # type: ignore[attr-defined]
    r = await ui.post(f"{UI}/evaluations", json={"conversation_id": "p1-ru-004"})
    assert r.status_code == 502
    assert "Ollama is down" in r.json()["error"]
    # A failed attempt does not count as "evaluated", but is visible in the history.
    assert (await ui.get(f"{UI}/dialogs/p1-ru-004/evaluation")).status_code == 404
    history = (await ui.get(f"{UI}/dialogs/p1-ru-004/evaluations")).json()
    assert history[0]["status"] == "failed" and "Ollama is down" in history[0]["error"]


async def test_reevaluate_after_checklist_change_uses_new_version(ui: AsyncClient):
    first = (await ui.post(f"{UI}/evaluations", json={"conversation_id": "p1-kz-001"})).json()
    doc = (await ui.get(f"{UI}/checklists/active")).json()
    doc["criteria"][0]["description"] = "Да — оператор поздоровался и назвал имя."
    assert (await ui.put(f"{UI}/checklists/active", json=doc)).status_code == 200

    row = next(
        x for x in (await ui.get(f"{UI}/dialogs")).json() if x["conversation_id"] == "p1-kz-001"
    )
    assert row["checklist_version"] == 1  # stale until re-evaluated
    old = (await ui.get(f"{UI}/dialogs/p1-kz-001/evaluation")).json()
    assert (
        old["checklist"]["criteria"][0]["description"]
        == first["checklist"]["criteria"][0]["description"]
    )

    second = (await ui.post(f"{UI}/evaluations", json={"conversation_id": "p1-kz-001"})).json()
    assert second["checklist_version"] == 2
    assert second["checklist"]["criteria"][0]["description"].endswith("назвал имя.")
    assert second["evaluation_id"] != first["evaluation_id"]


# --- appeals --------------------------------------------------------------------------------


async def test_appeal_flow_in_ui_shape(ui: AsyncClient):
    ev = (await ui.post(f"{UI}/evaluations", json={"conversation_id": "p1-en-001"})).json()
    c01 = next(r for r in ev["results"] if r["criterion_id"] == "c01")

    r = await ui.post(
        f"{UI}/appeals",
        json={
            "evaluation_id": ev["evaluation_id"],
            "conversation_id": "p1-en-001",
            "criterion_id": "c01",
            "comment": "Operator did introduce themselves in #10.",
        },
    )
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["status"] == "open"
    assert a["decision"] is None
    assert a["criterion_id"] == "c01"
    assert a["criterion_name"] == "Установление контакта"
    assert a["original_answer"] == c01["answer"]
    assert a["conversation_id"] == "p1-en-001"
    assert a["evaluation_id"] == ev["evaluation_id"]

    # Listing by evaluation and by status.
    assert (
        len((await ui.get(f"{UI}/appeals", params={"evaluation_id": ev["evaluation_id"]})).json())
        == 1
    )
    assert len((await ui.get(f"{UI}/appeals", params={"status": "open"})).json()) == 1
    assert (await ui.get(f"{UI}/appeals", params={"status": "changed"})).json() == []
    row = next(
        x for x in (await ui.get(f"{UI}/dialogs")).json() if x["conversation_id"] == "p1-en-001"
    )
    assert row["appeals_open"] == 1 and row["appeals_total"] == 1

    # Duplicate open appeal is refused with a readable error.
    r = await ui.post(
        f"{UI}/appeals",
        json={"evaluation_id": ev["evaluation_id"], "criterion_id": "c01", "comment": "again"},
    )
    assert r.status_code == 409 and r.json()["error"]

    flip = "no" if c01["answer"] == "yes" else "yes"
    r = await ui.post(
        f"{UI}/appeals/{a['appeal_id']}/decision",
        json={"action": "change", "answer": flip, "reason": "Checked message #10."},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "changed"
    assert d["decision"]["action"] == "change"
    assert d["decision"]["answer"] == flip
    assert d["decision"]["reason"] == "Checked message #10."
    assert d["decision"]["decided_at"]

    # The evaluation keeps the original answer; the backend's final total moved.
    after = (await ui.get(f"{UI}/dialogs/p1-en-001/evaluation")).json()
    c01_after = next(r for r in after["results"] if r["criterion_id"] == "c01")
    assert c01_after["answer"] == c01["answer"]
    assert c01_after["final_answer"] == flip
    assert after["final_total"] != after["total"]
    row = next(
        x for x in (await ui.get(f"{UI}/dialogs")).json() if x["conversation_id"] == "p1-en-001"
    )
    assert row["total"] == after["final_total"]
    assert row["appeals_open"] == 0 and row["appeals_total"] == 1

    # Confirm path.
    b = (
        await ui.post(
            f"{UI}/appeals",
            json={"evaluation_id": ev["evaluation_id"], "criterion_id": "c05", "comment": "Hmm."},
        )
    ).json()
    r = await ui.post(
        f"{UI}/appeals/{b['appeal_id']}/decision", json={"action": "confirm", "reason": "Stands."}
    )
    assert r.json()["status"] == "confirmed"
    assert r.json()["decision"]["action"] == "confirm"
    assert r.json()["decision"]["answer"] is None


async def test_appeal_errors(ui: AsyncClient):
    ev = (await ui.post(f"{UI}/evaluations", json={"conversation_id": "p1-ru-005"})).json()
    r = await ui.post(
        f"{UI}/appeals", json={"evaluation_id": 9999, "criterion_id": "c01", "comment": "x"}
    )
    assert r.status_code == 404
    r = await ui.post(
        f"{UI}/appeals",
        json={"evaluation_id": ev["evaluation_id"], "criterion_id": "zzz", "comment": "x"},
    )
    assert r.status_code == 404
    a = (
        await ui.post(
            f"{UI}/appeals",
            json={"evaluation_id": ev["evaluation_id"], "criterion_id": "c01", "comment": "x"},
        )
    ).json()
    r = await ui.post(
        f"{UI}/appeals/{a['appeal_id']}/decision", json={"action": "change", "reason": "r"}
    )
    assert r.status_code == 422 and r.json()["error"]
    r = await ui.post(
        f"{UI}/appeals/{a['appeal_id']}/decision", json={"action": "nope", "reason": "r"}
    )
    assert r.status_code == 422
    r = await ui.post(
        f"{UI}/appeals/{a['appeal_id']}/decision",
        json={"action": "change", "answer": "na", "reason": "r"},
    )
    assert r.status_code == 409  # N/A not allowed on c01
    assert (
        await ui.post(f"{UI}/appeals/777/decision", json={"action": "confirm", "reason": "r"})
    ).status_code == 404
    assert (await ui.get(f"{UI}/appeals", params={"status": "weird"})).status_code == 422


async def test_cors_preflight(client: AsyncClient):
    r = await client.options(
        f"{UI}/evaluations",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
