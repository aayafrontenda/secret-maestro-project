"""User-facing rationale text in Russian, Kazakh and English, built from rule outcomes.

The Kazakh strings should be reviewed by a native speaker.
"""

from __future__ import annotations

from typing import Literal

from .checklist import BY_ID

Language = Literal["ru", "kk", "en"]
LANGUAGES: tuple[Language, ...] = ("ru", "kk", "en")

TEXTS: dict[Language, dict[str, str]] = {
    "ru": {
        "yes": "да",
        "no": "нет",
        "greeted": "поздоровался в первом ответе",
        "introduced": "представился в первом ответе",
        "client_language_used": "ответил на языке клиента",
        "enough_info_from_start": "данных хватало с самого начала",
        "used_known_details": "учёл известные детали",
        "clarified_missing": "уточнил недостающее до ответа",
        "identification_required": "требовалась идентификация",
        "identity_confirmed_first": "личность подтверждена до раскрытия данных или действия",
        "request_formulated": "клиент сформулировал запрос",
        "polite": "оператор вежлив",
        "client_complained": "клиент выразил недовольство",
        "reacted_to_problem": "оператор отреагировал на конкретную проблему",
        "chat_cut_off": "чат оборвался",
        "summarized": "подвёл итог",
        "offered_help": "предложил дальнейшую помощь",
        "said_goodbye": "попрощался",
        "insult": "оскорбление клиента",
        "off_company_offer": "предложение платной услуги в обход компании",
        "confidential_disclosure": "раскрытие конфиденциальной информации",
        "na_02": "Данных для ответа хватало с самого начала.",
        "na_03": "Запрос не требовал идентификации.",
        "na_04": "Чат закончился до того, как клиент сформулировал запрос.",
        "na_07": "Чат оборвался до возможности его завершить.",
        "gross_found": "Выявлено",
        "gross_none": "Оскорблений, предложений услуг в обход компании и раскрытия конфиденциальной информации не выявлено.",
        "level": "Ступень {level} из {top}",
        "failed": "Критерий не оценён: модель не дала корректного ответа.",
        "04_20": "все существенные вопросы закрыты или дан корректный следующий шаг.",
        "04_15": "основной вопрос решён, пропущена второстепенная деталь.",
        "04_10": "часть запроса закрыта, существенный вопрос остался открытым.",
        "04_5": "есть общая подсказка, но клиенту всё ещё непонятно, как действовать.",
        "04_0": "ответа по существу нет или ключевая рекомендация ошибочна.",
        "06_10": "ответы ясные и связные; при явном ожидании оператор предупредил.",
        "06_7": "один заметный сбой, но клиент может понять ответ и продолжить.",
        "06_4": "клиенту приходится переспрашивать из-за формулировок или порядка ответов.",
        "06_0": "из-за бессвязных или противоречивых реплик ход диалога непонятен.",
    },
    "kk": {
        "yes": "иә",
        "no": "жоқ",
        "greeted": "бірінші жауапта амандасты",
        "introduced": "бірінші жауапта өзін таныстырды",
        "client_language_used": "клиенттің тілінде жауап берді",
        "enough_info_from_start": "деректер басынан-ақ жеткілікті болды",
        "used_known_details": "белгілі мәліметтерді ескерді",
        "clarified_missing": "жауап бермес бұрын жетіспейтін мәліметті нақтылады",
        "identification_required": "сәйкестендіру қажет болды",
        "identity_confirmed_first": "деректерді ашпас немесе әрекет жасамас бұрын жеке басы расталды",
        "request_formulated": "клиент сұрауын тұжырымдады",
        "polite": "оператор сыпайы болды",
        "client_complained": "клиент наразылық білдірді",
        "reacted_to_problem": "оператор нақты мәселеге назар аударды",
        "chat_cut_off": "чат үзілді",
        "summarized": "қорытынды жасады",
        "offered_help": "қосымша көмек ұсынды",
        "said_goodbye": "қоштасты",
        "insult": "клиентті қорлау",
        "off_company_offer": "компанияны айналып өтіп ақылы қызмет ұсыну",
        "confidential_disclosure": "құпия ақпаратты жария ету",
        "na_02": "Жауап беру үшін деректер басынан-ақ жеткілікті болды.",
        "na_03": "Сұрау сәйкестендіруді талап етпеді.",
        "na_04": "Клиент сұрауын тұжырымдағанға дейін чат аяқталды.",
        "na_07": "Чат оны аяқтау мүмкіндігі болғанға дейін үзілді.",
        "gross_found": "Анықталды",
        "gross_none": "Қорлау, компанияны айналып өтіп қызмет ұсыну және құпия ақпаратты жария ету анықталған жоқ.",
        "level": "{top} ішінен {level} деңгейі",
        "failed": "Критерий бағаланбады: модель дұрыс жауап бермеді.",
        "04_20": "барлық маңызды сұрақтар жабылды немесе дұрыс келесі қадам берілді.",
        "04_15": "негізгі сұрақ шешілді, қосымша бөлшек өткізіліп кетті.",
        "04_10": "сұраудың бір бөлігі жабылды, маңызды сұрақ ашық қалды.",
        "04_5": "жалпы кеңес бар, бірақ клиентке әлі де қалай әрекет ету керегі түсініксіз.",
        "04_0": "мәні бойынша жауап жоқ немесе негізгі ұсыныс қате.",
        "06_10": "жауаптар анық және байланысты; айқын күту болса, оператор ескертті.",
        "06_7": "бір байқалатын іркіліс бар, бірақ клиент жауапты түсініп, жалғастыра алады.",
        "06_4": "тұжырымдар немесе жауаптардың реті салдарынан клиент қайта сұрауға мәжбүр.",
        "06_0": "байланыссыз немесе қайшы репликалар салдарынан диалогтың барысы түсініксіз.",
    },
    "en": {
        "yes": "yes",
        "no": "no",
        "greeted": "greeted in the first reply",
        "introduced": "introduced themselves in the first reply",
        "client_language_used": "replied in the client's language",
        "enough_info_from_start": "enough information from the start",
        "used_known_details": "took known details into account",
        "clarified_missing": "clarified missing details before answering",
        "identification_required": "identification was required",
        "identity_confirmed_first": "identity confirmed before disclosure or action",
        "request_formulated": "the client stated a request",
        "polite": "the operator was polite",
        "client_complained": "the client expressed dissatisfaction",
        "reacted_to_problem": "the operator reacted to the specific problem",
        "chat_cut_off": "the chat was cut off",
        "summarized": "summarized the outcome",
        "offered_help": "offered further help",
        "said_goodbye": "said goodbye",
        "insult": "insulting the client",
        "off_company_offer": "offering a paid service outside the company",
        "confidential_disclosure": "disclosing confidential information",
        "na_02": "The information needed to answer was available from the start.",
        "na_03": "The request did not require identification.",
        "na_04": "The chat ended before the client stated a request.",
        "na_07": "The chat was cut off before it could be closed.",
        "gross_found": "Found",
        "gross_none": "No insults, off-company offers or confidential disclosures were found.",
        "level": "Level {level} of {top}",
        "failed": "Not scored: the model did not return a valid answer.",
        "04_20": "all material questions are closed or a correct next step is given.",
        "04_15": "the main question is resolved, a secondary detail is missing.",
        "04_10": "part of the request is closed, a material question remains open.",
        "04_5": "there is a general hint, but the client still does not know how to act.",
        "04_0": "there is no answer on substance, or the key recommendation is wrong.",
        "06_10": "replies are clear and coherent; the operator warned about any explicit wait.",
        "06_7": "one noticeable lapse, but the client can understand the reply and continue.",
        "06_4": "the client has to ask again because of the wording or the order of replies.",
        "06_0": "incoherent or contradictory replies make the dialogue impossible to follow.",
    },
}

GROSS_KEYS = ("insult", "off_company_offer", "confidential_disclosure")


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def rationale(criterion_id: str, answer: object, facts: dict[str, bool], na_reason: str | None, language: Language) -> str:
    t = TEXTS[language]
    if na_reason:
        return t[na_reason]
    if criterion_id == "08":
        found = [t[key] for key in GROSS_KEYS if facts.get(key)]
        return f"{t['gross_found']}: {', '.join(found)}." if found else t["gross_none"]
    criterion = BY_ID[criterion_id]
    if criterion.is_scale:
        head = t["level"].format(level=answer, top=max(criterion.levels))
        return f"{head}: {t[f'{criterion_id}_{answer}']}"
    parts = [f"{t[key]}: {t['yes' if value else 'no']}" for key, value in facts.items()]
    return _capitalize("; ".join(parts)) + "."
