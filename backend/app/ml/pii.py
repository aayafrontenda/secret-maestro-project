"""Mask personal data before a transcript leaves the machine (cloud LLM providers)."""

import re
from collections import Counter

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IBAN = re.compile(r"\bKZ\d{2}[0-9A-Z]{13,16}\b", re.I)
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
IIN = re.compile(r"(?<!\d)\d{12}(?!\d)")
PHONE = re.compile(
    r"(?<![\w+])(?:\+7|8)[\s(-]*7\d{2}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)"
    r"|(?<![\w+])\+\d{1,3}[\s(-]*\d{2,4}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)"
)


def _card(m: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    return "[CARD]" if 13 <= len(digits) <= 19 else m.group(0)


def mask(text: str, counter: Counter[str] | None = None) -> str:
    """Replace e-mails, IBANs, card numbers, IINs and phone numbers with placeholders."""

    def sub(pattern: re.Pattern[str], repl, s: str, kind: str) -> str:
        def fn(m: re.Match[str]) -> str:
            out = repl(m) if callable(repl) else repl
            if counter is not None and out != m.group(0):
                counter[kind] += 1
            return out

        return pattern.sub(fn, s)

    text = sub(EMAIL, "[EMAIL]", text, "email")
    text = sub(IBAN, "[IBAN]", text, "iban")
    text = sub(CARD, _card, text, "card")
    text = sub(IIN, "[IIN]", text, "iin")
    text = sub(PHONE, "[PHONE]", text, "phone")
    return text
