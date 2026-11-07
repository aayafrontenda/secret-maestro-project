import json

import pytest

from maestro.facts import detect_language, extract_facts
from maestro.ingest import IngestError, parse_bytes, parse_json_object, parse_text
from maestro.schemas import Role


def test_json_shapes():
    single = {"id": "a", "messages": [{"sender": "Клиент", "message": "Привет"}, {"author": "agent", "content": "Здравствуйте"}]}
    [chat] = parse_json_object(single)
    assert chat.chat_id == "a"
    assert [m.role for m in chat.messages] == [Role.CLIENT, Role.OPERATOR]
    assert [m.id for m in chat.messages] == ["M1", "M2"]

    many = parse_json_object({"chats": [single, {**single, "id": "b"}]})
    assert [c.chat_id for c in many] == ["a", "b"]

    rows = [
        {"chat_id": 1, "role": "client", "text": "x"},
        {"chat_id": 2, "role": "client", "text": "y"},
        {"chat_id": 1, "role": "operator", "text": "z"},
    ]
    assert [len(c.messages) for c in parse_json_object(rows)] == [2, 1]


def test_attachments_become_placeholders_and_tags_are_dropped():
    data = {"messages": [{"role": "client", "text": "", "attachments": ["a.png"], "tags": ["vip"]}]}
    [chat] = parse_json_object(data)
    assert chat.messages[0].text == "[attachment]"


def test_unknown_role_fails_loudly():
    with pytest.raises(IngestError):
        parse_json_object({"messages": [{"role": "martian", "text": "hi"}]})


def test_plain_text_with_continuations():
    text = "[10:00:01] Клиент: Здравствуйте\n[10:01:00] Оператор: Добрый день!\nчем помочь?\nSystem: closed"
    [chat] = parse_text(text, "t")
    assert len(chat.messages) == 3
    assert chat.messages[1].text == "Добрый день!\nчем помочь?"
    assert chat.messages[0].timestamp.hour == 10


def test_csv_with_semicolons():
    data = "chat_id;role;text;time\n7;client;Вопрос;2026-11-01 10:00:00\n7;operator;Ответ;2026-11-01 10:01:00\n"
    [chat] = parse_bytes("chats.csv", data.encode("utf-8"))
    assert chat.chat_id == "7" and len(chat.messages) == 2


def test_synthetic_dataset_parses():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "chats.json"
    chats = parse_json_object(json.loads(path.read_text(encoding="utf-8")))
    assert len(chats) == 12
    assert all(m.timestamp is not None for c in chats for m in c.messages)


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Сәлеметсіз бе, шотты қалай ашамын?", "kk"),
        ("Здравствуйте, как открыть счёт?", "ru"),
        ("Hello, how do I open an account?", "en"),
        ("Салем, рахмет", "kk"),
        ("12345", "unknown"),
    ],
)
def test_language_detection(text, language):
    assert detect_language(text) == language


def test_facts_find_long_pauses():
    data = {
        "messages": [
            {"role": "client", "text": "Вопрос", "time": "2026-11-01T10:00:00"},
            {"role": "operator", "text": "Ответ", "time": "2026-11-01T10:20:00"},
        ]
    }
    facts = extract_facts(parse_json_object(data)[0])
    assert facts.long_pauses == ["M1 to M2: 20 min"]
    assert facts.first_operator_id == "M2"
