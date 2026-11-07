"""Checklist rules: which probes to ask per criterion and how their answers become a verdict.

Probes are asked lazily, so a criterion that turns out N/A does not spend calls on the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .checklist import Answer
from .probes import Context, ProbeAnswer
from .schemas import Role

GREETING = re.compile(
    r"\b(здравствуй\w*|добр(ый|ое|ого) (день|вечер|утро|времени)|приветствую|сәлем\w*|салем\w*|армысыз|"
    r"қайырлы (күн|таң|кеш)|кайырлы (кун|тан|кеш)|salem\w*|qayirli \w+|hello|hi|good (morning|afternoon|evening))\b",
    re.IGNORECASE,
)
INTRODUCTION = re.compile(
    r"(меня зовут|менің атым|менин атым|menin atym|my name is|\[имя скрыто\]|\[name hidden\])",
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
OPERATOR_CLOSED = re.compile(
    r"(оператор закрыл чат|чат закрыт оператором|оператор чатты жапты|agent closed the chat|"
    r"chat closed by (the )?(operator|agent))",
    re.IGNORECASE,
)
CLIENT_GONE = re.compile(
    r"(клиент покинул чат|клиент завершил разговор|соединение с клиентом прервано|связь с клиентом прервана|"
    r"клиентпен байланыс үзілді|клиент чаттан шықты|connection to (the )?customer lost|customer left|"
    r"customer ended the (call|chat))",
    re.IGNORECASE,
)
# The operator saying verification is needed, including conditional wording ("если нужно проверить счёт, понадобится
# идентификация"): asking for it, rather than skipping it, is what the operator is judged on.
VERIFICATION_ASKED = re.compile(
    r"(подтверд\w* личност|идентификац|жеке бас\w* раста|verif\w* (your )?identity|confirm (your )?identity|"
    r"identity (check|verification))",
    re.IGNORECASE,
)
CONDITIONAL = re.compile(r"\b(если|егер|if)\b", re.IGNORECASE)
QUESTION = re.compile(r"\w[^?]*\?")  # a client message with a question mark states a request
# "Можно поговорить с человеком?" has a question mark but no request on substance.
OPERATOR_REQUEST = re.compile(
    r"(оператор|человек|специалист|сотрудник|маман|адам|\bagent\b|\bhuman\b|representative|\boperator\b)",
    re.IGNORECASE,
)
# An operator asking for details: a question or a request to tell something.
CLARIFYING = re.compile(
    r"(\?|уточн\w*|укаж\w*|напиш\w*|подскаж\w*|сообщ\w*|назов\w*|пришл\w*|нақтыла\w*|айтыңыз|жазыңыз|"
    r"көрсетіңіз|\bspecify\b|\btell me\b|\blet me know\b|\bplease (send|share|confirm)\b|"
    # A question without a question mark: a question word at the start of a sentence, or a Kazakh question particle.
    r"(^|[.!]\s+)(как(ой|ая|ое|ие|им)|где|когда|куда|откуда|сколько|почему|зачем|чем|вы\s|у вас\s|"
    r"қай|қандай|қашан|қалай|қайда|неше|неге|which|what|where|when|how|why|do you|are you|can you)\b|"
    r"\w+\s(ма|ме|ба|бе|па|пе)(\s|$|[.,!]))",
    re.IGNORECASE,
)
# A closing offer of further help is a question but not a clarification. An opening "С чем помочь?" is one.
HELP_OFFER = re.compile(
    r"(чем ещ[её]|ещ[её] (какие[- ]то )?вопрос|ещ[её] (чем[- ]то )?помочь|басқа сұра\w*|тағы (қандай )?сұра\w*|"
    r"тағы көмек|anything else|other questions)",
    re.IGNORECASE,
)
# The operator asking for verification data or how to address the client: routine, not asking again for known details.
ROUTINE_QUESTION = re.compile(
    r"(фамили|отчеств|ф\.?\s?и\.?\s?о\b|\bиин\b|\bин\b|\bжсн\b|номер телефона|\bсмс\b|\bsms\b|шестизначн|"
    r"код подтвержд|идентификац|подтверд\w* личност|жеке бас\w* раста|адрес\w* (вашей )?(постоянной )?регистрац|"
    r"адрес\w* проживани|как (я )?(могу |можно )?(к вам )?обращаться|как\w* (мы )?к вам обращаться|как вас зовут|"
    r"атыңыз кім|full name|date of birth|phone number|verification code|how (should|can) i address you)",
    re.IGNORECASE,
)
GOODBYE = re.compile(
    r"(до свидания|всего (доброго|хорошего)|хорошего (дня|вечера)|сау болыңыз|сау бол\b|қош болыңыз|"
    r"\bsau bol\w*|\bkosh bol\w*|"
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
    # Kazakh typed without its own letters is detected as Russian, so a dialog marked as Kazakh with a
    # "Russian" operator reply is not settled by code.
    dialog_says_other = ctx.facts.dialog_language not in (None, operator_lang)
    if client_lang != "unknown" and client_lang == operator_lang and not dialog_says_other:
        same_language = True
    else:
        # Detection can be wrong (Kazakh written without its own letters), so a mismatch is confirmed by the model.
        same_language = ctx.ask("client_language_used").value
    facts = {"greeted": greeted.value, "introduced": introduced.value, "client_language_used": same_language}
    answer = all(facts.values())
    return Decision(_yes_no(answer), facts, evidence=[first], expected_at=None if answer else first)


def c02(ctx: Context) -> Decision:
    enough, known = ctx.ask("enough_info_from_start"), ctx.ask("used_known_details")
    if not known.value and _is_routine(ctx, known.message_id):
        # The "repeated" question was a verification or etiquette question, not a known detail asked again.
        known = ProbeAnswer(True, known.message_id, "routine question, not a known detail asked again")
    # Asking again for what the client already gave fails the criterion even if nothing was missing.
    if not known.value:
        facts = {"enough_info_from_start": enough.value, "used_known_details": False}
        return Decision("no", facts, evidence=_cited(known), expected_at=known.message_id or _first_operator(ctx))
    if enough.value:
        return Decision("na", {"enough_info_from_start": True, "used_known_details": True}, "na_02", _cited(enough))
    clarified = ctx.ask("clarified_missing")
    asked = clarified.value
    if asked and "call" not in ctx.channel.lower():
        # A clarification needs an operator question or request for details somewhere in the chat; a guess
        # ("Переустановите приложение") is not one. Speech transcripts may lack question marks, so calls are trusted.
        asked = any(
            m.role is Role.OPERATOR and CLARIFYING.search(m.text) and not HELP_OFFER.search(m.text)
            for m in ctx.transcript.messages
        )
    facts = {"enough_info_from_start": False, "used_known_details": True, "clarified_missing": asked}
    answer = asked
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
    if confirmed.value:
        return Decision("yes", facts, evidence=_cited(confirmed, required))
    # Not confirmed. The operator still did the job if they asked for verification and revealed nothing
    # about the account (the client declined or left); "no" is for skipping or doing it wrong.
    asked = next((m for m in ctx.transcript.messages if m.role is Role.OPERATOR and VERIFICATION_ASKED.search(m.text)), None)
    if asked is not None:
        disclosed = ctx.ask("account_info_disclosed")
        facts.update(verification_asked=True, account_info_disclosed=disclosed.value)
        if not disclosed.value:
            return Decision("yes", facts, evidence=[asked.id])
        return Decision("no", facts, evidence=_cited(disclosed, required), expected_at=disclosed.message_id)
    facts["verification_asked"] = False
    return Decision("no", facts, evidence=_cited(required), expected_at=required.message_id or _first_operator(ctx))


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


def _is_routine(ctx: Context, message_id: str | None) -> bool:
    message = ctx.message(message_id)
    return message is not None and message.role is Role.OPERATOR and bool(ROUTINE_QUESTION.search(message.text))


def _previous_operator(ctx: Context, message_id: str) -> str | None:
    messages = ctx.transcript.messages
    end = next((i for i, m in enumerate(messages) if m.id == message_id), 0)
    return next((m.id for m in reversed(messages[:end]) if m.role is Role.OPERATOR), None)


def c06(ctx: Context) -> Decision:
    # Scale from the checklist: 0 incoherent, 4 the client has to ask again, 7 one noticeable lapse, 10 clear.
    # Rudeness is scored in 05 and 08, not here.
    incoherent = ctx.ask("incoherent")
    if incoherent.value and incoherent.message_id:
        # Level 0 means the course of the dialogue cannot be followed; confirm on the cited reply alone.
        clear = ctx.ask("reply_understandable", msg=incoherent.message_id)
        if clear.value:
            incoherent = ProbeAnswer(False, None, "the cited reply is understandable")
    if incoherent.value and incoherent.message_id:
        return Decision(0, {"incoherent": True}, evidence=_cited(incoherent), expected_at=incoherent.message_id)
    asked_again = ctx.ask("client_asked_again")
    if asked_again.value and asked_again.message_id:
        # A broad question over the whole chat over-counts follow-ups; confirm on the message pair.
        prev = _previous_operator(ctx, asked_again.message_id)
        if prev is not None:
            confirmed = ctx.ask("asked_again_confirmed", msg=asked_again.message_id, prev=prev)
            if not confirmed.value:
                asked_again = ProbeAnswer(False, None, "not confirmed on the message pair")
    if asked_again.value:
        facts = {"incoherent": False, "client_asked_again": True}
        return Decision(4, facts, evidence=_cited(asked_again), expected_at=asked_again.message_id)
    lapse = ctx.ask("noticeable_lapse")
    if lapse.value and _is_routine(ctx, lapse.message_id):
        lapse = ProbeAnswer(False, None, "routine question, not a lapse")
    if lapse.value and lapse.message_id:
        # The broad question contradicted its own reasoning or counted other criteria; confirm on the message.
        confirmed = ctx.ask("lapse_confirmed", msg=lapse.message_id)
        if not confirmed.value:
            lapse = ProbeAnswer(False, None, "not confirmed on the message")
    facts = {"incoherent": False, "client_asked_again": False, "noticeable_lapse": lapse.value}
    if lapse.value:
        return Decision(7, facts, evidence=_cited(lapse), expected_at=lapse.message_id)
    return Decision(10, facts, evidence=[ctx.facts.first_operator_id] if ctx.facts.first_operator_id else [])


def c07(ctx: Context) -> Decision:
    last = ctx.facts.last_operator_id
    if last is None:
        return Decision("na", {"chat_cut_off": True}, "na_07")
    _settle_cut_off(ctx, last)
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


def _settle_cut_off(ctx: Context, last_operator_id: str) -> None:
    """System events say how the chat ended. The operator closing it is not a cut-off; the client
    leaving or the line dropping before the operator said goodbye is."""
    messages = ctx.transcript.messages
    last_operator = next(m for m in messages if m.id == last_operator_id)
    after = messages[messages.index(last_operator) + 1 :]
    for message in after:
        if message.role is not Role.SYSTEM:
            continue
        if OPERATOR_CLOSED.search(message.text):
            ctx.settle("chat_cut_off", False, message.id, "the operator closed the chat")
            return
        if CLIENT_GONE.search(message.text):
            said_goodbye = bool(GOODBYE.search(last_operator.text))
            ctx.settle("chat_cut_off", not said_goodbye, message.id, "the client left or the line dropped")
            return


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
