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
    assert "used_known_details" not in llm.calls  # 02 is N/A


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
