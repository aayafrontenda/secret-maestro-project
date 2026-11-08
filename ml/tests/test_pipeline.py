import json

from fakes import FakeLLM
from maestro.ingest import parse_json_object
from maestro.llm import LLMResponse
from maestro.pipeline import score_transcript

CHAT = {
    "chat_id": "t1",
    "messages": [
        {"role": "client", "text": "Добрый день, какая комиссия за сделку?"},
        {"role": "operator", "text": "Здравствуйте! Меня зовут Алина. Комиссия 0,2%."},
        {"role": "client", "text": "Спасибо"},
        {"role": "operator", "text": "Пожалуйста, обращайтесь. Всего доброго!"},
    ],
}

GOOD = {
    "introduced": ("M2", True),
    "used_known_details": ("M2", True),
    "enough_info_from_start": ("M1", True),
    "identification_required": False,
    "request_formulated": ("M1", True),
    "consultation_level": ("M2", 20),
    "impolite": False,
    "client_complained": False,
    "chat_cut_off": False,
    "summarized": False,
    "offered_help": ("M4", True),
}


def transcript():
    return parse_json_object(CHAT)[0]


def test_good_chat_scores_100_with_na_redistribution():
    llm = FakeLLM(GOOD)
    result = score_transcript(transcript(), llm)
    answers = {c.criterion_id: c.answer for c in result.criteria}
    assert answers == {"01": "yes", "02": "na", "03": "na", "04": 20, "05": "yes", "06": 10, "07": "yes", "08": "no"}
    assert result.final_score == 100.0
    assert result.status == "scored"
    assert result.gross_violation.flag is False


def test_fixed_phrases_skip_the_model():
    llm = FakeLLM(GOOD)
    score_transcript(transcript(), llm)
    assert "greeted" not in llm.calls  # "Здравствуйте"
    assert "said_goodbye" not in llm.calls  # "Всего доброго"
    assert "client_language_used" not in llm.calls  # both detected as Russian
    assert "reacted_to_problem" not in llm.calls  # no complaint


def test_evidence_is_taken_from_the_transcript():
    result = score_transcript(transcript(), FakeLLM(GOOD))
    c04 = next(c for c in result.criteria if c.criterion_id == "04")
    assert c04.evidence[0].message_id == "M2"
    assert c04.evidence[0].quote == "Здравствуйте! Меня зовут Алина. Комиссия 0,2%."


def test_rationale_language():
    result = score_transcript(transcript(), FakeLLM(GOOD), output_language="kk")
    c02 = next(c for c in result.criteria if c.criterion_id == "02")
    assert c02.rationale == "Жауап беру үшін деректер басынан-ақ жеткілікті болды."
    result = score_transcript(transcript(), FakeLLM(GOOD), output_language="en")
    assert result.criteria[0].rationale.startswith("Greeted in the first reply: yes")


def test_gross_flag_requires_an_operator_message():
    answers = {**GOOD, "insult": True}  # the model says yes but cites nothing
    result = score_transcript(transcript(), FakeLLM(answers))
    assert result.gross_violation.insult is False
    answers = {**GOOD, "insult": ("M2", True)}
    result = score_transcript(transcript(), FakeLLM(answers))
    assert result.gross_violation.flag is True
    assert result.final_score == 100.0  # 08 never changes the score


class BrokenLLM(FakeLLM):
    def complete(self, system, user, schema):
        if "How correctly and completely" in user:
            self.calls.append("broken")
            return LLMResponse(content="not json at all", duration_ms=1)
        return super().complete(system, user, schema)


def test_unusable_answers_fail_the_criterion_without_inventing_a_score():
    llm = BrokenLLM(GOOD)
    result = score_transcript(transcript(), llm)
    c04 = next(c for c in result.criteria if c.criterion_id == "04")
    assert c04.status == "failed" and c04.answer is None
    assert len([a for a in c04.attempts if a.probe == "consultation_level"]) == 3
    assert result.status == "partial"
    assert result.final_score is None


def test_operator_language_mismatch_is_confirmed_by_the_model():
    chat = json.loads(json.dumps(CHAT))
    chat["messages"][0]["text"] = "Сәлеметсіз бе, комиссия қанша?"
    llm = FakeLLM({**GOOD, "client_language_used": ("M2", False)})
    result = score_transcript(parse_json_object(chat)[0], llm)
    assert "client_language_used" in llm.calls
    c01 = result.criteria[0]
    assert c01.answer == "no" and c01.expected_at == "M2"


def test_thinking_is_enabled_only_for_listed_criteria(monkeypatch):
    from maestro.probes import PROBE_CRITERION

    monkeypatch.setenv("MAESTRO_THINK_ON", "04, 7")
    llm = FakeLLM(GOOD)
    score_transcript(transcript(), llm)
    assert llm.calls, "the model was not asked anything"
    for key, think in zip(llm.calls, llm.thinks):
        assert think is (PROBE_CRITERION.get(key) in {"04", "07"}), key


def test_thinking_follows_the_client_setting_when_unset(monkeypatch):
    monkeypatch.delenv("MAESTRO_THINK_ON", raising=False)
    llm = FakeLLM(GOOD)
    score_transcript(transcript(), llm)
    assert set(llm.thinks) == {None}


def _chat(messages):
    return parse_json_object({"chat_id": "t2", "messages": messages})[0]


def test_asking_for_an_operator_is_not_a_request_on_substance():
    chat = _chat([
        {"role": "client", "text": "Здравствуйте, можно поговорить с человеком?"},
        {"role": "operator", "text": "Здравствуйте! Меня зовут Валерия. С чем помочь?"},
        {"role": "system", "text": "Клиент покинул чат."},
    ])
    llm = FakeLLM({**GOOD, "request_formulated": False})
    result = score_transcript(chat, llm)
    assert "request_formulated" in llm.calls  # the question mark did not settle it
    assert {c.criterion_id: c.answer for c in result.criteria}["04"] == "na"


def test_re_asking_known_details_fails_needs_discovery_even_when_data_was_enough():
    llm = FakeLLM({**GOOD, "used_known_details": ("M2", False), "known_detail_reasked": ("M2", True)})
    result = score_transcript(transcript(), llm)
    assert {c.criterion_id: c.answer for c in result.criteria}["02"] == "no"


def test_needs_discovery_follows_what_the_operator_did():
    chat = _chat([
        {"role": "client", "text": "Не приходят SMS для входа."},
        {"role": "operator", "text": "Здравствуйте, я Тимур. Подскажите, вы сменили номер телефона?"},
        {"role": "client", "text": "Да, сменил."},
        {"role": "operator", "text": "Тогда обновите номер в профиле. Всего доброго!"},
    ])

    def c02(answers):
        result = score_transcript(chat, FakeLLM({**GOOD, **answers}))
        return {c.criterion_id: c.answer for c in result.criteria}["02"]

    # A clarifying question asked for a NEW detail is not a known detail asked again.
    assert c02({"used_known_details": ("M2", False), "known_detail_reasked": False,
                "clarified_missing": ("M2", True), "enough_info_from_start": True}) == "yes"
    # The operator clarified before answering: "yes", even if the start looked complete.
    assert c02({"clarified_missing": ("M2", True), "enough_info_from_start": True}) == "yes"
    # No clarification: N/A when the start had everything, otherwise "no".
    assert c02({"clarified_missing": False, "enough_info_from_start": True}) == "na"
    assert c02({"clarified_missing": False, "enough_info_from_start": False}) == "no"


def test_summary_is_looked_for_only_after_the_clients_last_message():
    from maestro.facts import extract_facts
    from maestro.probes import Context

    chat = _chat([
        {"role": "client", "text": "I can't register, the login is taken."},
        {"role": "operator", "text": "Hi, I'm Maya. A login stays on record. Use a different one."},
        {"role": "client", "text": "Right, thanks."},
        {"role": "operator", "text": "You're welcome. Take care!"},
    ])
    ctx = Context(transcript=chat, facts=extract_facts(chat), llm=FakeLLM(GOOD))
    assert [m.text for m in ctx.shown("operator_closing")] == ["You're welcome. Take care!"]


def _c06(answers):
    result = score_transcript(transcript(), FakeLLM({**GOOD, **answers}))
    return {c.criterion_id: c.answer for c in result.criteria}["06"]


def test_dialogue_level_is_set_by_code_from_facts():
    lapse = {"noticeable_lapse": ("M2", True), "lapse_confirmed": ("M2", True)}
    assert _c06({}) == 10
    assert _c06(lapse) == 7
    # The broad question said "lapse" but the message alone shows none.
    assert _c06({"noticeable_lapse": ("M2", True), "lapse_confirmed": False}) == 10
    assert _c06({"client_asked_again": ("M3", True), "asked_again_confirmed": ("M3", True), **lapse}) == 4
    # Not confirmed on the message pair: a follow-up, not a re-ask; the lapse decides.
    assert _c06({"client_asked_again": ("M3", True), "asked_again_confirmed": False, **lapse}) == 7
    assert _c06({"incoherent": ("M2", True), "client_asked_again": ("M3", True)}) == 0


def test_a_rude_but_clear_reply_is_not_incoherence():
    # "Тогда не знаю." was flagged as incoherent; the narrow check finds its meaning clear.
    answers = {"incoherent": ("M2", True), "reply_understandable": ("M2", True)}
    assert _c06(answers) == 10
    assert _c06({**answers, "client_asked_again": ("M3", True), "asked_again_confirmed": ("M3", True)}) == 4


def test_incoherence_needs_an_operator_message_to_point_at():
    assert _c06({"incoherent": True}) == 10  # no message cited


def test_dialogue_probes_do_not_see_the_exchange_with_the_bot():
    from maestro.facts import extract_facts
    from maestro.probes import Context

    chat = _chat([
        {"role": "client", "text": "Где тариф?"},
        {"role": "bot", "text": "В отчёте брокера."},
        {"role": "client", "text": "Подключите оператора."},
        {"role": "operator", "text": "Здравствуйте, я Алина. Тариф в разделе «Кабинет»."},
        {"role": "client", "text": "Нашла, спасибо."},
    ])
    ctx = Context(transcript=chat, facts=extract_facts(chat), llm=FakeLLM(GOOD))
    assert [m.role.value for m in ctx.shown("since_operator")] == ["operator", "client"]


def test_a_clarification_must_be_an_operator_question():
    opening = [
        {"role": "client", "text": "Не могу войти."},
        {"role": "operator", "text": "Здравствуйте, я Антон. Переустановите приложение."},
        {"role": "client", "text": "Я на компьютере."},
    ]
    base = {**GOOD, "enough_info_from_start": False, "used_known_details": ("M2", True), "clarified_missing": ("M2", True)}
    reply = {"role": "client", "text": "Freedom Global."}
    guess = score_transcript(_chat([*opening, {"role": "operator", "text": "Ну, тогда сайт."}, reply]), FakeLLM(base))
    asked = score_transcript(_chat([*opening, {"role": "operator", "text": "Укажите, пожалуйста, адрес сайта."}, reply]), FakeLLM(base))
    offer = score_transcript(_chat([*opening, {"role": "operator", "text": "Ну, тогда сайт. Чем ещё могу помочь?"}, reply]), FakeLLM(base))
    assert {c.criterion_id: c.answer for c in offer.criteria}["02"] == "no"  # a help offer is not a clarification
    assert {c.criterion_id: c.answer for c in guess.criteria}["02"] == "no"
    assert {c.criterion_id: c.answer for c in asked.criteria}["02"] == "yes"



def test_declined_verification_is_not_the_operators_fault():
    chat = _chat([
        {"role": "client", "text": "Почему у меня поменялся тариф?"},
        {"role": "operator", "text": "Здравствуйте, я Тимур. Чтобы проверить ваш счёт, нужно подтвердить личность."},
        {"role": "client", "text": "Давайте пока без этого."},
        {"role": "operator", "text": "Хорошо. Если решите, напишите нам. До свидания!"},
    ])
    answers = {**GOOD, "identification_required": ("M1", True), "identity_confirmed_first": False}
    clean = score_transcript(chat, FakeLLM({**answers, "account_info_disclosed": False}))
    leaked = score_transcript(chat, FakeLLM({**answers, "account_info_disclosed": ("M2", True)}))
    assert {c.criterion_id: c.answer for c in clean.criteria}["03"] == "yes"
    assert {c.criterion_id: c.answer for c in leaked.criteria}["03"] == "no"


def test_skipped_verification_fails_identification():
    chat = _chat([
        {"role": "client", "text": "Почему отклоняются мои приказы?"},
        {"role": "operator", "text": "Здравствуйте, я Саша. Биржа отменяет ваш приказ."},
    ])
    result = score_transcript(chat, FakeLLM({**GOOD, "identification_required": ("M1", True), "identity_confirmed_first": False}))
    assert {c.criterion_id: c.answer for c in result.criteria}["03"] == "no"


def test_dialog_marked_kazakh_is_not_settled_as_same_language_by_code():
    from maestro.facts import extract_facts
    from maestro.probes import Context
    from maestro.rules import c01

    chat = _chat([
        {"role": "client", "text": "Салем, шотка акша тускен жок"},
        {"role": "operator", "text": "Здравствуйте, меня зовут Алина. Проверю."},
    ])
    llm = FakeLLM({**GOOD, "client_language_used": ("M2", False)})
    decision = c01(Context(transcript=chat, facts=extract_facts(chat, "kk"), llm=llm))
    assert "client_language_used" in llm.calls and decision.answer == "no"



def test_an_opening_question_counts_as_clarification_even_if_the_client_leaves():
    chat = _chat([
        {"role": "client", "text": "Подключите оператора."},
        {"role": "operator", "text": "Здравствуйте! Меня зовут Валерия. С чем помочь?"},
        {"role": "system", "text": "Клиент покинул чат."},
    ])
    answers = {**GOOD, "enough_info_from_start": False, "used_known_details": ("M2", True), "clarified_missing": ("M2", True)}
    result = score_transcript(chat, FakeLLM(answers))
    assert {c.criterion_id: c.answer for c in result.criteria}["02"] == "yes"


def test_phrases_in_latin_kazakh_and_questions_without_marks():
    from maestro.rules import CLARIFYING, GOODBYE, GREETING, INTRODUCTION

    assert GREETING.search("Salemetsiz be, menin atym Dana") and INTRODUCTION.search("Salemetsiz be, menin atym Dana")
    assert GOODBYE.search("Sau boliniz!")
    for question in ["Какой у вас логин", "Қай сайттан кірдіңіз", "Сізге нұсқаулық керек пе", "Which app are you using"]:
        assert CLARIFYING.search(question), question
    for guess in ["Переустановите приложение.", "Ну, тогда сайт.", "Мен Айгерім. Котировки бөлімін ашыңыз."]:
        assert not CLARIFYING.search(guess), guess


def test_clarification_without_a_question_mark_counts():
    chat = _chat([
        {"role": "client", "text": "Не могу войти."},
        {"role": "operator", "text": "Здравствуйте, я Антон. Какой у вас логин"},
        {"role": "client", "text": "anton77"},
        {"role": "operator", "text": "Сбросьте пароль по ссылке на экране входа."},
    ])
    answers = {**GOOD, "enough_info_from_start": False, "used_known_details": ("M2", True), "clarified_missing": ("M2", True)}
    assert {c.criterion_id: c.answer for c in score_transcript(chat, FakeLLM(answers)).criteria}["02"] == "yes"


def test_latin_kazakh_client_is_checked_by_the_model():
    from maestro.facts import extract_facts
    from maestro.probes import Context
    from maestro.rules import c01

    chat = _chat([
        {"role": "client", "text": "salem, shotqa aqsha tuspedi"},
        {"role": "operator", "text": "Здравствуйте, меня зовут Алина. Проверю."},
    ])
    llm = FakeLLM({**GOOD, "client_language_used": ("M2", False)})
    decision = c01(Context(transcript=chat, facts=extract_facts(chat, "kk"), llm=llm))
    assert "client_language_used" in llm.calls and decision.answer == "no"



def test_verification_questions_are_not_asking_again_for_known_details():
    chat = _chat([
        {"role": "client", "text": "Почему отклоняется мой приказ?"},
        {"role": "operator", "text": "Здравствуйте, я Тимур. Какую бумагу вы покупали?"},
        {"role": "client", "text": "Облигацию МФО."},
        {"role": "operator", "text": "Продиктуйте, пожалуйста, ваши фамилию, имя, отчество."},
        {"role": "client", "text": "Иванов Иван Иванович."},
        {"role": "operator", "text": "Спасибо. Приказ отклонён биржей, можно купить только через трейдера."},
    ])
    answers = {**GOOD, "enough_info_from_start": False, "used_known_details": ("M4", False), "clarified_missing": ("M2", True)}
    result = score_transcript(chat, FakeLLM(answers))
    assert {c.criterion_id: c.answer for c in result.criteria}["02"] == "yes"


def test_a_verification_question_is_not_a_lapse():
    chat = _chat([
        {"role": "client", "text": "Не вижу облигацию."},
        {"role": "operator", "text": "Здравствуйте, я Тимур. Как я могу к вам обращаться?"},
        {"role": "client", "text": "Айдар."},
        {"role": "operator", "text": "Айдар, облигация в разделе «Котировки»."},
    ])
    result = score_transcript(chat, FakeLLM({**GOOD, "noticeable_lapse": ("M2", True)}))
    assert {c.criterion_id: c.answer for c in result.criteria}["06"] == 10
