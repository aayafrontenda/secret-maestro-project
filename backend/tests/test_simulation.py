"""Dry run of a checklist draft on evaluated dialogs."""

import copy

from httpx import AsyncClient

from app.ml.schemas import MLEvaluateRequest
from tests.test_insights import API, ScriptedML, _evaluate, _use


class RecordingML(ScriptedML):
    def __init__(self, plan: dict[str, str]) -> None:
        super().__init__(plan)
        self.sent: list[tuple[str, list[str]]] = []

    async def evaluate(self, request: MLEvaluateRequest):
        self.sent.append((request.conversation_id, [c.code for c in request.criteria]))
        return await super().evaluate(request)


async def _setup(client: AsyncClient) -> dict:
    _use(client, ScriptedML({}))
    evs = [await _evaluate(client, f"p1-ru-00{i}") for i in (1, 2, 3)]
    # A reviewer decided that p1-ru-001 failed c01, against the model's "yes".
    a = (
        await client.post(
            f"{API}/appeals",
            json={"evaluation_id": evs[0]["evaluation_id"], "criterion_id": "c01", "comment": "x"},
        )
    ).json()
    d = await client.post(
        f"{API}/appeals/{a['appeal_id']}/decision",
        json={"action": "change", "answer": "no", "reason": "no greeting"},
    )
    assert d.status_code == 200, d.text
    return (await client.get(f"{API}/checklists/active")).json()


async def test_simulation_reruns_only_changed_criteria(seeded: AsyncClient):
    doc = await _setup(seeded)
    draft = copy.deepcopy(doc)
    c01 = next(c for c in draft["criteria"] if c["id"] == "c01")
    c01["description"] += " Приветствие должно быть в первой реплике."

    ml = RecordingML({"p1-ru-001": "bad"})  # under the new wording the model says "no" there
    _use(seeded, ml)
    r = await seeded.post(f"{API}/checklists/active/simulate", json={"document": draft, "limit": 5})
    assert r.status_code == 200, r.text
    out = r.json()

    assert [c["criterion_id"] for c in out["changed_criteria"]] == ["c01"]
    assert out["changed_criteria"][0]["fields"] == ["rule"]
    assert all(codes == ["c01"] for _, codes in ml.sent)
    assert out["sample"] == 3 and out["failed"] == 0
    # The dialog with a reviewer's decision on c01 comes first.
    assert out["dialogs"][0]["conversation_id"] == "p1-ru-001"
    first = out["dialogs"][0]["changes"][0]
    assert first["model_answer"] == "yes" and first["human_answer"] == "no"
    assert first["old_answer"] == "no" and first["new_answer"] == "no" and not first["changed"]

    stat = out["criteria"][0]
    assert stat == {
        **stat,
        "evaluated": 3,
        "changed": 0,
        "human_decided": 1,
        "agree_before": 0,
        "agree_after": 1,
    }
    # Nothing was stored: the active checklist and the evaluations are unchanged.
    assert (await seeded.get(f"{API}/checklists/active")).json()["version"] == doc["version"]


async def test_simulation_weight_change_needs_no_model(seeded: AsyncClient):
    doc = await _setup(seeded)
    draft = copy.deepcopy(doc)
    scored = [c for c in draft["criteria"] if c["type"] != "flag"]
    scored[0]["weight"] += 5
    scored[1]["weight"] -= 5

    ml = RecordingML({})
    _use(seeded, ml)
    out = (await seeded.post(f"{API}/checklists/active/simulate", json={"document": draft})).json()
    assert ml.sent == []
    assert out["changed_criteria"] == [] and out["dialogs_changed"] == 0
    assert out["sample"] == 3
    # p1-ru-001 lost c01 after the appeal, so a different weight changes its total.
    by_id = {d["conversation_id"]: d for d in out["dialogs"]}
    assert by_id["p1-ru-001"]["new_total"] != by_id["p1-ru-001"]["old_total"]
    assert by_id["p1-ru-002"]["new_total"] == by_id["p1-ru-002"]["old_total"] == 100


async def test_simulation_rejects_invalid_draft(seeded: AsyncClient):
    doc = await _setup(seeded)
    draft = copy.deepcopy(doc)
    draft["criteria"][0]["weight"] += 7
    r = await seeded.post(f"{API}/checklists/active/simulate", json={"document": draft})
    assert r.status_code == 422 and "100" in r.json()["error"]
