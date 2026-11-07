"""Recognise the eight standard checklist criteria inside a user-editable checklist.

A criterion from the request uses the detailed built-in logic only while its rule still
says what the standard criterion says. A reworded or new criterion is scored by the
generic evaluator instead, so edits made in the checklist editor always take effect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .checklist import BY_ID



@dataclass(frozen=True)
class Standard:
    preset_id: str
    rules: tuple[str, ...]  # standard wording in the languages the checklist may be written in
    answer_type: str  # "yes_no" or "scale"
    is_flag: bool = False


# The rule texts come from the official checklist PDF, so they stay in its languages.
STANDARDS: tuple[Standard, ...] = (
    Standard("01", ("Да — оператор поздоровался на языке клиента и представился в первом ответе.",
                    "Yes — the operator greeted the client in the client's language and introduced themselves in the first reply."), "yes_no"),
    Standard("02", ("Да — оператор учёл известные детали и уточнил недостающее до ответа.",
                    "Yes — the operator took known details into account and clarified what was missing before answering."), "yes_no"),
    Standard("03", ("Да — проверка личности подтверждена до раскрытия данных или защищённого действия.",
                    "Yes — identity verification was confirmed before disclosing data or a protected action."), "yes_no"),
    Standard("04", ("Оцените ответ или следующий шаг по шкале.",
                    "Rate the answer or the next step on the scale."), "scale"),
    Standard("05", ("Да — оператор вежлив и, если клиент выразил недовольство или описал неудобство, отреагировал на конкретную проблему.",
                    "Yes — the operator is polite and, if the client expressed dissatisfaction or described an inconvenience, reacted to the specific problem."), "yes_no"),
    Standard("06", ("Оцените ясность, порядок ответов и предупреждение об ожидании по шкале.",
                    "Rate clarity, the order of replies and the warning about waiting on the scale."), "scale"),
    Standard("07", ("Да — оператор подвёл итог или предложил дальнейшую помощь и попрощался.",
                    "Yes — the operator summarized or offered further help and said goodbye."), "yes_no"),
    Standard("08", ("Да — выявлено оскорбление клиента, предложение платной услуги в обход компании или раскрытие конфиденциальной информации.",
                    "Yes — an insult to the client, an offer of a paid service bypassing the company, or disclosure of confidential information was found."), "yes_no", is_flag=True),
)

# The general rules printed in the checklist PDF. The built-in logic already encodes them,
# and repeating them in every narrow question lowered agreement with our labels (80% -> 76%),
# so only rules that differ from these are added to the narrow questions.
STANDARD_GUIDELINES: tuple[str, ...] = (
    "«Нет» — действие было нужно, но оператор его пропустил или выполнил неправильно. N/A — критерий неприменим по условию.",
    "Общий вопрос о тарифах не требует идентификации. Если требовалась проверка личности перед защищённым действием и она не подтверждена в чате — «Нет».",
    "Для пропущенного действия укажите место, где оно ожидалось. Для N/A объясните, какое условие выполнено.",
    "Реплики бота и системные события — контекст, оценивается только оператор.",
    "Теги и вложения в оценку не входят.",
)

NOISE = re.compile(r"[\W\d_]+", re.UNICODE)


def _normalize(text: str) -> str:
    """Remove only what does not change the meaning of a rule."""
    text = text.casefold().replace("ё", "е")
    # A sentence that only describes the negative answer ("Нет — ни одно из трёх не выявлено.").
    text = re.sub(r"(^|[.;]\s*)(нет|no|жоқ)\s*[—–-][^.;]*[.;]?", " ", text)
    # The leading answer label ("Да —", "Yes —", "Иә —").
    text = re.sub(r"^\s*(да|yes|иә)\s*[—–-]\s*", "", text)
    # "... по шкале на стр. 2" / "on the scale": the scale itself is checked separately.
    text = re.sub(r"\b(по шкале|on the scale)\b.*$", "", text)
    return NOISE.sub(" ", text).strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b), autojunk=False).ratio()


def extra_guidelines(guidelines: list[str]) -> list[str]:
    """Rules the user added or reworded, i.e. those not among the standard ones."""
    standard = {_normalize(rule) for rule in STANDARD_GUIDELINES}
    return [rule for rule in guidelines if _normalize(rule) not in standard]


def match_standard(
    rule: str, answer_type: str, is_flag: bool, scale_values: list[int] | None
) -> str | None:
    """Return the preset ID ("01"…"08") that this criterion still is, or None.

    Only the standard wording itself keeps the built-in logic. Character similarity cannot tell a
    harmless variant from an edit that changes the meaning ("подтверждена" vs "не подтверждена"
    is 0.98 similar), so any other wording goes to the generic evaluator and the edit takes effect.
    """
    wanted = _normalize(rule)
    for standard in STANDARDS:
        if standard.answer_type != answer_type or standard.is_flag != is_flag:
            continue
        if standard.answer_type == "scale":
            levels = set(BY_ID[standard.preset_id].levels)
            if not scale_values or set(scale_values) != levels:
                continue
        if any(_normalize(text) == wanted for text in standard.rules):
            return standard.preset_id
    return None
