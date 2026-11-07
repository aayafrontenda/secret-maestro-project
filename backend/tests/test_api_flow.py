"""End-to-end API flow: import -> checklist -> evaluate -> appeal -> decision -> recalculation."""

import asyncio

import pytest
from httpx import AsyncClient

API = "/api/v1"


async def _wait_completed(client: AsyncClient, evaluation_id: int, timeout: float = 10.0) -> dict:
    queue = client.app.state.queue  # type: ignore[attr-defined]
    await asyncio.wait_for(queue.join(), timeout)
    r = await client.get(f"{API}/evaluations/{evaluation_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed", body.get("error")
    return body


# --- system ---------------------------------------------------------------------------------


async def test_health(client: AsyncClient):
    r = await client.get(f"{API}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ml"]["provider"] == "mock"
    assert body["queue"]["workers"] == 2


async def test_default_checklist_is_seeded(client: AsyncClient):
    r = await client.get(f"{API}/checklists")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["is_default"] is True
    assert items[0]["criteria_count"] == 8
    assert items[0]["total_weight"] == 100

    r = await client.get(f"{API}/checklists/default")
    codes = [c["code"] for c in r.json()["criteria"]]
    assert codes == [f"c{i}" for i in range(1, 9)]
    c4 = next(c for c in r.json()["criteria"] if c["code"] == "c4")
    assert c4["answer_type"] == "scale" and c4["scale_max"] == 20
    assert [s["value"] for s in c4["scale_steps"]] == [20, 15, 10, 5, 0]


# --- dialogs --------------------------------------------------------------------------------


async def test_import_dev_dataset(client: AsyncClient, dev_dataset: dict):
    r = await client.post(f"{API}/dialogs", json=dev_dataset["data"]["records"])
    assert r.status_code == 201, r.text
    assert r.json()["created"] == 65

    r = await client.get(f"{API}/dialogs", params={"limit": 500})
    assert r.json()["total"] == 65
    langs = {d["language"] for d in r.json()["items"]}
    assert langs == {"RU", "KZ", "EN"}

    r = await client.get(f"{API}/dialogs", params={"channel": "voice call"})
    assert r.json()["total"] == 5
    assert all(d["audio_url"] for d in r.json()["items"])

    r = await client.get(f"{API}/dialogs/p1-ru-001")
    assert r.status_code == 200
    body = r.json()
    assert body["transcript"][0]["index"] == 0
    assert body["transcript"][0]["speaker"] == "client"
    assert body["transcript"][-1]["index"] == body["message_count"] - 1

    # Re-import is an upsert, not a duplicate.
    r = await client.post(f"{API}/dialogs", json=dev_dataset["data"]["records"][:3])
    assert r.json() == {
        "dataset_group_id": None,
        "received": 3,
        "created": 0,
        "updated": 3,
        "ids": [x["conversation_id"] for x in dev_dataset["data"]["records"][:3]],
    }


async def test_import_file_endpoint(client: AsyncClient, dev_dataset: dict):
    import json

    payload = json.dumps(dev_dataset).encode("utf-8")
    r = await client.post(
        f"{API}/dialogs/import-file", files={"file": ("invoke.json", payload, "application/json")}
    )
    assert r.status_code == 200, r.text
    assert r.json()["dataset_group_id"] == "DEV"
    assert r.json()["created"] == 65


async def test_import_from_api_requires_config(client: AsyncClient):
    r = await client.post(f"{API}/dialogs/import", json={"group_id": "DEV"})
    assert r.status_code == 503


async def test_upload_validation(client: AsyncClient):
    r = await client.post(
        f"{API}/dialogs",
        json={"conversation_id": "x", "channel": "sms", "language": "RU", "transcript": []},
    )
    assert r.status_code == 422


async def test_missing_dialog_404(client: AsyncClient):
    assert (await client.get(f"{API}/dialogs/nope")).status_code == 404
    assert (await client.get(f"{API}/dialogs/nope/audio")).status_code == 404


# --- checklists -----------------------------------------------------------------------------


async def test_checklist_crud_and_versioning(client: AsyncClient):
    r = await client.get(f"{API}/checklists/default")
    original = r.json()
    cid = original["id"]
    assert original["version"] == 1

    # Replace criterion c8 with a new scored criterion (the "swap one criterion" check).
    criteria = [c for c in original["criteria"] if c["code"] != "c8"]
    criteria.append(
        {
            "code": "c9",
            "title": "Upsell offered",
            "rule": "Yes — operator offered a relevant product",
            "answer_type": "yes_no",
            "weight": 10,
            "allow_na": True,
            "na_rule": "N/A — no suitable product",
        }
    )
    body = {"name": "Chat Quality v2", "description": "swapped c8 for c9", "criteria": criteria}
    r = await client.put(f"{API}/checklists/{cid}", json=body)
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["version"] == 2
    assert updated["name"] == "Chat Quality v2"
    assert [c["code"] for c in updated["criteria"]][-1] == "c9"
    assert updated["total_weight"] == 110

    # Duplicate + make default + delete rules.
    r = await client.post(f"{API}/checklists/{cid}/duplicate")
    assert r.status_code == 201
    copy_id = r.json()["id"]
    assert r.json()["is_default"] is False
    r = await client.post(f"{API}/checklists/{copy_id}/default")
    assert r.json()["is_default"] is True
    assert (await client.get(f"{API}/checklists/{cid}")).json()["is_default"] is False
    assert (await client.delete(f"{API}/checklists/{copy_id}")).status_code == 409
    assert (await client.delete(f"{API}/checklists/{cid}")).status_code == 204
    assert (await client.get(f"{API}/checklists/{cid}")).status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        {"code": "x", "title": "T", "answer_type": "scale", "weight": 10},  # no scale_max
        {"code": "x", "title": "T", "answer_type": "yes_no", "weight": 0},  # zero weight
        {"code": "bad code", "title": "T", "answer_type": "yes_no", "weight": 5},  # code chars
        {
            "code": "x",
            "title": "T",
            "answer_type": "scale",
            "weight": 10,
            "scale_max": 10,
            "scale_steps": [{"value": 20}, {"value": 0}],
        },  # top step != scale_max
    ],
)
async def test_checklist_validation(client: AsyncClient, bad: dict):
    r = await client.post(f"{API}/checklists", json={"name": "bad", "criteria": [bad]})
    assert r.status_code == 422, r.text


async def test_checklist_duplicate_codes_rejected(client: AsyncClient):
    c = {"code": "a", "title": "A", "answer_type": "yes_no", "weight": 5}
    r = await client.post(f"{API}/checklists", json={"name": "dup", "criteria": [c, c]})
    assert r.status_code == 422


# --- evaluations ----------------------------------------------------------------------------


async def test_evaluate_single_dialog_async(seeded: AsyncClient):
    r = await seeded.post(f"{API}/evaluations", json={"dialog_id": "p1-ru-001"})
    assert r.status_code == 202, r.text
    ev_id = r.json()["id"]
    assert r.json()["status"] in ("queued", "running", "completed")

    body = await _wait_completed(seeded, ev_id)
    assert body["checklist_id"] == 1
    assert body["checklist_snapshot"]["version"] == 1
    assert body["provider"] == "mock"
    assert len(body["results"]) == 8
    assert body["original_total"] is not None
    assert body["final_total"] == body["original_total"]
    assert 0 <= body["original_total"] <= 100

    # Every result carries what the UI must show.
    for res in body["results"]:
        assert res["answer"] in ("yes", "no", "na") or isinstance(res["answer"], int | float)
        assert res["explanation"]
        assert res["final_answer"] == res["answer"]
        if res["answer"] == "na":
            assert res["na_reason"]
            assert res["score"] is None
        elif res["is_flag"]:
            assert res["score"] is None
        else:
            assert res["score"] is not None
            assert res["effective_weight"] >= res["weight"]
        for e in res["evidence"]:
            assert {"message_index", "timestamp", "speaker", "text"} <= set(e)

    # Totals are consistent with per-criterion points (allowing for rounding).
    pts = sum(r["score"] for r in body["results"] if r["score"] is not None)
    assert abs(pts - body["original_total"]) < 0.05
    assert body["original_sections"]
    assert sum(s["max_points"] for s in body["original_sections"]) == pytest.approx(100, abs=0.05)

    # The dialog now exposes its latest evaluation.
    r = await seeded.get(f"{API}/dialogs/p1-ru-001")
    assert r.json()["latest_evaluation"]["id"] == ev_id


async def test_evaluate_sync(seeded: AsyncClient):
    r = await seeded.post(f"{API}/evaluations/sync", json={"dialog_id": "p1-kz-001"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"
    assert r.json()["dialog_id"] == "p1-kz-001"


async def test_evaluate_unknown_dialog_or_checklist(seeded: AsyncClient):
    assert (await seeded.post(f"{API}/evaluations", json={"dialog_id": "nope"})).status_code == 404
    r = await seeded.post(
        f"{API}/evaluations", json={"dialog_id": "p1-ru-001", "checklist_id": 999}
    )
    assert r.status_code == 404


async def test_batch_evaluation_all_dialogs(seeded: AsyncClient):
    r = await seeded.post(f"{API}/evaluations/batch", json={})
    assert r.status_code == 202, r.text
    batch = r.json()
    assert batch["queued"] == 65 and batch["skipped"] == 0

    queue = seeded.app.state.queue  # type: ignore[attr-defined]
    await asyncio.wait_for(queue.join(), 60)

    r = await seeded.get(f"{API}/evaluations/batch/{batch['batch_id']}")
    assert r.json()["finished"] is True
    assert r.json()["completed"] == 65 and r.json()["failed"] == 0

    r = await seeded.get(f"{API}/evaluations", params={"batch_id": batch["batch_id"], "limit": 500})
    assert r.json()["total"] == 65
    assert all(e["status"] == "completed" for e in r.json()["items"])

    # Second batch with skip_evaluated queues nothing.
    r = await seeded.post(f"{API}/evaluations/batch", json={"skip_evaluated": True})
    assert r.json()["queued"] == 0 and r.json()["skipped"] == 65

    # Subset batch with an unknown id fails loudly.
    r = await seeded.post(f"{API}/evaluations/batch", json={"dialog_ids": ["p1-ru-001", "ghost"]})
    assert r.status_code == 404


async def test_batch_unknown_404(seeded: AsyncClient):
    assert (await seeded.get(f"{API}/evaluations/batch/nope")).status_code == 404


async def test_evaluation_uses_snapshot_not_live_checklist(seeded: AsyncClient):
    r = await seeded.post(f"{API}/evaluations/sync", json={"dialog_id": "p1-ru-002"})
    ev = r.json()
    assert len(ev["results"]) == 8

    # Edit the checklist afterwards: the stored evaluation must not change.
    cl = (await seeded.get(f"{API}/checklists/default")).json()
    criteria = cl["criteria"][:3]
    r = await seeded.put(
        f"{API}/checklists/{cl['id']}", json={"name": "trimmed", "criteria": criteria}
    )
    assert r.status_code == 200
    again = (await seeded.get(f"{API}/evaluations/{ev['id']}")).json()
    assert len(again["results"]) == 8
    assert again["checklist_snapshot"]["version"] == 1

    # New evaluations use the new version.
    r = await seeded.post(f"{API}/evaluations/sync", json={"dialog_id": "p1-ru-002"})
    assert len(r.json()["results"]) == 3
    assert r.json()["checklist_snapshot"]["version"] == 2


async def test_delete_evaluation(seeded: AsyncClient):
    ev = (await seeded.post(f"{API}/evaluations/sync", json={"dialog_id": "p1-en-001"})).json()
    assert (await seeded.delete(f"{API}/evaluations/{ev['id']}")).status_code == 204
    assert (await seeded.get(f"{API}/evaluations/{ev['id']}")).status_code == 404


# --- appeals ---------------------------------------------------------------------------------


async def _evaluated(client: AsyncClient, dialog_id: str = "p1-ru-001") -> dict:
    r = await client.post(f"{API}/evaluations/sync", json={"dialog_id": dialog_id})
    assert r.status_code == 200, r.text
    return r.json()


async def test_appeal_confirm_keeps_scores(seeded: AsyncClient):
    ev = await _evaluated(seeded)
    target = next(r for r in ev["results"] if r["criterion_code"] == "c1")

    r = await seeded.post(
        f"{API}/evaluations/{ev['id']}/appeals",
        json={"criterion_result_id": target["id"], "comment": "The operator did greet the client."},
    )
    assert r.status_code == 201, r.text
    appeal = r.json()
    assert appeal["status"] == "pending"
    assert appeal["previous_answer"] == target["answer"]

    # Reviewer queue shows it with evidence and a transcript fragment.
    r = await seeded.get(f"{API}/appeals", params={"status": "pending"})
    assert r.json()["total"] == 1
    detail = (await seeded.get(f"{API}/appeals/{appeal['id']}")).json()
    assert detail["criterion_code"] == "c1"
    assert detail["dialog_id"] == "p1-ru-001"
    assert detail["fragment"]
    assert detail["explanation"] == target["explanation"]

    r = await seeded.post(
        f"{API}/appeals/{appeal['id']}/decision",
        json={"decision": "confirm", "reason": "Verdict stands."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed"
    assert r.json()["decided_at"]

    after = (await seeded.get(f"{API}/evaluations/{ev['id']}")).json()
    assert after["final_total"] == after["original_total"]
    c1 = next(r for r in after["results"] if r["criterion_code"] == "c1")
    assert c1["appeals"][0]["status"] == "confirmed"


async def test_appeal_change_recalculates_final_total(seeded: AsyncClient):
    ev = await _evaluated(seeded)
    c1 = next(r for r in ev["results"] if r["criterion_code"] == "c1")
    flip_to = "no" if c1["answer"] == "yes" else "yes"

    appeal = (
        await seeded.post(
            f"{API}/evaluations/{ev['id']}/appeals",
            json={"criterion_result_id": c1["id"], "comment": "Disagree."},
        )
    ).json()
    r = await seeded.post(
        f"{API}/appeals/{appeal['id']}/decision",
        json={"decision": "change", "new_answer": flip_to, "reason": "Re-read the first reply."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "changed"
    assert r.json()["new_answer"] == flip_to

    after = (await seeded.get(f"{API}/evaluations/{ev['id']}")).json()
    c1_after = next(r for r in after["results"] if r["criterion_code"] == "c1")
    assert c1_after["answer"] == c1["answer"]  # original is preserved
    assert c1_after["final_answer"] == flip_to
    delta = c1_after["final_score"] - (c1_after["score"] or 0)
    assert after["original_total"] == ev["original_total"]
    assert after["final_total"] == pytest.approx(after["original_total"] + delta, abs=0.02)
    assert after["final_total"] != after["original_total"]

    # A second appeal on the same criterion is allowed once the first is decided.
    r = await seeded.post(
        f"{API}/evaluations/{ev['id']}/appeals",
        json={"criterion_result_id": c1["id"], "comment": "Again."},
    )
    assert r.status_code == 201
    assert r.json()["previous_answer"] == flip_to


async def test_appeal_change_to_na_redistributes(seeded: AsyncClient):
    ev = await _evaluated(seeded)
    c3 = next(r for r in ev["results"] if r["criterion_code"] == "c3")
    if c3["answer"] == "na":
        new_answer = "no"
    else:
        new_answer = "na"
    appeal = (
        await seeded.post(
            f"{API}/evaluations/{ev['id']}/appeals",
            json={"criterion_result_id": c3["id"], "comment": "Applicability."},
        )
    ).json()
    r = await seeded.post(
        f"{API}/appeals/{appeal['id']}/decision",
        json={"decision": "change", "new_answer": new_answer, "reason": "Rule 3."},
    )
    assert r.status_code == 200, r.text
    after = (await seeded.get(f"{API}/evaluations/{ev['id']}")).json()
    weights = sum(r["final_effective_weight"] or 0 for r in after["results"])
    assert weights == pytest.approx(100, abs=0.05)


async def test_appeal_on_grave_flag_changes_final_flag_only(seeded: AsyncClient):
    ev = await _evaluated(seeded)
    c8 = next(r for r in ev["results"] if r["criterion_code"] == "c8")
    assert ev["grave_error"] is False
    appeal = (
        await seeded.post(
            f"{API}/evaluations/{ev['id']}/appeals",
            json={
                "criterion_result_id": c8["id"],
                "comment": "Operator asked for a private number.",
            },
        )
    ).json()
    r = await seeded.post(
        f"{API}/appeals/{appeal['id']}/decision",
        json={
            "decision": "change",
            "new_answer": "yes",
            "reason": "Message 7 is an off-platform offer.",
        },
    )
    assert r.status_code == 200, r.text
    after = (await seeded.get(f"{API}/evaluations/{ev['id']}")).json()
    assert after["grave_error"] is False
    assert after["final_grave_error"] is True
    assert after["final_total"] == after["original_total"]


async def test_appeal_rules(seeded: AsyncClient):
    ev = await _evaluated(seeded)
    c1 = next(r for r in ev["results"] if r["criterion_code"] == "c1")

    # Second pending appeal on the same criterion is rejected.
    r = await seeded.post(
        f"{API}/evaluations/{ev['id']}/appeals",
        json={"criterion_result_id": c1["id"], "comment": "one"},
    )
    assert r.status_code == 201
    appeal_id = r.json()["id"]
    r = await seeded.post(
        f"{API}/evaluations/{ev['id']}/appeals",
        json={"criterion_result_id": c1["id"], "comment": "two"},
    )
    assert r.status_code == 409

    # Wrong criterion id for this evaluation.
    r = await seeded.post(
        f"{API}/evaluations/{ev['id']}/appeals",
        json={"criterion_result_id": 999999, "comment": "x"},
    )
    assert r.status_code == 409

    # change requires new_answer; N/A not allowed on c1; same answer must use confirm.
    r = await seeded.post(
        f"{API}/appeals/{appeal_id}/decision", json={"decision": "change", "reason": "r"}
    )
    assert r.status_code == 422
    r = await seeded.post(
        f"{API}/appeals/{appeal_id}/decision",
        json={"decision": "change", "new_answer": "na", "reason": "r"},
    )
    assert r.status_code == 409
    r = await seeded.post(
        f"{API}/appeals/{appeal_id}/decision",
        json={"decision": "change", "new_answer": c1["answer"], "reason": "r"},
    )
    assert r.status_code == 409

    # Decide, then it cannot be decided again.
    r = await seeded.post(
        f"{API}/appeals/{appeal_id}/decision", json={"decision": "confirm", "reason": "ok"}
    )
    assert r.status_code == 200
    r = await seeded.post(
        f"{API}/appeals/{appeal_id}/decision", json={"decision": "confirm", "reason": "again"}
    )
    assert r.status_code == 409

    assert (await seeded.get(f"{API}/appeals/424242")).status_code == 404


# --- robustness ------------------------------------------------------------------------------


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
    r = await client.post(f"{API}/dialogs", json=record)
    assert r.status_code == 201, r.text
    d = (await client.get(f"{API}/dialogs/ctrl-001")).json()
    assert d["channel"] == "voice call"
    assert d["language"] == "KZ"
    assert d["audio_url"] is None
    assert [m["speaker"] for m in d["transcript"]] == ["operator", "client", "weird_role"]
    assert d["transcript"][0]["timestamp"] == "12"

    # Still evaluable.
    r = await client.post(f"{API}/evaluations/sync", json={"dialog_id": "ctrl-001"})
    assert r.status_code == 200 and r.json()["status"] == "completed"


async def test_delete_dialog_cascades(seeded: AsyncClient):
    ev = await _evaluated(seeded, "p1-ru-004")
    c1 = next(r for r in ev["results"] if r["criterion_code"] == "c1")
    r = await seeded.post(
        f"{API}/evaluations/{ev['id']}/appeals",
        json={"criterion_result_id": c1["id"], "comment": "x"},
    )
    appeal_id = r.json()["id"]

    assert (await seeded.delete(f"{API}/dialogs/p1-ru-004")).status_code == 204
    assert (await seeded.get(f"{API}/dialogs/p1-ru-004")).status_code == 404
    assert (await seeded.get(f"{API}/evaluations/{ev['id']}")).status_code == 404
    assert (await seeded.get(f"{API}/appeals/{appeal_id}")).status_code == 404
    assert (await seeded.get(f"{API}/appeals")).json()["total"] == 0


async def test_list_filters_and_pagination(seeded: AsyncClient):
    r = await seeded.get(f"{API}/dialogs", params={"language": "kz", "limit": 10, "offset": 10})
    body = r.json()
    assert body["total"] == 15 and len(body["items"]) == 5
    r = await seeded.get(f"{API}/dialogs", params={"q": "p4-"})
    assert r.json()["total"] == 5
    r = await seeded.get(f"{API}/dialogs", params={"group_id": "nope"})
    assert r.json()["total"] == 0
