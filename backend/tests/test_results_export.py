"""results.json in the organizers' format 1.0."""

from httpx import AsyncClient

from app.services.results_export import ORDER, model_info, validate
from tests.test_insights import ScriptedML, _evaluate, _use

API = "/api"


async def test_export_dev_set(seeded: AsyncClient):
    _use(seeded, ScriptedML({"p1-ru-001": "grave", "p1-ru-002": "bad", "p1-ru-003": "fail"}))
    for i in (1, 2, 3, 4):
        await _evaluate(seeded, f"p1-ru-00{i}")

    doc = (await seeded.get(f"{API}/results", params={"group_id": "DEV", "team": "Maestro"})).json()
    assert doc["schema_version"] == "1.0" and doc["team_name"] == "Maestro"
    assert doc["model"]["mode"] in ("local", "external_api", "hybrid")
    assert len(doc["results"]) == 65
    by_id = {r["conversation_id"]: r for r in doc["results"]}

    ok = by_id["p1-ru-004"]
    assert ok["status"] == "ok"
    assert [c["criterion_id"] for c in ok["criteria"]] == ORDER
    vals = {c["criterion_id"]: c["value"] for c in ok["criteria"]}
    assert vals["contact"] is True and vals["consultation"] == 20 and vals["dialogue"] == 10
    assert vals["critical"] is False and ok["score"] == {
        "final_score": 100.0,
        "critical_flag": False,
    }
    assert all(t >= 1 for c in ok["criteria"] for t in c["evidence_turns"])
    assert ok["criteria"][0]["evidence_turns"] == [2]  # message index 1 -> turn 2

    grave = by_id["p1-ru-001"]
    assert grave["score"]["critical_flag"] is True
    assert grave["criteria"][7] == {
        **grave["criteria"][7],
        "criterion_id": "critical",
        "value": True,
    }

    bad = by_id["p1-ru-002"]
    assert {c["criterion_id"]: c["value"] for c in bad["criteria"]}["consultation"] == 0
    assert bad["score"]["final_score"] == 0

    for cid in ("p1-ru-003", "p1-ru-005"):  # failed and never evaluated
        r = by_id[cid]
        assert r["status"] == "error" and r["criteria"] == [] and r["score"] is None and r["error"]

    assert validate(doc, 65) == []
    check = (
        await seeded.get(f"{API}/results/check", params={"group_id": "DEV", "expected": 65})
    ).json()
    assert check["ok"] == 3 and check["errors"] == 62 and check["problems"] == []

    r = await seeded.get(f"{API}/results", params={"group_id": "DEV", "download": True})
    assert r.headers["content-disposition"].endswith('"results.json"')
    groups = (await seeded.get(f"{API}/results/groups")).json()
    assert groups == [{"group_id": "DEV", "dialogs": 65}]


async def test_export_uses_final_answers_after_appeal(seeded: AsyncClient):
    _use(seeded, ScriptedML({"p1-ru-001": "grave"}))
    ev = await _evaluate(seeded, "p1-ru-001")
    a = (
        await seeded.post(
            f"{API}/appeals",
            json={"evaluation_id": ev["evaluation_id"], "criterion_id": "c08", "comment": "No."},
        )
    ).json()
    await seeded.post(
        f"{API}/appeals/{a['appeal_id']}/decision",
        json={"action": "change", "answer": "no", "reason": "Not a violation."},
    )
    doc = (await seeded.get(f"{API}/results", params={"group_id": "DEV"})).json()
    r = next(x for x in doc["results"] if x["conversation_id"] == "p1-ru-001")
    assert r["criteria"][7]["value"] is False and r["score"]["critical_flag"] is False
    assert "Not a violation." in r["criteria"][7]["rationale"]


async def test_na_is_null_and_needs_allowed_criteria(seeded: AsyncClient):
    class NA(ScriptedML):
        async def evaluate(self, request):
            resp = await super().evaluate(request)
            for r in resp.results:
                if r.code in ("c02", "c03", "c04", "c07"):
                    r.answer = "na"
            return resp

    _use(seeded, NA({}))
    await _evaluate(seeded, "p1-ru-001")
    doc = (await seeded.get(f"{API}/results", params={"group_id": "DEV"})).json()
    r = next(x for x in doc["results"] if x["conversation_id"] == "p1-ru-001")
    vals = {c["criterion_id"]: c["value"] for c in r["criteria"]}
    assert vals["discovery"] is None and vals["consultation"] is None and vals["closure"] is None
    assert r["score"]["final_score"] == 100.0
    assert validate({**doc, "results": [r]}) == []


def test_validate_catches_mistakes():
    good = {
        "conversation_id": "x",
        "status": "ok",
        "criteria": [
            {"criterion_id": c, "value": v, "rationale": "", "evidence_turns": [1]}
            for c, v in zip(ORDER, [True, None, None, 15, True, 7, True, False], strict=True)
        ],
        "score": {"final_score": 85.38, "critical_flag": False},
    }
    doc = {"model": {"mode": "local", "name": "m"}, "results": [good]}
    assert validate(doc, 1) == []
    bad = {**good, "criteria": [dict(c) for c in good["criteria"]]}
    bad["criteria"][0]["value"] = None  # contact has no N/A
    bad["criteria"][5]["value"] = 5  # not a dialogue step
    bad["criteria"][3]["value"] = False  # bool where a number is expected
    probs = validate({**doc, "results": [bad, bad]}, 10)
    assert any("10" in p for p in probs) and any("duplicate" in p for p in probs)
    assert sum("not allowed" in p for p in probs) == 6


def test_model_mode_detection():
    class E:
        def __init__(self, provider, name):
            self.provider, self.model_name = provider, name

    assert model_info([E("ollama", "qwen3.5:9b")]) == {"mode": "local", "name": "qwen3.5:9b"}
    assert model_info([E("openai", "gpt-5.6-luna")])["mode"] == "external_api"
    assert model_info([E("ollama", "qwen3.5:9b + gemini-3.7-flash")])["mode"] == "hybrid"
    doc = {"model": model_info([E("mock", "heuristic-v1")]), "results": []}
    assert any("mock" in p for p in validate(doc))
