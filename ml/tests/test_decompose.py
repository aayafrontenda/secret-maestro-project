import pytest

from fakes import FakeLLM
from maestro import decompose
from maestro.contract import Criterion, evaluate
from test_contract import ANSWERS, CHECKLIST, request

APOLOGY = {
    **CHECKLIST[4], "title": "Извинение", "allow_na": True, "na_rule": "Клиент не выражал недовольства.",
    "rule": "Да — оператор извинился или признал проблему и предложил конкретный следующий шаг.",
}
PLAN = {"conditions": [
    {"question": "Did the operator apologise or acknowledge the problem?", "label": "извинился"},
    {"question": "Did the operator propose a concrete next step?", "label": "следующий шаг"},
]}


@pytest.fixture(autouse=True)
def decomposed_mode(monkeypatch):
    monkeypatch.setenv("MAESTRO_GENERIC_MODE", "decompose")
    decompose._plans.clear()


def _run(criterion, check, generic=None):
    llm = FakeLLM({**ANSWERS, "generic": generic or {"na_condition_holds": False, "evidence": [], "explanation": ""},
                   "generic_plan": PLAN, "generic_check": check})
    result = evaluate(request([Criterion(**criterion)]), llm).results[0]
    return result, llm


def test_yes_needs_every_condition():
    result, llm = _run(APOLOGY, {"answer": True, "evidence": ["M3"]})
    assert result.answer == "yes" and result.method == "generic"
    assert result.explanation == "извинился: да; следующий шаг: да"
    assert llm.calls.count("generic") == 4  # N/A, plan, two conditions

    def only_apology(user):
        return {"answer": "apologise" in user, "evidence": ["M3"] if "apologise" in user else []}

    result, _ = _run(APOLOGY, only_apology)
    assert result.answer == "no" and result.explanation == "извинился: да; следующий шаг: нет"


def test_the_plan_is_made_once_per_checklist():
    _run(APOLOGY, {"answer": True, "evidence": []})
    _, llm = _run(APOLOGY, {"answer": True, "evidence": []})
    assert llm.calls.count("generic") == 3  # N/A and two conditions, the plan is cached


def test_scale_levels_are_checked_from_the_top():
    scale = {
        **CHECKLIST[5], "title": "Понятность инструкций", "rule": "Оцените конкретность инструкций.",
        "scale_steps": [{"value": 10, "label": "по шагам"}, {"value": 5, "label": "без шагов"}, {"value": 0, "label": "нет"}],
        "scale_max": 10,
    }
    result, llm = _run(scale, lambda user: {"answer": "без шагов" in user, "evidence": ["M3"]})
    assert result.answer == 5 and result.explanation == "Ступень 5: без шагов"
    result, _ = _run(scale, {"answer": False, "evidence": []})
    assert result.answer == 0


def test_a_flag_needs_an_operator_message():
    flag = {"code": "x", "title": "Обещание доходности", "answer_type": "yes_no", "allow_na": False, "is_flag": True,
            "rule": "Да — оператор гарантировал клиенту доходность."}
    result, _ = _run(flag, {"answer": True, "evidence": ["M0"]})  # a client message
    assert result.answer == "no"
    result, _ = _run(flag, {"answer": True, "evidence": ["M3"]})
    assert result.answer == "yes"


def test_single_mode_is_the_default(monkeypatch):
    monkeypatch.delenv("MAESTRO_GENERIC_MODE")
    _, llm = _run(APOLOGY, {"answer": True, "evidence": []},
                  generic={"answer": "yes", "evidence": [], "explanation": "ok"})
    assert llm.calls.count("generic") == 2  # N/A and one answer
