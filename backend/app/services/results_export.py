"""results.json in the organizers' format 1.0 (CQA_Student_Guide_Appendix_Results.pdf).

One entry per dialog of the set, from its latest evaluation on a checklist that has the eight
standard criteria (codes 01-08). Final answers are used, i.e. after reviewers' appeal decisions.
Dialogs that were not evaluated or whose evaluation failed are reported with status "error".
"""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Dialog, Evaluation
from app.models.evaluation import CriterionResult, EvaluationStatus

SCHEMA_VERSION = "1.0"

# code -> (criterion_id, allowed values; None = N/A). bool and int are told apart in _allowed.
STANDARD: dict[str, tuple[str, set[Any]]] = {
    "01": ("contact", {True, False}),
    "02": ("discovery", {True, False, None}),
    "03": ("identification", {True, False, None}),
    "04": ("consultation", {0, 5, 10, 15, 20, None}),
    "05": ("empathy", {True, False}),
    "06": ("dialogue", {0, 4, 7, 10}),
    "07": ("closure", {True, False, None}),
    "08": ("critical", {True, False}),
}
ORDER = [cid for cid, _ in STANDARD.values()]

CLOUD = re.compile(r"^(gpt|o\d|chatgpt|gemini|claude|glm|deepseek|kimi|grok|mistral-large)", re.I)


def _allowed(value: Any, allowed: set[Any]) -> bool:
    if value is None:
        return None in allowed
    boolean = any(isinstance(a, bool) for a in allowed)
    if boolean:
        return isinstance(value, bool)
    return isinstance(value, int) and not isinstance(value, bool) and value in allowed


def _code(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    return digits.zfill(2) if digits else raw


def _value(answer: Any) -> Any:
    if answer == "yes":
        return True
    if answer == "no":
        return False
    if answer in ("na", None):
        return None
    v = float(answer)
    return int(v) if v.is_integer() else v


def _turns(r) -> list[int]:
    turns = [int(e["message_index"]) + 1 for e in r.evidence or [] if "message_index" in e]
    if not turns and r.checked_range:
        lo = int(r.checked_range["from_index"])
        hi = int(r.checked_range["to_index"])
        turns = list(range(lo + 1, hi + 2)) if hi - lo < 6 else [lo + 1, hi + 1]
    return sorted(set(turns))


def _rationale(r) -> str:
    decided = [a for a in r.appeals if a.status.value == "changed" and a.decision_reason]
    if decided:
        return f"{r.explanation} Решение по апелляции: {decided[-1].decision_reason}".strip()
    if r.final_answer == "na" and r.na_reason and r.na_reason not in (r.explanation or ""):
        return f"{r.explanation} {r.na_reason}".strip()
    return r.explanation or ""


def _usable(ev: Evaluation) -> bool:
    codes = {_code(r.criterion_code) for r in ev.results}
    return set(STANDARD) <= codes


def _entry(d: Dialog, ev: Evaluation | None) -> dict[str, Any]:
    if ev is None or ev.status != EvaluationStatus.completed:
        reason = (ev.error if ev is not None else None) or "Диалог не оценён"
        return {
            "conversation_id": d.id,
            "status": "error",
            "criteria": [],
            "score": None,
            "error": reason,
        }
    by_code = {_code(r.criterion_code): r for r in ev.results}
    criteria = []
    for code, (cid, _) in STANDARD.items():
        r = by_code[code]
        value = _value(r.final_answer)
        criteria.append(
            {
                "criterion_id": cid,
                "value": value,
                "rationale": _rationale(r),
                "evidence_turns": _turns(r),
            }
        )
    critical = by_code["08"].final_answer == "yes"
    return {
        "conversation_id": d.id,
        "status": "ok",
        "criteria": criteria,
        "score": {
            "final_score": round(float(ev.final_total), 2) if ev.final_total is not None else None,
            "critical_flag": critical,
        },
    }


def model_info(evaluations: list[Evaluation]) -> dict[str, str]:
    names = sorted(
        {
            f"mock ({ev.model_name})" if ev.provider == "mock" else ev.model_name
            for ev in evaluations
            if ev.model_name
        }
    )
    kinds = set()
    for ev in evaluations:
        for part in (ev.model_name or "").split(" + "):
            if not part:
                continue
            local = ev.provider in ("ollama", "local") and not CLOUD.match(part)
            kinds.add("local" if local else "external_api")
    mode = "hybrid" if len(kinds) > 1 else (kinds.pop() if kinds else "local")
    return {"mode": mode, "name": ", ".join(names) or "unknown"}


async def build_results(
    session: AsyncSession,
    *,
    group_id: str | None,
    team_name: str,
    mode: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    stmt = select(Dialog).order_by(Dialog.id)
    if group_id:
        stmt = stmt.where(Dialog.dataset_group_id == group_id)
    dialogs = list((await session.scalars(stmt)).all())
    evs = (
        await session.scalars(
            select(Evaluation)
            .where(Evaluation.dialog_id.in_([d.id for d in dialogs]))
            .where(Evaluation.status.in_([EvaluationStatus.completed, EvaluationStatus.failed]))
            .options(selectinload(Evaluation.results).selectinload(CriterionResult.appeals))
            .order_by(Evaluation.id)
        )
    ).all()

    latest_ok: dict[str, Evaluation] = {}
    latest_any: dict[str, Evaluation] = {}
    for ev in evs:  # ordered by id: later ones win
        latest_any[ev.dialog_id] = ev
        if ev.status == EvaluationStatus.completed and _usable(ev):
            latest_ok[ev.dialog_id] = ev

    used: list[Evaluation] = []
    results = []
    for d in dialogs:
        ev = latest_ok.get(d.id) or latest_any.get(d.id)
        if ev is not None and ev.status == EvaluationStatus.completed and not _usable(ev):
            ev = None  # only evaluated on a checklist without the eight standard criteria
        if ev is not None and ev.status == EvaluationStatus.completed:
            used.append(ev)
        results.append(_entry(d, ev))

    info = model_info(used)
    return {
        "schema_version": SCHEMA_VERSION,
        "team_name": team_name,
        "model": {"mode": mode or info["mode"], "name": model_name or info["name"]},
        "results": results,
    }


def validate(doc: dict[str, Any], expected: int | None = None) -> list[str]:
    """Checks from the appendix: one entry per dialog, eight criteria, allowed values."""
    errors: list[str] = []
    results = doc.get("results") or []
    ids = [r.get("conversation_id") for r in results]
    if expected is not None and len(results) != expected:
        errors.append(f"{len(results)} records, expected {expected}")
    if len(ids) != len(set(ids)):
        errors.append("duplicate conversation_id")
    if doc.get("model", {}).get("mode") not in ("local", "external_api", "hybrid"):
        errors.append("model.mode must be local, external_api or hybrid")
    if "mock (" in str(doc.get("model", {}).get("name", "")):
        errors.append("some dialogs were graded by the demo mock: re-evaluate them with a model")
    for r in results:
        cid = r.get("conversation_id")
        if r.get("status") == "error":
            if r.get("criteria") != [] or r.get("score") is not None or not r.get("error"):
                errors.append(f"{cid}: error entries need empty criteria, score null and error")
            continue
        got = [c.get("criterion_id") for c in r.get("criteria", [])]
        if got != ORDER:
            errors.append(f"{cid}: criteria {got}")
            continue
        for c, (_, allowed) in zip(r["criteria"], STANDARD.values(), strict=True):
            if not _allowed(c["value"], allowed):
                errors.append(f"{cid}: {c['criterion_id']}={c['value']!r} not allowed")
        s = r.get("score") or {}
        fs = s.get("final_score")
        if not isinstance(fs, (int, float)) or not 0 <= fs <= 100:
            errors.append(f"{cid}: final_score {fs!r}")
        if s.get("critical_flag") is not r["criteria"][7]["value"]:  # critical is last
            errors.append(f"{cid}: critical_flag differs from critical")
    return errors
