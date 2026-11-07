"""Narrow questions ("probes") asked of the LLM, one per call.

Ideas behind the design:
- The model never gives a verdict. Each criterion is split into yes/no probes, and code
  in rules.py derives the verdict.
- Each probe sees only the messages that can answer it, which avoids "who said it" mistakes.
- The model points at a message by ID. Evidence text is always taken from the transcript
  by code, so a quote cannot be invented.
- The model states its reasoning before the answer: small models asked to answer or quote
  first tend to justify whatever they picked.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .facts import ChatFacts, render_facts
from .llm import LLMClient, LLMOutputError, extract_json
from .schemas import AttemptTrace, Message, Role, Transcript

Scope = Literal["first_operator", "opening", "operator", "operator_tail", "client", "people", "all"]
Cite = Literal["any", "operator", "client"]

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")
MAX_ATTEMPTS = 3
OPERATOR_TAIL = 3
CALL_NOTE = (
    "Note: this is a phone call transcribed by speech recognition. It contains recognition errors: garbled or "
    "nonsense words, broken grammar, wrong word boundaries. Do not treat these errors as the operator's words, "
    "rudeness or illiteracy; judge what the operator evidently meant. Placeholders such as '[Имя скрыто]' or "
    "'[Персональные данные скрыты]' replace real names and personal data that were said aloud."
)

SCOPE_INTRO: dict[Scope, str] = {
    "first_operator": "The operator's FIRST message in the chat",
    "opening": "The start of the chat, up to and including the operator's first message",
    "operator": "All messages written by the OPERATOR",
    "operator_tail": "The operator's LAST messages in the chat",
    "client": "All messages written by the CLIENT",
    # The bot's boilerplate ("I can share information about your accounts", privacy consent)
    # misleads questions about account data, so those questions do not see bot messages.
    "people": "The chat without the bot's messages: client, operator and system events",
    "all": "The whole chat",
}


@dataclass(frozen=True)
class Probe:
    key: str
    scope: Scope
    question: str
    cite: Cite = "any"
    hints: bool = False  # include facts computed by code


@dataclass(frozen=True)
class LevelProbe:
    key: str
    levels: tuple[int, ...]
    question: str


PROBES: dict[str, Probe] = {
    p.key: p
    for p in (
        # 01 Establishing contact
        Probe("greeted", "first_operator", "Does this message contain a greeting, for example 'Здравствуйте', 'Сәлеметсіз бе' or 'Hello'?"),
        Probe(
            "introduced",
            "first_operator",
            "Does the operator give their own name or say who they are in this message, for example "
            "'меня зовут Айгуль', 'менің атым Данияр', 'Мен Нұрланмын' or 'support specialist Anna'? "
            "A company name alone does NOT count. A placeholder such as '[Имя скрыто]' is an anonymised name "
            "and counts as the operator saying their name.",
        ),
        Probe(
            "client_language_used",
            "opening",
            "Is the operator's first message written in the same language as the client's messages "
            "(Russian, Kazakh or English)?",
            cite="operator",
            hints=True,
        ),
        # 02 Needs discovery
        Probe(
            "enough_info_from_start",
            "all",
            "Did the client's messages BEFORE the operator's first answer already contain everything needed "
            "to answer, so that no clarifying question was necessary? A general question with one clear answer, "
            "such as a tariff or how to open an account, counts as yes. A greeting without a request, or a request "
            "that depends on details the client has not given, counts as no.",
            cite="client",
        ),
        Probe(
            "used_known_details",
            "all",
            "Did the operator take into account the details the client had already given, without asking for them again? "
            "If the client had not given any details, answer true.",
            cite="operator",
        ),
        Probe(
            "clarified_missing",
            "all",
            "Before giving the answer, did the operator ask the client for the details that were missing? "
            "If the client gave no request at first, asking how they can help counts.",
            cite="operator",
        ),
        # 03 Identification
        Probe(
            "identification_required",
            "people",
            "Did helping the client require the operator to look into or act on the client's OWN account? Answer true "
            "if the client asked for information only their account can show (why their withdrawal is restricted, "
            "where their deposit is, their balance, holdings or order status) or for an operation on the account, "
            "or if the OPERATOR revealed anything about the client's account, for example the operator writing 'I can "
            "see a restriction on your account'. Answer false when the operator can help without looking at the "
            "account: login problems, where to find or how to do something in the app or on the website, how to "
            "update personal data, where to download a report or payment details, which account type to use, "
            "tariffs, how a feature works. The client mentioning their account or a blocked action is not enough.",
        ),
        Probe(
            "identity_confirmed_first",
            "people",
            "Is the client's identity confirmed in the chat BEFORE the operator disclosed account information or "
            "performed an account action? A system message reporting successful verification, or the operator checking "
            "details and confirming they match, counts. Only asking the client to verify, without confirmation, does NOT count.",
        ),
        # 04 Consultation
        Probe(
            "request_formulated",
            "client",
            "Did the client ask any question, make any request or describe any problem? Every kind counts: "
            "'What is the commission?', 'How do I open an account?', 'Show my balance', 'I cannot log in'. "
            "A greeting alone, or 'thank you', does not count.",
        ),
        # 05 Empathy
        Probe(
            "impolite",
            "operator",
            "Is any of these operator messages rude, sarcastic, dismissive or blaming the client? "
            "If yes, point to that message.",
            cite="operator",
        ),
        Probe(
            "client_complained",
            "client",
            "Does any of these client messages express dissatisfaction or describe an inconvenience, such as an error, "
            "a delay, lost money or time, or frustration? A plain question is NOT a complaint.",
        ),
        Probe(
            "reacted_to_problem",
            "all",
            "The client complained in message {complaint}. Did the operator respond to that specific problem? Any one "
            "of these counts: acknowledging the client's concern ('I understand why you are worried', 'Понимаю, что "
            "вы переживаете'), apologising, or giving an explanation or steps aimed at that specific problem. "
            "Answer false only if the operator ignored the problem, brushed it off, or replied with nothing but a "
            "generic phrase such as 'thank you for contacting us'.",
            cite="operator",
        ),
        # 07 Closing
        Probe(
            "chat_cut_off",
            "all",
            "Did the chat break off before the operator had a chance to close it, for example the client stopped "
            "replying mid-dialogue and the chat was closed, or the connection dropped? If the operator answered and "
            "simply did not say goodbye, answer false.",
        ),
        Probe("summarized", "operator_tail", "Does the operator sum up the outcome of the conversation?"),
        Probe(
            "offered_help",
            "operator_tail",
            "Does the operator offer further help or invite the client to come back with questions? Examples: "
            "'Can I help with anything else?', 'Обращайтесь', 'Пишите, если будут вопросы', "
            "'Сұрақтарыңыз болса, жазыңыз', 'Write to us if you have questions'.",
        ),
        Probe("said_goodbye", "operator_tail", "Does the operator say goodbye or wish the client well?"),
        # 08 Gross violations
        Probe(
            "insult",
            "operator",
            "Does any operator message insult or humiliate the client, belittle the client's intelligence or "
            "competence (for example 'you clearly understand nothing'), or swear at the client?",
            cite="operator",
        ),
        Probe(
            "off_company_offer",
            "operator",
            "Does the operator offer their OWN private service outside the company, for example ask the client to "
            "transfer money to the operator personally for investing, or ask for the client's personal phone number "
            "to give paid advice privately? The offer alone is enough. Pointing the client to the company's own "
            "websites, apps, web terminal, departments or managers is NOT an offer outside the company.",
            cite="operator",
        ),
        Probe(
            "confidential_disclosure",
            "all",
            "Does the operator disclose confidential information: data of another client, internal confidential company "
            "information, or this client's account data before the client's identity was confirmed?",
            cite="operator",
        ),
    )
}

LEVEL_PROBES: dict[str, LevelProbe] = {
    "04": LevelProbe(
        "consultation_level",
        (0, 5, 10, 15, 20),
        "How correctly and completely did the operator resolve the client's request? Judge substance only, not tone "
        "or clarity: a clear answer to one of two important questions still gets a partial level. First list each "
        "question the client asked and whether it was answered. You do not have the broker's reference materials, so "
        "treat a recommendation as wrong only if it contradicts itself, the chat, or common sense. Pick one level:\n"
        "20: all material questions are closed, or a correct next step is given.\n"
        "15: the main question is resolved, a secondary detail is missing.\n"
        "10: part of the request is closed, a material question remains open.\n"
        "5: there is a general hint, but the client still does not know how to act.\n"
        "0: there is no answer on substance, or the key recommendation is wrong.",
    ),
    "06": LevelProbe(
        "dialogue_level",
        (0, 4, 7, 10),
        "How clearly and consistently did the operator communicate? Judge clarity, the order of replies, spelling and "
        "grammar, and whether the operator warned the client before an explicit wait (leaving to check something, or a "
        "long pause listed in the hints). Do not judge whether the answer was correct or complete, and do not judge "
        "the speed of the first response. Pick one level:\n"
        "10: replies are clear and coherent; if there was an explicit wait, the operator warned the client.\n"
        "7: one noticeable lapse, such as an unannounced wait, but the client can understand the reply and continue.\n"
        "4: the client has to ask again because of the wording or the order of replies.\n"
        "0: incoherent or contradictory replies make the course of the dialogue impossible to follow.",
    ),
}


@dataclass(frozen=True)
class ProbeAnswer:
    value: bool | int
    message_id: str | None
    why: str


@dataclass
class Context:
    """One chat being scored: runs probes on demand and caches their answers."""

    transcript: Transcript
    facts: ChatFacts
    llm: LLMClient
    channel: str = "agent chat"
    traces: dict[str, list[AttemptTrace]] = field(default_factory=dict)
    _cache: dict[str, ProbeAnswer] = field(default_factory=dict)

    def message(self, message_id: str | None) -> Message | None:
        return next((m for m in self.transcript.messages if m.id == message_id), None)

    def shown(self, scope: Scope) -> list[Message]:
        messages = self.transcript.messages
        operator = [m for m in messages if m.role is Role.OPERATOR]
        if scope == "first_operator":
            return operator[:1]
        if scope == "opening":
            if not operator:
                return []
            return messages[: messages.index(operator[0]) + 1]
        if scope == "operator":
            return operator
        if scope == "operator_tail":
            return operator[-OPERATOR_TAIL:]
        if scope == "client":
            return [m for m in messages if m.role is Role.CLIENT]
        if scope == "people":
            return [m for m in messages if m.role is not Role.BOT]
        return list(messages)

    def settle(self, key: str, value: bool, message_id: str | None, why: str) -> None:
        """Record an answer found by code, so the model is not asked."""
        self._cache.setdefault(key, ProbeAnswer(value, message_id, why))

    def ask(self, key: str, **params: str) -> ProbeAnswer:
        """Ask a yes/no probe. A probe with nothing to look at answers no without a call."""
        if key in self._cache:
            return self._cache[key]
        probe = PROBES[key]
        shown = self.shown(probe.scope)
        roles = {"operator": {Role.OPERATOR}, "client": {Role.CLIENT}}.get(probe.cite)
        citable = [m.id for m in shown if roles is None or m.role in roles]
        if not shown or not citable:
            answer = ProbeAnswer(False, None, "nothing to check in this scope")
        else:
            question = probe.question.format(**params)
            hints = render_facts(self.facts) if probe.hints else None
            data = self._call(key, SCOPE_INTRO[probe.scope], shown, question, hints, citable, {"type": "boolean"})
            value = data["answer"] is True
            cited = data["message"] if data["message"] in citable else None
            if cited is None and len(citable) == 1:
                cited = citable[0]
            answer = ProbeAnswer(value, cited, str(data.get("why", "")))
        self._cache[key] = answer
        return answer

    def level(self, criterion_id: str) -> ProbeAnswer:
        probe = LEVEL_PROBES[criterion_id]
        if probe.key in self._cache:
            return self._cache[probe.key]
        shown = self.shown("all")
        data = self._call(
            probe.key,
            SCOPE_INTRO["all"],
            shown,
            probe.question,
            render_facts(self.facts),
            [m.id for m in shown],
            {"type": "integer", "enum": list(probe.levels)},
        )
        if data["answer"] not in probe.levels:
            raise LLMOutputError(f"{probe.key}: level {data['answer']!r} is not one of {probe.levels}")
        cited = data["message"] if self.message(data["message"]) else None
        answer = ProbeAnswer(int(data["answer"]), cited, str(data.get("why", "")))
        self._cache[probe.key] = answer
        return answer

    def _call(
        self,
        key: str,
        intro: str,
        shown: list[Message],
        question: str,
        hints: str | None,
        citable: list[str],
        answer_schema: dict[str, Any],
    ) -> dict[str, Any]:
        schema = {
            "type": "object",
            "properties": {
                "why": {"type": "string"},
                "answer": answer_schema,
                "message": {"type": "string", "enum": [*citable, "none"]},
            },
            "required": ["why", "answer", "message"],
        }
        data = self.call(key, SYSTEM_PROMPT, render_prompt(intro, shown, question, hints), schema)
        data.setdefault("message", "none")
        return data

    def call(self, key: str, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Ask the model, retrying unusable answers, and record every attempt under `key`."""
        if "call" in self.channel.lower():
            prompt = f"{CALL_NOTE}\n\n{prompt}"
        traces = self.traces.setdefault(key, [])
        required = [name for name in schema.get("required", []) if name != "message"]
        last_error = ""
        for _ in range(MAX_ATTEMPTS):
            digest = hashlib.sha256((system + prompt).encode()).hexdigest()
            try:
                response = self.llm.complete(system, prompt, schema)
            except LLMOutputError as exc:
                last_error = str(exc)
                traces.append(AttemptTrace(probe=key, prompt_sha256=digest, raw_response="", duration_ms=0, error=last_error))
                continue
            trace = AttemptTrace(
                probe=key,
                prompt_sha256=digest,
                raw_response=response.content,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                duration_ms=response.duration_ms,
            )
            traces.append(trace)
            try:
                data = extract_json(response.content)
                missing = [name for name in required if name not in data]
                if missing:
                    raise LLMOutputError(f"missing fields: {', '.join(missing)}")
                return data
            except LLMOutputError as exc:
                last_error = trace.error = str(exc)
        raise LLMOutputError(f"{key}: no valid answer after {MAX_ATTEMPTS} attempts: {last_error}")


def render_messages(messages: list[Message]) -> str:
    lines = []
    for message in messages:
        if message.time_text:
            stamp = f" | {message.time_text}"
        elif message.timestamp:
            stamp = f" | {message.timestamp:%Y-%m-%d %H:%M:%S}"
        else:
            stamp = ""
        lines.append(f"[{message.id}{stamp} | {message.role.value}] {message.text}")
    return "\n".join(lines)


def render_prompt(intro: str, shown: list[Message], question: str, hints: str | None) -> str:
    parts = [f"{intro}:\n<messages>\n{render_messages(shown)}\n</messages>"]
    if hints:
        parts.append(f"Facts computed by code (may be incomplete):\n{hints}")
    parts.append(f"Question: {question}")
    return "\n\n".join(parts)
