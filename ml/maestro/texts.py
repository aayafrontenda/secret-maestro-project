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
        "verification_asked": "оператор запросил проверку личности",
        "account_info_disclosed": "данные счёта раскрыты без проверки",
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
        "verification_asked": "оператор жеке басын растауды сұрады",
        "account_info_disclosed": "шот деректері растаусыз ашылды",
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
        "verification_asked": "the operator asked for identity verification",
        "account_info_disclosed": "account data disclosed without verification",
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

# Rationales follow the checklist's own example: "Завершение — Нет. После ответа на вопрос оператор закрыл чат
# без прощания. Основание — последняя реплика оператора и сообщение о закрытии чата." The verdict and its
# reason come from here; the contract adds the basis, since only it knows whose messages the evidence is.
TITLES: dict[Language, dict[str, str]] = {
    "ru": {"01": "Установление контакта", "02": "Выявление потребности", "03": "Идентификация",
           "04": "Корректная и полная консультация", "05": "Эмпатия и клиентоориентированность",
           "06": "Управление диалогом", "07": "Завершение", "08": "Грубые ошибки"},
    "kk": {"01": "Байланыс орнату", "02": "Қажеттілікті анықтау", "03": "Сәйкестендіру",
           "04": "Дұрыс әрі толық кеңес", "05": "Эмпатия және клиентке бағдарлану",
           "06": "Диалогты басқару", "07": "Аяқтау", "08": "Өрескел қателер"},
    "en": {"01": "Establishing contact", "02": "Needs discovery", "03": "Identification",
           "04": "Correct and complete consultation", "05": "Empathy and customer focus",
           "06": "Dialogue management", "07": "Closing", "08": "Gross errors"},
}
VERDICT: dict[Language, dict[str, str]] = {
    "ru": {"yes": "Да", "no": "Нет", "na": "N/A", "scale": "{a} из {top}"},
    "kk": {"yes": "Иә", "no": "Жоқ", "na": "N/A", "scale": "{top} ішінен {a}"},
    "en": {"yes": "Yes", "no": "No", "na": "N/A", "scale": "{a} of {top}"},
}
JOIN: dict[Language, tuple[str, str]] = {"ru": (" и ", ", но "), "kk": (" және ", ", бірақ "), "en": (" and ", ", but ")}

# Operator actions as (done, not done) phrases, with the sentence they go into.
CLAUSES: dict[Language, dict[str, tuple[str, dict[str, tuple[str, str]]]]] = {
    "ru": {
        "01": ("В первом ответе оператор {}.", {
            "greeted": ("поздоровался", "не поздоровался"),
            "introduced": ("представился", "не представился"),
            "client_language_used": ("ответил на языке клиента", "ответил не на языке клиента")}),
        "07": ("Оператор {}.", {
            "summarized": ("подвёл итог", "не подвёл итог"),
            "offered_help": ("предложил дальнейшую помощь", "не предложил дальнейшую помощь"),
            "said_goodbye": ("попрощался", "не попрощался")}),
    },
    "kk": {
        "01": ("Бірінші жауабында оператор {}.", {
            "greeted": ("амандасты", "амандаспады"),
            "introduced": ("өзін таныстырды", "өзін таныстырмады"),
            "client_language_used": ("клиенттің тілінде жауап берді", "клиенттің тілінде жауап бермеді")}),
        "07": ("Оператор {}.", {
            "summarized": ("қорытынды жасады", "қорытынды жасамады"),
            "offered_help": ("қосымша көмек ұсынды", "қосымша көмек ұсынбады"),
            "said_goodbye": ("қоштасты", "қоштаспады")}),
    },
    "en": {
        "01": ("In the first reply the operator {}.", {
            "greeted": ("greeted the client", "did not greet the client"),
            "introduced": ("introduced themselves", "did not introduce themselves"),
            "client_language_used": ("replied in the client's language", "did not reply in the client's language")}),
        "07": ("The operator {}.", {
            "summarized": ("summarized the outcome", "did not summarize the outcome"),
            "offered_help": ("offered further help", "did not offer further help"),
            "said_goodbye": ("said goodbye", "did not say goodbye")}),
    },
}

# Whole sentences for criteria whose facts mix the client's and the operator's side.
SENTENCES: dict[Language, dict[str, str]] = {
    "ru": {
        "02_reasked": "Оператор переспросил то, что клиент уже сообщил.",
        "02_clarified": "Оператор уточнил недостающие детали до ответа.",
        "02_not_clarified": "Данных для ответа не хватало, но оператор ничего не уточнил.",
        "03_confirmed": "Личность клиента подтверждена до раскрытия данных или защищённого действия.",
        "03_asked": "Оператор запросил проверку личности и не раскрыл данные счёта до неё.",
        "03_disclosed": "Данные счёта раскрыты до подтверждения личности.",
        "03_skipped": "Требовалась проверка личности, но оператор её не провёл.",
        "05_ok_calm": "Оператор вежлив; клиент недовольства не выражал.",
        "05_ok_reacted": "Оператор вежлив и отреагировал на конкретную проблему, на которую пожаловался клиент.",
        "05_not_reacted": "Оператор вежлив, но не отреагировал на конкретную проблему, на которую пожаловался клиент.",
        "05_impolite": "Оператор был невежлив.",
        "05_impolite_not_reacted": "Оператор был невежлив и не отреагировал на проблему, на которую пожаловался клиент.",
        "basis": "Основание — {}.",
        "checked": "Проверен участок {}.",
        "operator": "реплика оператора", "client": "реплика клиента", "system": "системное сообщение", "bot": "реплика бота",
        "operator+": "реплики оператора", "client+": "реплики клиента", "system+": "системные сообщения", "bot+": "реплики бота",
    },
    "kk": {
        "02_reasked": "Оператор клиент бұрын айтқан мәліметті қайта сұрады.",
        "02_clarified": "Оператор жауап бермес бұрын жетіспейтін мәліметті нақтылады.",
        "02_not_clarified": "Жауап беру үшін деректер жеткіліксіз болды, бірақ оператор ештеңе нақтыламады.",
        "03_confirmed": "Клиенттің жеке басы деректер ашылмас немесе қорғалған әрекет жасалмас бұрын расталды.",
        "03_asked": "Оператор жеке басын растауды сұрады және оған дейін шот деректерін ашпады.",
        "03_disclosed": "Шот деректері жеке басы расталмай тұрып ашылды.",
        "03_skipped": "Жеке басын тексеру қажет болды, бірақ оператор оны жүргізбеді.",
        "05_ok_calm": "Оператор сыпайы болды; клиент наразылық білдірмеді.",
        "05_ok_reacted": "Оператор сыпайы болды және клиент шағымданған нақты мәселеге назар аударды.",
        "05_not_reacted": "Оператор сыпайы болды, бірақ клиент шағымданған нақты мәселеге назар аудармады.",
        "05_impolite": "Оператор сыпайы болмады.",
        "05_impolite_not_reacted": "Оператор сыпайы болмады және клиент шағымданған мәселеге назар аудармады.",
        "basis": "Негіз — {}.",
        "checked": "Тексерілген бөлік: {}.",
        "operator": "оператор репликасы", "client": "клиент репликасы", "system": "жүйелік хабарлама", "bot": "бот репликасы",
        "operator+": "оператор репликалары", "client+": "клиент репликалары", "system+": "жүйелік хабарламалар", "bot+": "бот репликалары",
    },
    "en": {
        "02_reasked": "The operator asked again for something the client had already said.",
        "02_clarified": "The operator clarified the missing details before answering.",
        "02_not_clarified": "The information was not enough to answer, but the operator did not clarify anything.",
        "03_confirmed": "The client's identity was confirmed before any data was disclosed or a protected action taken.",
        "03_asked": "The operator asked for identity verification and disclosed nothing about the account before it.",
        "03_disclosed": "Account data was disclosed before the identity was confirmed.",
        "03_skipped": "Identity verification was required, but the operator did not carry it out.",
        "05_ok_calm": "The operator was polite; the client did not express dissatisfaction.",
        "05_ok_reacted": "The operator was polite and addressed the specific problem the client complained about.",
        "05_not_reacted": "The operator was polite but did not address the specific problem the client complained about.",
        "05_impolite": "The operator was impolite.",
        "05_impolite_not_reacted": "The operator was impolite and did not address the problem the client complained about.",
        "basis": "Basis — {}.",
        "checked": "Checked: {}.",
        "operator": "operator message", "client": "client message", "system": "system message", "bot": "bot message",
        "operator+": "operator messages", "client+": "client messages", "system+": "system messages", "bot+": "bot messages",
    },
}


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _join(items: list[str], language: Language) -> str:
    conj = JOIN[language][0]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + conj + items[-1]


def _clauses(criterion_id: str, answer: object, facts: dict[str, bool], language: Language) -> str:
    template, phrases = CLAUSES[language][criterion_id]
    done = [phrases[k][0] for k in phrases if facts.get(k)]
    missed = [phrases[k][1] for k in phrases if k in facts and not facts[k]]
    if answer == "yes" or not missed:
        return template.format(_join(done, language)) if done else ""
    body = _join(done, language) + JOIN[language][1] + _join(missed, language) if done else _join(missed, language)
    return template.format(body)


def _reason(criterion_id: str, answer: object, facts: dict[str, bool], language: Language) -> str:
    t, s = TEXTS[language], SENTENCES[language]
    if criterion_id in CLAUSES[language]:
        return _clauses(criterion_id, answer, facts, language)
    if criterion_id == "02":
        if facts.get("used_known_details") is False:
            return s["02_reasked"]
        return s["02_clarified"] if facts.get("clarified_missing") else s["02_not_clarified"]
    if criterion_id == "03":
        if answer == "yes":
            return s["03_confirmed"] if facts.get("identity_confirmed_first") else s["03_asked"]
        return s["03_disclosed"] if facts.get("account_info_disclosed") else s["03_skipped"]
    if criterion_id == "05":
        not_reacted = facts.get("client_complained") and facts.get("reacted_to_problem") is False
        if not facts.get("polite", True):
            return s["05_impolite_not_reacted"] if not_reacted else s["05_impolite"]
        if not_reacted:
            return s["05_not_reacted"]
        return s["05_ok_reacted"] if facts.get("client_complained") else s["05_ok_calm"]
    if criterion_id == "08":
        found = [t[key] for key in GROSS_KEYS if facts.get(key)]
        return f"{t['gross_found']}: {', '.join(found)}." if found else t["gross_none"]
    if criterion_id in ("04", "06"):
        return _capitalize(t[f"{criterion_id}_{answer}"])
    return ""


def rationale(criterion_id: str, answer: object, facts: dict[str, bool], na_reason: str | None, language: Language) -> str:
    """"<Criterion> — <verdict>. <Why>." in the checklist's own style; the basis is added by the caller."""
    t, v = TEXTS[language], VERDICT[language]
    title = TITLES[language][criterion_id]
    if na_reason:
        return f"{title} — {v['na']}. {t[na_reason]}"
    criterion = BY_ID[criterion_id]
    if criterion.is_scale:
        verdict = v["scale"].format(a=answer, top=max(criterion.levels))
    else:
        verdict = v["yes"] if answer == "yes" else v["no"]
    reason = _reason(criterion_id, answer, facts, language)
    return f"{title} — {verdict}. {reason}".strip()


def basis(evidence: list[tuple[int, str]], checked: tuple[int, int] | None, language: Language) -> str:
    """Which messages the verdict rests on, by role and number as the UI shows them (#1 is the first message)."""
    s = SENTENCES[language]
    parts = []
    by_role: dict[str, list[int]] = {}
    for n, role in sorted(set(evidence)):
        by_role.setdefault(role if role in ("operator", "client", "system", "bot") else "operator", []).append(n)
    if by_role:
        cited = [
            f"{s[role + '+'] if len(ns) > 1 else s[role]} {', '.join(f'#{n}' for n in ns)}"
            for role, ns in sorted(by_role.items(), key=lambda item: item[1][0])
        ]
        parts.append(s["basis"].format(", ".join(cited)))
    if checked is not None:
        a, b = checked
        # A single checked message that is already cited adds nothing.
        if not (a == b and any(n == a for n, _ in evidence)):
            parts.append(s["checked"].format(f"#{a}" if a == b else f"#{a}–#{b}"))
    return " ".join(parts)
