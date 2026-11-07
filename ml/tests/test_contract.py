import json
from pathlib import Path

from fastapi.testclient import TestClient

from fakes import FakeLLM
from maestro.contract import Criterion, EvaluateRequest, evaluate
from maestro.presets import match_standard
from maestro.service import create_app
from test_pipeline import GOOD

CHECKLIST = json.loads((Path(__file__).resolve().parents[1] / "data" / "default_checklist.json").read_text(encoding="utf-8"))

# Same shape as the organizers' data: a bot answers before the operator joins, MM:SS times.
TRANSCRIPT = [
    {"index": 0, "timestamp": "00:00", "speaker": "client", "text": "Где посмотреть мой тариф? В приложении не нахожу."},
    {"index": 1, "timestamp": "00:02", "speaker": "bot", "text": "Здравствуйте! Я AIM, AI-ассистент Freedom Broker."},
    {"index": 2, "timestamp": "00:38", "speaker": "system", "text": "Эскалация на оператора."},
    {"index": 3, "timestamp": "01:15", "speaker": "operator", "text": "Здравствуйте! Меня зовут Алина. Откройте вкладку «Кабинет»."},
    {"index": 4, "timestamp": "01:28", "speaker": "client", "text": "Нашла, спасибо."},
    {"index": 5, "timestamp": "02:04", "speaker": "operator", "text": "Пожалуйста, обращайтесь. Хорошего вечера!"},
]

ANSWERS = {
    **GOOD,
    "introduced": ("M3", True),
    "enough_info_from_start": ("M0", True),
    "request_formulated": ("M0", True),
    "consultation_level": ("M3", 20),
    "offered_help": ("M5", True),
}


def request(criteria=None, language="RU"):
    return EvaluateRequest(
        conversation_id="p1-ru-001", language=language, transcript=TRANSCRIPT, criteria=criteria or CHECKLIST
    )


def test_every_standard_criterion_is_recognised():
    for item in CHECKLIST:
        c = Criterion(**item)
        values = [s["value"] for s in c.scale_steps or []]
        assert match_standard(c.rule, c.answer_type, c.is_flag, values) == f"0{c.code[1]}"


def test_reworded_criterion_is_not_treated_as_standard():
    rule = "Да — оператор назвал клиента по имени хотя бы один раз."
    assert match_standard(rule, "yes_no", False, []) is None


def test_response_follows_the_contract():
    response = evaluate(request(), FakeLLM(ANSWERS))
    by_code = {r.code: r for r in response.results}
    assert list(by_code) == ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"]
    assert all(r.method == "standard" for r in response.results)
    assert by_code["c1"].answer == "yes" and by_code["c1"].evidence == [3]
    assert by_code["c2"].answer == "na" and by_code["c2"].na_reason
    assert by_code["c4"].answer == 20 and 3 in by_code["c4"].evidence
    assert by_code["c8"].answer == "no" and by_code["c8"].checked_range.from_index == 3
    assert response.usage.calls > 0 and response.model.name == "fake"


def test_explanations_follow_the_dialog_language():
    response = evaluate(request(language="KZ"), FakeLLM(ANSWERS))
    assert response.results[1].explanation == "Жауап беру үшін деректер басынан-ақ жеткілікті болды."
    response = evaluate(request(language="EN"), FakeLLM(ANSWERS))
    assert response.results[1].explanation.startswith("The information")


def test_missed_first_reply_points_at_the_operator_message():
    transcript = [dict(m) for m in TRANSCRIPT]
    transcript[3]["text"] = "Откройте вкладку «Кабинет»."  # no greeting, no name
    answers = {**ANSWERS, "introduced": ("M3", False), "greeted": ("M3", False)}
    req = EvaluateRequest(conversation_id="x", transcript=transcript, criteria=CHECKLIST)
    c1 = evaluate(req, FakeLLM(answers)).results[0]
    assert c1.answer == "no"
    assert (c1.checked_range.from_index, c1.checked_range.to_index) == (3, 3)


def test_new_criterion_uses_the_generic_evaluator():
    new = {
        "code": "c9", "title": "Обращение по имени", "answer_type": "yes_no", "weight": 5, "allow_na": False,
        "rule": "Да — оператор хотя бы раз обратился к клиенту по имени.",
    }
    llm = FakeLLM({**ANSWERS, "generic": {"answer": "no", "evidence": [], "explanation": "Оператор не обращался по имени."}})
    response = evaluate(request(CHECKLIST + [new]), llm)
    c9 = response.results[-1]
    assert c9.method == "generic" and c9.answer == "no"
    assert c9.explanation == "Оператор не обращался по имени."
    assert c9.checked_range is not None


def test_generic_flag_needs_an_operator_message():
    flag = {
        "code": "x", "title": "Обещание доходности", "answer_type": "yes_no", "allow_na": False, "is_flag": True,
        "rule": "Да — оператор гарантировал клиенту доходность.",
    }
    llm = FakeLLM({**ANSWERS, "generic": {"answer": "yes", "evidence": ["M0"], "explanation": "..."}})
    assert evaluate(request([flag]), llm).results[0].answer == "no"
    llm = FakeLLM({**ANSWERS, "generic": {"answer": "yes", "evidence": ["M3"], "explanation": "..."}})
    assert evaluate(request([flag]), llm).results[0].answer == "yes"


def test_hidden_name_in_a_call_counts_as_introduction():
    transcript = [
        {"index": 0, "timestamp": "2026-01-01T10:00:00+05:00", "speaker": "client", "text": "Алло."},
        {"index": 1, "timestamp": "2026-01-01T10:00:05+05:00", "speaker": "operator",
         "text": "Фридом брокер, меня зовут [Имя скрыто], здравствуйте, чем могу помочь?"},
    ]
    llm = FakeLLM(ANSWERS)
    req = EvaluateRequest(conversation_id="call", channel="voice call", transcript=transcript, criteria=[CHECKLIST[0]])
    result = evaluate(req, llm).results[0]
    assert "introduced" not in llm.calls and "greeted" not in llm.calls
    assert result.answer == "yes"


def _closing(transcript_tail):
    transcript = TRANSCRIPT[:4] + transcript_tail
    llm = FakeLLM({**ANSWERS, "chat_cut_off": ("M5", True)})
    req = EvaluateRequest(conversation_id="x", transcript=transcript, criteria=[CHECKLIST[6]])
    return evaluate(req, llm).results[0], llm


def test_operator_closing_the_chat_is_not_a_cut_off():
    result, llm = _closing([
        {"index": 4, "timestamp": "01:28", "speaker": "client", "text": "Нет, спасибо."},
        {"index": 5, "timestamp": "02:00", "speaker": "system", "text": "Оператор закрыл чат."},
    ])
    assert "chat_cut_off" not in llm.calls
    assert result.answer == "no"  # no goodbye, no summary


def test_client_leaving_before_a_goodbye_is_a_cut_off():
    result, llm = _closing([
        {"index": 4, "timestamp": "01:28", "speaker": "client", "text": "Жақсы."},
        {"index": 5, "timestamp": "02:00", "speaker": "system", "text": "Клиентпен байланыс үзілді."},
    ])
    assert "chat_cut_off" not in llm.calls
    assert result.answer == "na"


def test_reported_verification_means_identification_was_required():
    transcript = TRANSCRIPT[:4] + [
        {"index": 4, "timestamp": "01:20", "speaker": "system", "text": "Customer identity verified."},
        {"index": 5, "timestamp": "01:30", "speaker": "operator", "text": "Your deposit is being processed."},
    ]
    llm = FakeLLM({**ANSWERS, "identity_confirmed_first": ("M4", True)})
    req = EvaluateRequest(conversation_id="x", transcript=transcript, criteria=[CHECKLIST[2]])
    result = evaluate(req, llm).results[0]
    assert "identification_required" not in llm.calls
    assert result.answer == "yes"


class Recording(FakeLLM):
    def __init__(self, answers):
        super().__init__(answers)
        self.prompts: list[str] = []

    def complete(self, system, user, schema):
        self.prompts.append(user)
        return super().complete(system, user, schema)


def test_user_added_guideline_reaches_every_prompt():
    rule = "Обращение на «ты» считается невежливым."
    llm = Recording(ANSWERS)
    evaluate(request().model_copy(update={"guidelines": [rule]}), llm)
    assert llm.prompts and all(rule in p for p in llm.prompts)


def test_backend_first_response_threshold_counts_as_a_standard_rule():
    from maestro.presets import extra_guidelines

    # As backend/app/services/evaluations.py builds it from first_response_threshold_sec.
    line = "Порог первой реакции — 240 с: если клиент ждал ответа оператора дольше, это явное ожидание."
    assert extra_guidelines([line]) == []


def test_only_user_added_guidelines_reach_the_model():
    standard = "Теги и вложения в оценку не входят."
    added = "Обращение на «ты» считается невежливым."
    new = {
        "code": "c9", "title": "Обращение по имени", "answer_type": "yes_no", "allow_na": False,
        "rule": "Да — оператор хотя бы раз обратился к клиенту по имени.",
    }
    llm = Recording({**ANSWERS, "generic": {"answer": "no", "evidence": [], "explanation": "..."}})
    evaluate(request(CHECKLIST + [new]).model_copy(update={"guidelines": [standard, added]}), llm)
    generic = [p for p in llm.prompts if "\nRule: " in p]
    assert len(generic) == 1 and added in generic[0]
    # The PDF's standard notes lowered agreement on both paths, so no prompt gets them.
    assert all(standard not in p for p in llm.prompts)


def test_edited_settings_constrain_the_answer():
    # N/A switched off for c2 in the editor: the standard logic's N/A becomes "no".
    edited = [dict(CHECKLIST[1], allow_na=False)]
    assert evaluate(request(edited), FakeLLM(ANSWERS)).results[0].answer == "no"


def test_service_endpoints():
    with TestClient(create_app(lambda: FakeLLM(ANSWERS))) as client:
        assert client.get("/health").status_code == 200
        response = client.post("/evaluate", json=request().model_dump(mode="json"))
        assert response.status_code == 200
        body = response.json()
        assert len(body["results"]) == 8 and body["conversation_id"] == "p1-ru-001"
        assert client.post("/evaluate", json={**request().model_dump(mode="json"), "criteria": []}).status_code == 422



def test_small_edits_that_change_the_meaning_go_to_the_generic_evaluator():
    edits = [
        ("Да — проверка личности не подтверждена до раскрытия данных или защищённого действия.", "yes_no", False),
        ("Да — оператор подвёл итог и предложил дальнейшую помощь и попрощался.", "yes_no", False),
        ("Да — оператор вежлив, извинился и, если клиент выразил недовольство или описал неудобство, "
         "отреагировал на конкретную проблему.", "yes_no", False),
    ]
    for rule, answer_type, is_flag in edits:
        assert match_standard(rule, answer_type, is_flag, []) is None, rule


def test_harmless_variants_keep_the_built_in_logic():
    # As the frontend sends them: no "по шкале", an extra sentence about the negative answer.
    assert match_standard("Оцените ясность, порядок ответов и предупреждение об ожидании.", "scale", False, [0, 4, 7, 10]) == "06"
    assert match_standard(
        "Да — выявлено оскорбление клиента, предложение платной услуги в обход компании или раскрытие "
        "конфиденциальной информации. Нет — ни одно из трёх не выявлено.", "yes_no", True, []) == "08"
    assert match_standard("да - оператор учел известные детали и уточнил недостающее до ответа", "yes_no", False, []) == "02"


def test_generic_criterion_is_told_what_not_to_judge():
    seen = []

    class Recording(FakeLLM):
        def complete(self, system, user, schema, think=None):
            if "\nRule: " in user:
                seen.append((system, user))
            return super().complete(system, user, schema, think)

    checklist = [dict(c) for c in CHECKLIST]
    checklist[4] = {**checklist[4], "title": "Извинение", "rule": "Да — оператор извинился за неудобство."}
    llm = Recording({**ANSWERS, "generic": {"answer": "yes", "evidence": [], "explanation": "ok"}})
    evaluate(request([Criterion(**c) for c in checklist]), llm)
    system, user = seen[0]
    assert "Judge ONLY what this criterion's rule asks" in system
    assert "Эмпатия" not in user  # the replaced criterion is gone
    assert "Корректная и полная консультация" in user and "Грубые ошибки" in user


def test_generic_answers_given_as_strings_are_understood():
    from maestro.generic import _normalize_answer

    assert _normalize_answer("10") == 10 and _normalize_answer(10.0) == 10
    assert _normalize_answer("N/A") == "na" and _normalize_answer("Yes") == "yes"
    checklist = [dict(c) for c in CHECKLIST]
    checklist[5] = {**checklist[5], "title": "Понятность инструкций", "rule": "Оцените конкретность инструкций.",
                    "scale_steps": [{"value": 10, "label": "конкретно"}, {"value": 5, "label": "частично"}, {"value": 0, "label": "нет"}],
                    "scale_max": 10}
    llm = FakeLLM({**ANSWERS, "generic": {"answer": "10", "evidence": [], "explanation": "ok"}})
    response = evaluate(request([Criterion(**c) for c in checklist]), llm)
    assert next(r for r in response.results if r.code == "c6").answer == 10


def test_generic_na_condition_takes_priority():
    checklist = [dict(c) for c in CHECKLIST]
    checklist[4] = {**checklist[4], "title": "Извинение", "allow_na": True, "na_rule": "клиент не выражал недовольства",
                    "rule": "Да — если клиент выразил недовольство, оператор извинился."}
    llm = FakeLLM({**ANSWERS, "generic": {"na_condition_holds": True, "answer": "no", "evidence": [], "explanation": "ok"}})
    response = evaluate(request([Criterion(**c) for c in checklist]), llm)
    assert next(r for r in response.results if r.code == "c5").answer == "na"
    assert llm.calls.count("generic") == 1  # N/A settled in the first step, the rule is not asked


def test_generic_answer_step_cannot_pick_na():
    checklist = [dict(c) for c in CHECKLIST]
    checklist[4] = {**checklist[4], "title": "Извинение", "allow_na": True, "na_rule": "клиент не выражал недовольства",
                    "rule": "Да — если клиент выразил недовольство, оператор извинился."}
    seen = []

    class Recording(FakeLLM):
        def complete(self, system, user, schema, think=None):
            if "\nRule: " in user:
                seen.append(schema)
            return super().complete(system, user, schema, think)

    llm = Recording({**ANSWERS, "generic": {"answer": "yes", "evidence": [], "explanation": "ok"}})
    response = evaluate(request([Criterion(**c) for c in checklist]), llm)
    assert next(r for r in response.results if r.code == "c5").answer == "yes"
    assert [list(s["properties"])[1] for s in seen] == ["na_condition_holds", "answer"]
    assert "na" not in seen[1]["properties"]["answer"]["enum"]


def test_generic_criteria_can_use_a_separate_model():
    checklist = [dict(c) for c in CHECKLIST]
    checklist[4] = {**checklist[4], "title": "Извинение", "rule": "Да — оператор извинился за неудобство."}
    main = FakeLLM(ANSWERS)
    strong = FakeLLM({"generic": {"answer": "yes", "evidence": [], "explanation": "ok"}})
    strong.model = "strong"
    response = evaluate(request([Criterion(**c) for c in checklist]), main, strong)
    assert strong.calls == ["generic"]
    assert "generic" not in main.calls and main.calls
    assert response.model.generic_name == "strong"
    assert response.usage.calls == len(main.calls) + len(strong.calls)
