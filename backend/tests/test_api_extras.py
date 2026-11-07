"""Beyond the UI contract: health, batches, retries, history, deletes, robustness."""

import asyncio

import pytest
from httpx import AsyncClient

from app.ml.schemas import MLCriterionResult, MLEvaluateRequest, MLEvaluateResponse, MLRange

API = "/api"


async def _wait_batch(client: AsyncClient, batch_id: str, timeout: float = 60) -> dict:
    await asyncio.wait_for(client.app.state.queue.join(), timeout)  # type: ignore[attr-defined]
    r = await client.get(f"{API}/evaluations/batch/{batch_id}")
    assert r.status_code == 200, r.text
    return r.json()


async def test_health_and_queue(client: AsyncClient):
    r = await client.get(f"{API}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["ml"] == {"provider": "mock", "reachable": True}
    assert body["queue"]["workers"] == 2
    assert (await client.get(f"{API}/queue")).json()["queued"] == 0
    assert (await client.get("/")).json()["api"] == "/api"


async def test_upload_file_endpoint(client: AsyncClient, dev_dataset: dict):
    import json

    payload = json.dumps(dev_dataset).encode("utf-8")
    r = await client.post(
        f"{API}/datasets/upload-file", files={"file": ("invoke.json", payload, "application/json")}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"group_id": "DEV", "imported": 65}
    r = await client.post(
        f"{API}/datasets/upload-file", files={"file": ("x.json", b"{nope", "application/json")}
    )
    assert r.status_code == 422 and r.json()["error"]


async def test_import_tolerates_unexpected_labels(client: AsyncClient):
    record = {
        "conversation_id": "ctrl-001",
        "channel": "Voice",
        "language": "kk-KZ",
        "transcript": [
            {"timestamp": 12, "speaker": "Agent", "text": "Сәлеметсіз бе"},
            {"timestamp": "00:05", "speaker": "Customer", "text": "Сәлем"},
            {"timestamp": None, "speaker": "weird_role", "text": ""},
        ],
        "audio_url": "",
    }
    r = await client.post(f"{API}/datasets/upload", json={"name": "ctrl", "payload": [record]})
    assert r.status_code == 200, r.text
    d = (await client.get(f"{API}/dialogs/ctrl-001")).json()
    assert d["channel"] == "voice call" and d["language"] == "KZ" and d["audio_url"] is None
    assert [m["speaker"] for m in d["transcript"]] == ["operator", "client", "weird_role"]
    assert d["transcript"][0]["timestamp"] == "12"
    r = await client.post(f"{API}/evaluations", json={"conversation_id": "ctrl-001"})
    assert r.status_code == 200 and r.json()["status"] == "completed"


async def test_list_filters(seeded: AsyncClient):
    assert len((await seeded.get(f"{API}/dialogs", params={"language": "kz"})).json()) == 15
    assert len((await seeded.get(f"{API}/dialogs", params={"channel": "voice call"})).json()) == 5
    assert (await seeded.get(f"{API}/dialogs", params={"group_id": "nope"})).json() == []


async def test_batch_all_then_only_new(seeded: AsyncClient):
    r = await seeded.post(f"{API}/evaluations/batch", json={})
    assert r.status_code == 202, r.text
    batch = r.json()
    assert batch["queued"] == 65 and batch["skipped"] == 0 and batch["checklist_version"] == 1
    done = await _wait_batch(seeded, batch["batch_id"])
    assert done["finished"] is True and done["completed"] == 65 and done["failed"] == 0

    rows = (await seeded.get(f"{API}/dialogs")).json()
    assert all(r["evaluation"] == "done" and r["total"] is not None for r in rows)
    listed = (
        await seeded.get(f"{API}/evaluations", params={"batch_id": batch["batch_id"], "limit": 500})
    ).json()
    assert len(listed) == 65 and all(e["status"] == "completed" for e in listed)

    r = await seeded.post(f"{API}/evaluations/batch", json={"only_new": True})
    assert r.json()["queued"] == 0 and r.json()["skipped"] == 65

    # After a checklist change only_new re-queues everything (version changed).
    doc = (await seeded.get(f"{API}/checklists/active")).json()
    doc["criteria"][0]["description"] += " (v2)"
    assert (await seeded.put(f"{API}/checklists/active", json=doc)).status_code == 200
    r = await seeded.post(
        f"{API}/evaluations/batch",
        json={"only_new": True, "conversation_ids": ["p1-ru-001", "p1-ru-002"]},
    )
    assert r.json()["queued"] == 2 and r.json()["checklist_version"] == 2
    await _wait_batch(seeded, r.json()["batch_id"])
    row = next(
        x
        for x in (await seeded.get(f"{API}/dialogs")).json()
        if x["conversation_id"] == "p1-ru-001"
    )
    assert row["checklist_version"] == 2

    assert (
        await seeded.post(f"{API}/evaluations/batch", json={"conversation_ids": ["ghost"]})
    ).status_code == 404
    assert (await seeded.get(f"{API}/evaluations/batch/nope")).status_code == 404
    assert (await seeded.get(f"{API}/evaluations", params={"status": "weird"})).status_code == 422


class BrokenML:
    name = "broken"

    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def evaluate(self, request: MLEvaluateRequest) -> MLEvaluateResponse:
        if self.mode == "raise":
            raise RuntimeError("model exploded")
        if self.mode == "missing":
            return MLEvaluateResponse(results=[MLCriterionResult(code="c01", answer="yes")])
        if self.mode == "sloppy":
            out = []
            for c in request.criteria:
                if c.code == "c01":
                    out.append(MLCriterionResult(code=c.code, answer="na", evidence=[999]))
                elif c.answer_type == "scale":
                    out.append(
                        MLCriterionResult(
                            code=c.code,
                            answer=17,
                            checked_range=MLRange(from_index=5, to_index=9999),
                        )
                    )
                else:
                    out.append(MLCriterionResult(code=c.code, answer="Да"))
            return MLEvaluateResponse(results=out)
        raise AssertionError(self.mode)

    async def health(self) -> bool:
        return False

    async def aclose(self) -> None:
        return None


def _use(client: AsyncClient, ml) -> None:
    client.app.state.ml = ml  # type: ignore[attr-defined]
    client.app.state.queue._ml = ml  # type: ignore[attr-defined]


async def test_model_crash_marks_failed_then_retry_works(seeded: AsyncClient):
    _use(seeded, BrokenML("raise"))
    r = await seeded.post(f"{API}/evaluations", json={"conversation_id": "p1-ru-001"})
    assert r.status_code == 502 and "model exploded" in r.json()["error"]
    stats = (await seeded.get(f"{API}/queue")).json()
    assert stats["workers"] == 2 and stats["running"] == 0  # worker survived

    failed = (await seeded.get(f"{API}/dialogs/p1-ru-001/evaluations")).json()[0]
    assert failed["status"] == "failed"
    assert (
        await seeded.post(f"{API}/evaluations/{failed['evaluation_id']}/retry")
    ).status_code == 202

    from app.ml.mock import MockMLClient

    # The retry was queued while the model was still broken -> fails again; fix the model, retry.
    await seeded.app.state.queue.join()  # type: ignore[attr-defined]
    _use(seeded, MockMLClient())
    r = await seeded.post(f"{API}/evaluations/{failed['evaluation_id']}/retry")
    assert r.status_code == 202
    await seeded.app.state.queue.join()  # type: ignore[attr-defined]
    ev = (await seeded.get(f"{API}/evaluations/{failed['evaluation_id']}")).json()
    assert ev["status"] == "completed" and len(ev["results"]) == 8
    assert (
        await seeded.post(f"{API}/evaluations/{failed['evaluation_id']}/retry")
    ).status_code == 409


async def test_missing_criteria_fail_loudly(seeded: AsyncClient):
    _use(seeded, BrokenML("missing"))
    r = await seeded.post(f"{API}/evaluations", json={"conversation_id": "p1-ru-002"})
    assert r.status_code == 502 and "missing criteria" in r.json()["error"]


async def test_sloppy_answers_are_normalised(seeded: AsyncClient):
    _use(seeded, BrokenML("sloppy"))
    r = await seeded.post(f"{API}/evaluations", json={"conversation_id": "p1-ru-003"})
    assert r.status_code == 200, r.text
    by = {x["criterion_id"]: x for x in r.json()["results"]}
    assert by["c01"]["answer"] == "no" and "N/A is not allowed" in by["c01"]["normalization_note"]
    assert by["c01"]["evidence"] == []  # out-of-range index dropped
    assert by["c04"]["answer"] == 15  # 17 snapped to the nearest step
    assert by["c04"]["checked_range"][1] < 999
    assert by["c06"]["answer"] == 10  # clamped to scale_max
    assert by["c02"]["answer"] == "yes"  # "Да" understood


async def test_delete_dialog_cascades(seeded: AsyncClient):
    ev = (await seeded.post(f"{API}/evaluations", json={"conversation_id": "p1-ru-004"})).json()
    a = (
        await seeded.post(
            f"{API}/appeals",
            json={"evaluation_id": ev["evaluation_id"], "criterion_id": "c01", "comment": "x"},
        )
    ).json()
    assert (await seeded.delete(f"{API}/dialogs/p1-ru-004")).status_code == 204
    assert (await seeded.get(f"{API}/dialogs/p1-ru-004")).status_code == 404
    assert (await seeded.get(f"{API}/evaluations/{ev['evaluation_id']}")).status_code == 404
    assert (await seeded.get(f"{API}/appeals/{a['appeal_id']}")).status_code == 404
    assert (await seeded.get(f"{API}/appeals")).json() == []


async def test_restart_requeues_unfinished(seeded: AsyncClient):
    """Evaluations left queued/running by a crash are picked up when the queue starts."""
    from app.services.queue import EvaluationQueue

    r = await seeded.post(f"{API}/evaluations/batch", json={"conversation_ids": ["p1-ru-005"]})
    await _wait_batch(seeded, r.json()["batch_id"])
    ev_id = r.json()["evaluation_ids"][0]

    from sqlalchemy import text

    from app.core.db import get_session_factory

    async with get_session_factory()() as s:
        await s.execute(text("update evaluations set status='running' where id=:id"), {"id": ev_id})
        await s.commit()

    q = EvaluationQueue(get_session_factory(), seeded.app.state.ml, workers=1)  # type: ignore[attr-defined]
    await q.start()
    await q.join()
    await q.stop()
    assert (await seeded.get(f"{API}/evaluations/{ev_id}")).json()["status"] == "completed"


@pytest.mark.parametrize("path", ["/api/v1/dialogs", "/api/v1/health"])
async def test_no_v1_left(client: AsyncClient, path: str):
    assert (await client.get(path)).status_code == 404
