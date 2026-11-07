"""Evaluation pipeline robustness: bad ML output must fail the evaluation, never the worker."""

import asyncio

from httpx import AsyncClient

from app.ml.schemas import MLCriterionResult, MLEvaluateRequest, MLEvaluateResponse, MLRange

API = "/api/v1"


class BrokenML:
    name = "broken"

    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def evaluate(self, request: MLEvaluateRequest) -> MLEvaluateResponse:
        if self.mode == "raise":
            raise RuntimeError("model exploded")
        if self.mode == "missing":
            return MLEvaluateResponse(results=[MLCriterionResult(code="c1", answer="yes")])
        if self.mode == "garbage":
            return MLEvaluateResponse(
                results=[MLCriterionResult(code=c.code, answer="maybe") for c in request.criteria]
            )
        if self.mode == "sloppy":
            # N/A where it is not allowed, off-scale number, out-of-range evidence.
            out = []
            for c in request.criteria:
                if c.code == "c1":
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
                    out.append(MLCriterionResult(code=c.code, answer="no"))
            return MLEvaluateResponse(results=out)
        raise AssertionError(self.mode)

    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


async def _run(client: AsyncClient, mode: str) -> dict:
    client.app.state.ml = BrokenML(mode)  # type: ignore[attr-defined]
    client.app.state.queue._ml = client.app.state.ml  # type: ignore[attr-defined]
    r = await client.post(f"{API}/evaluations", json={"dialog_id": "p1-ru-001"})
    assert r.status_code == 202
    await asyncio.wait_for(client.app.state.queue.join(), 10)  # type: ignore[attr-defined]
    return (await client.get(f"{API}/evaluations/{r.json()['id']}")).json()


async def test_model_exception_marks_failed_and_worker_survives(seeded: AsyncClient):
    ev = await _run(seeded, "raise")
    assert ev["status"] == "failed"
    assert "model exploded" in ev["error"]
    stats = (await seeded.get(f"{API}/queue")).json()
    assert stats["workers"] == 2 and stats["running"] == 0

    # Retry works once the model is healthy again.
    from app.ml.mock import MockMLClient

    seeded.app.state.ml = MockMLClient()  # type: ignore[attr-defined]
    seeded.app.state.queue._ml = seeded.app.state.ml  # type: ignore[attr-defined]
    r = await seeded.post(f"{API}/evaluations/{ev['id']}/retry")
    assert r.status_code == 202
    await asyncio.wait_for(seeded.app.state.queue.join(), 10)  # type: ignore[attr-defined]
    assert (await seeded.get(f"{API}/evaluations/{ev['id']}")).json()["status"] == "completed"


async def test_missing_criteria_fails(seeded: AsyncClient):
    ev = await _run(seeded, "missing")
    assert ev["status"] == "failed"
    assert "missing criteria" in ev["error"]


async def test_garbage_answers_fail(seeded: AsyncClient):
    ev = await _run(seeded, "garbage")
    assert ev["status"] == "failed"
    assert "ValidationError" in ev["error"]


async def test_sloppy_answers_are_normalised(seeded: AsyncClient):
    ev = await _run(seeded, "sloppy")
    assert ev["status"] == "completed", ev["error"]
    by = {r["criterion_code"]: r for r in ev["results"]}
    assert by["c1"]["answer"] == "no"
    assert "N/A is not allowed" in by["c1"]["normalization_note"]
    assert by["c1"]["evidence"] == []  # out-of-range index dropped
    assert by["c4"]["answer"] == 15  # 17 snapped to the nearest step
    assert by["c4"]["checked_range"]["to_index"] < 999
    assert by["c6"]["answer"] == 10  # 17 clamped to scale_max 10 (steps 10/7/4/0)


async def test_retry_only_for_failed(seeded: AsyncClient):
    r = await seeded.post(f"{API}/evaluations/sync", json={"dialog_id": "p1-ru-003"})
    assert (await seeded.post(f"{API}/evaluations/{r.json()['id']}/retry")).status_code == 409
