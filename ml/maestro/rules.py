"""Checklist rules: which probes to ask per criterion and how their answers become a verdict.

Probes are asked lazily, so a criterion that turns out N/A does not spend calls on the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .checklist import Answer
from .probes import Context
from .schemas import Role

GREETING = re.compile(
    r"\b(здравствуй\w*|добр(ый|ое|ого) (день|вечер|утро|времени)|приветствую|сәлем\w*|салем\w*|армысыз|"
    r"қайырлы (күн|таң|кеш)|hello|hi|good (morning|afternoon|evening))\b",
    re.IGNORECASE,
)
INTRODUCTION = re.compile(
    r"(меня зовут|менің атым|my name is|\[имя скрыто\]|\[name hidden\])",
    re.IGNORECASE,
)
IDENTITY_VERIFIED = re.compile(
    r"(личность клиента подтверждена|идентификац\w* (успешно )?пройден|жеке басы расталды|identity verified|"
    r"identity (has been |was )?confirmed)",
    re.IGNORECASE,
)
IDENTITY_REQUESTED = re.compile(
    r"(подтверд\w* личност|провед\w* идентификац|пройд\w* идентификац|начн\w* с идентификац|"
    r"жеке басыңызды растау|verify your identity|confirm your identity)",
    re.IGNORECASE,
)
CONDITIONAL = re.compile(r"\b(если|егер|if)\b", re.IGNORECASE)
QUESTION = re.compile(r"\w[^?]*\?")  # a client message with a question mark states a request
# "Можно поговорить с человеком?" has a question mark but no request on substance.
OPERATOR_REQUEST = re.compile(
    r"(оператор|человек|специалист|сотрудник|маман|адам|\bagent\b|\bhuman\b|representative|\boperator\b)",
    re.IGNORECASE,
)
GOODBYE = re.compile(
    r"(до свидания|всего (доброго|хорошего)|хорошего (дня|вечера)|сау болыңыз|сау бол\b|қош болыңыз|"
    r"\bgoodbye\b|\bbye\b|have a (nice|good|great) (day|evening))",
    re.IGNORECASE,
)


@dataclass
class Decision:
    answer: Answer
    facts: dict[str, bool] = field(default_factory=dict)
    na_reason: str | None = None  # text key, see texts.py
    evidence: list[str] = field(default_factory=list)  # message IDs
    expected_at: str | None = None


def _yes_no(value: bool) -> Answer:
    return "yes" if value else "no"


def _first_operator(ctx: Context) -> str | None:
    return ctx.facts.first_operator_id


def _cited(*answers) -> list[str]:
    ids: list[str] = []
    for answer in answers:
        if answer.message_id and answer.message_id not in ids:
            ids.append(answer.message_id)
    return ids


def _settle_by_phrase(ctx: Context, key: str, scope_ids: list[str], pattern: re.Pattern[str]) -> None:
    """Unambiguous wording, such as "Здравствуйте", answers a probe without asking the model."""
    hit = next((m for m in ctx.transcript.messages if m.id in scope_ids and pattern.search(m.text)), None)
    if hit is not None:
        ctx.settle(key, True, hit.id, "matched by a fixed phrase")


def c01(ctx: Context) -> Decision:
    first = _first_operator(ctx)
    if first is None:
        return Decision("no", {"greeted": False, "introduced": False, "client_language_used": False})
    _settle_by_phrase(ctx, "greeted", [first], GREETING)
    # Call transcripts hide names as "[Имя скрыто]"; the operator still said their name.
    _settle_by_phrase(ctx, "introduced", [first], INTRODUCTION)
    greeted, introduced = ctx.ask("greeted"), ctx.ask("introduced")
    client_lang, operator_lang = ctx.facts.client_language, ctx.facts.first_operator_language
    if client_lang != "unknown" and client_lang == operator_lang:
        same_language = True
    else:
        # Detection can be wrong (Kazakh written without its own letters), so a mismatch is confirmed by the model.
        same_language = ctx.ask("client_language_used").value
    facts = {"greeted": greeted.value, "introduced": introduced.value, "client_language_used": same_language}
    answer = all(facts.values())
    return Decision(_yes_no(answer), facts, evidence=[first], expected_at=None if answer else first)


def c02(ctx: Context) -> Decision:
    enough, known = ctx.ask("enough_info_from_start"), ctx.ask("used_known_details")
    # Asking again for what the client already gave fails the criterion even if nothing was missing.
    if not known.value:
        facts = {"enough_info_from_start": enough.value, "used_known_details": False}
        return Decision("no", facts, evidence=_cited(known), expected_at=known.message_id or _first_operator(ctx))
    if enough.value:
        return Decision("na", {"enough_info_from_start": True, "used_known_details": True}, "na_02", _cited(enough))
    clarified = ctx.ask("clarified_missing")
    facts = {"enough_info_from_start": False, "used_known_details": True, "clarified_missing": clarified.value}
    answer = clarified.value
    return Decision(
        _yes_no(answer), facts, evidence=_cited(known, clarified), expected_at=None if answer else _first_operator(ctx)
    )


def c03(ctx: Context) -> Decision:
    # A verification that happened, or that the operator asked for outright, shows identification was needed.
    for message in ctx.transcript.messages:
        verified = message.role is Role.SYSTEM and IDENTITY_VERIFIED.search(message.text)
        requested = (
            message.role is Role.OPERATOR
            and IDENTITY_REQUESTED.search(message.text)
            and not CONDITIONAL.search(message.text)
        )
        if verified or requested:
            ctx.settle("identification_required", True, message.id, "verification requested or reported")
            break
    required = ctx.ask("identification_required")
    if not required.value:
        return Decision("na", {"identification_required": False}, "na_03")
    confirmed = ctx.ask("identity_confirmed_first")
    facts = {"identification_required": True, "identity_confirmed_first": confirmed.value}
    return Decision(
        _yes_no(confirmed.value),
        facts,
        evidence=_cited(confirmed, required),
        expected_at=None if confirmed.value else (required.message_id or _first_operator(ctx)),
    )


def c04(ctx: Context) -> Decision:
    client_ids = [m.id for m in ctx.shown("client") if not OPERATOR_REQUEST.search(m.text)]
    _settle_by_phrase(ctx, "request_formulated", client_ids, QUESTION)
    formulated = ctx.ask("request_formulated")
    if not formulated.value:
        return Decision("na", {"request_formulated": False}, "na_04")
    level = ctx.level("04")
    return Decision(int(level.value), {"request_formulated": True}, evidence=_cited(level, formulated))


def c05(ctx: Context) -> Decision:
    impolite, complained = ctx.ask("impolite"), ctx.ask("client_complained")
    # Rudeness counts only with a message to point at, like gross violations.
    polite = not (impolite.value and impolite.message_id)
    facts = {"polite": polite, "client_complained": complained.value}
    evidence = [] if polite else _cited(impolite)
    expected_at = None
    reacted_ok = True
    if complained.value:
        reacted = ctx.ask("reacted_to_problem", complaint=complained.message_id or "unknown")
        facts["reacted_to_problem"] = reacted.value
        reacted_ok = reacted.value
        evidence += _cited(complained, reacted)
        if not reacted.value and complained.message_id:
            expected_at = _next_operator(ctx, complained.message_id)
    answer = polite and reacted_ok
    return Decision(_yes_no(answer), facts, evidence=evidence, expected_at=expected_at)


def _next_operator(ctx: Context, message_id: str) -> str | None:
    messages = ctx.transcript.messages
    start = next((i for i, m in enumerate(messages) if m.id == message_id), len(messages))
    return next((m.id for m in messages[start + 1 :] if m.role is Role.OPERATOR), None)


def c06(ctx: Context) -> Decision:
    # Scale from the checklist: 0 incoherent, 4 the client has to ask again, 7 one noticeable lapse, 10 clear.
    # Rudeness is scored in 05 and 08, not here.
    incoherent = ctx.ask("incoherent")
    if incoherent.value and incoherent.message_id:
        return Decision(0, {"incoherent": True}, evidence=_cited(incoherent), expected_at=incoherent.message_id)
    asked_again = ctx.ask("client_asked_again")
    if asked_again.value:
        facts = {"incoherent": False, "client_asked_again": True}
        return Decision(4, facts, evidence=_cited(asked_again), expected_at=asked_again.message_id)
    lapse = ctx.ask("noticeable_lapse")
    facts = {"incoherent": False, "client_asked_again": False, "noticeable_lapse": lapse.value}
    if lapse.value:
        return Decision(7, facts, evidence=_cited(lapse), expected_at=lapse.message_id)
    return Decision(10, facts, evidence=[ctx.facts.first_operator_id] if ctx.facts.first_operator_id else [])


def c07(ctx: Context) -> Decision:
    last = ctx.facts.last_operator_id
    if last is None:
        return Decision("na", {"chat_cut_off": True}, "na_07")
    cut = ctx.ask("chat_cut_off")
    if cut.value:
        return Decision("na", {"chat_cut_off": True}, "na_07", _cited(cut))
    tail_ids = [m.id for m in ctx.shown("operator_tail")]
    _settle_by_phrase(ctx, "said_goodbye", tail_ids, GOODBYE)
    summarized, offered, goodbye = ctx.ask("summarized"), ctx.ask("offered_help"), ctx.ask("said_goodbye")
    facts = {
        "chat_cut_off": False,
        "summarized": summarized.value,
        "offered_help": offered.value,
        "said_goodbye": goodbye.value,
    }
    # The checklist wording allows two readings. This one needs a summary or an offer of
    # further help, plus a goodbye. Review it once ground truth is available.
    answer = (summarized.value or offered.value) and goodbye.value
    return Decision(
        _yes_no(answer), facts, evidence=_cited(summarized, offered, goodbye) or [last], expected_at=None if answer else last
    )


def c08(ctx: Context) -> Decision:
    facts: dict[str, bool] = {}
    evidence: list[str] = []
    for key in ("insult", "off_company_offer", "confidential_disclosure"):
        found = ctx.ask(key)
        # A flag stands only with an operator message to point at.
        facts[key] = bool(found.value and found.message_id)
        if facts[key]:
            evidence += _cited(found)
    return Decision(_yes_no(any(facts.values())), facts, evidence=evidence)


DECIDERS: dict[str, Callable[[Context], Decision]] = {
    "01": c01, "02": c02, "03": c03, "04": c04, "05": c05, "06": c06, "07": c07, "08": c08,
}
