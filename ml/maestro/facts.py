"""Facts computed by code and passed to the LLM as hints. They never set a score."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .schemas import Role, Transcript

LONG_PAUSE_SECONDS = 300

KAZAKH_LETTERS = set("әғқңөұүһі")
KAZAKH_WORDS = {"сәлем", "салем", "рахмет", "иә", "жоқ", "жок", "керек", "қалай", "калай", "сіз", "сиз", "мен", "бар"}
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def detect_language(text: str) -> str:
    """Return ru, kk, en or unknown using letters and a few very common Kazakh words."""
    lowered = text.lower()
    words = WORD.findall(lowered)
    if not words:
        return "unknown"
    if KAZAKH_LETTERS & set(lowered):
        return "kk"
    letters = "".join(words)
    cyrillic = sum("а" <= ch <= "я" or ch == "ё" for ch in letters)
    if cyrillic * 2 >= len(letters):
        hits = sum(word in KAZAKH_WORDS for word in words)
        return "kk" if hits and hits * 3 >= len(words) else "ru"
    return "en" if lowered.isascii() or cyrillic == 0 else "unknown"


@dataclass
class ChatFacts:
    client_language: str = "unknown"
    first_operator_id: str | None = None
    first_operator_language: str = "unknown"
    last_operator_id: str | None = None
    last_message_id: str = ""
    last_message_role: str = ""
    system_messages: list[str] = field(default_factory=list)
    long_pauses: list[str] = field(default_factory=list)


def _client_language(transcript: Transcript) -> str:
    votes: Counter[str] = Counter()
    for message in transcript.messages:
        if message.role is Role.CLIENT:
            language = detect_language(message.text)
            if language != "unknown":
                votes[language] += len(message.text)
    return votes.most_common(1)[0][0] if votes else "unknown"


def extract_facts(transcript: Transcript, language_hint: str | None = None) -> ChatFacts:
    """`language_hint` (ru, kk or en) is used when the client's own messages do not reveal a language."""
    messages = transcript.messages
    operators = [m for m in messages if m.role is Role.OPERATOR]
    last = messages[-1]
    client_language = _client_language(transcript)
    if client_language == "unknown" and language_hint:
        client_language = language_hint
    facts = ChatFacts(
        client_language=client_language,
        last_message_id=last.id,
        last_message_role=last.role.value,
        system_messages=[m.id for m in messages if m.role is Role.SYSTEM],
    )
    if operators:
        facts.first_operator_id = operators[0].id
        facts.first_operator_language = detect_language(operators[0].text)
        facts.last_operator_id = operators[-1].id

    for previous, current in zip(messages, messages[1:]):
        if current.role is not Role.OPERATOR or previous.timestamp is None or current.timestamp is None:
            continue
        gap = (current.timestamp - previous.timestamp).total_seconds()
        if gap >= LONG_PAUSE_SECONDS:
            facts.long_pauses.append(f"{previous.id} to {current.id}: {round(gap / 60)} min")
    return facts


def render_facts(facts: ChatFacts) -> str:
    lines = [
        f"- Client language (detected): {facts.client_language}",
        f"- First operator message: {facts.first_operator_id or 'none'}",
        f"- Language of the first operator message (detected): {facts.first_operator_language}",
        f"- Last operator message: {facts.last_operator_id or 'none'}",
        f"- Last message in the chat: {facts.last_message_id} ({facts.last_message_role})",
        f"- System messages: {', '.join(facts.system_messages) or 'none'}",
        f"- Operator pauses of 5 minutes or more: {'; '.join(facts.long_pauses) or 'none or no timestamps'}",
    ]
    return "\n".join(lines)
