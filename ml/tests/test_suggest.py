from fastapi.testclient import TestClient

from fakes import FakeLLM
from maestro.service import create_app
from test_contract import ANSWERS, CHECKLIST, TRANSCRIPT


class Recording(FakeLLM):
    def __init__(self, answers):
        super().__init__(answers)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system, user, schema, think=None):
        self.prompts.append((system, user))
        return super().complete(system, user, schema, think)


def _body(**over):
    return {
        "conversation_id": "p1-ru-001",
        "language": "KZ",
        "transcript": TRANSCRIPT,
        "criterion": CHECKLIST[6],  # closing
        "answer": "no",
        "explanation": "Оператор не подвёл итог.",
        "evidence": [5],
        "checked_range": {"from_index": 5, "to_index": 5},
        **over,
    }


def test_suggestion_points_after_a_transcript_message():
    reply = {"after_message": "M5", "reply": "Сұрағыңыз шешілді. Тағы көмек керек пе? Сау болыңыз!", "change": "Қорытынды қосылды."}
    llm = Recording({**ANSWERS, "generic": reply})
    with TestClient(create_app(lambda: llm, lambda: None)) as client:
        response = client.post("/suggest", json=_body())
    assert response.status_code == 200
    body = response.json()
    assert body["reply"].startswith("Сұрағыңыз") and body["after_index"] == 5 and body["code"] == "c7"
    system, user = llm.prompts[-1]
    assert "Do not invent facts" in system
    assert "Write \"change\" in Kazakh" in user and "M5–M5" in user


def test_a_stronger_generic_model_writes_the_suggestion():
    main = Recording(ANSWERS)
    strong = Recording({"generic": {"after_message": "M3", "reply": "ok", "change": "ok"}})
    strong.model = "strong"
    with TestClient(create_app(lambda: main, lambda: strong)) as client:
        body = client.post("/suggest", json=_body()).json()
    assert body["model"] == "strong" and strong.prompts and not main.prompts


def test_empty_transcript_is_rejected():
    with TestClient(create_app(lambda: FakeLLM(ANSWERS), lambda: None)) as client:
        assert client.post("/suggest", json=_body(transcript=[])).status_code == 422
