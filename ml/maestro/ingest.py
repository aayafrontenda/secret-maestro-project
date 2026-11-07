"""Convert raw chat files into canonical transcripts.

The real input format is not known yet, so these adapters accept common shapes and
fail loudly on anything they cannot map. Tags, attachments and other metadata are
dropped on purpose because the checklist does not score them.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .schemas import Message, Role, Transcript

ROLE_FIELDS = ("role", "sender", "author", "from", "speaker", "type", "роль", "отправитель", "автор")
TEXT_FIELDS = ("text", "message", "content", "body", "текст", "сообщение")
TIME_FIELDS = ("timestamp", "time", "created_at", "date", "datetime", "время", "дата")
CHAT_ID_FIELDS = ("chat_id", "dialog_id", "conversation_id", "id_chat", "transcript_id")
ATTACHMENT_FIELDS = ("attachments", "attachment", "files", "file", "вложения", "вложение")
MESSAGE_LIST_FIELDS = ("messages", "dialog", "dialogue", "conversation", "chat", "transcript", "сообщения")

ROLE_SYNONYMS: dict[str, Role] = {
    **dict.fromkeys(("client", "customer", "user", "клиент", "пользователь", "тұтынушы", "клиенты"), Role.CLIENT),
    **dict.fromkeys(
        ("operator", "agent", "support", "manager", "specialist", "оператор", "агент", "менеджер",
         "специалист", "поддержка", "маман"),
        Role.OPERATOR,
    ),
    **dict.fromkeys(("system", "система", "системное", "жүйе"), Role.SYSTEM),
    **dict.fromkeys(("bot", "бот", "assistant"), Role.BOT),
}

ATTACHMENT_PLACEHOLDER = "[attachment]"
TIME_FORMATS = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%H:%M:%S")
# Chats from the organizers use "MM:SS" offsets from the start of the chat.
CHAT_OFFSET = re.compile(r"^(\d{1,3}):([0-5]\d)$")
CHAT_START = datetime(2000, 1, 1)
TXT_LINE = re.compile(
    r"^\s*(?:\[?(?P<time>\d[\d:.\-T /]*\d)\]?\s*[-–|]?\s*)?\[?(?P<role>[^\]:\d][^\]:]{0,29})\]?\s*:\s*(?P<text>.*)$"
)


class IngestError(ValueError):
    pass


def _first(record: dict[str, Any], fields: Iterable[str]) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in record.items()}
    for field in fields:
        value = lowered.get(field)
        if value not in (None, ""):
            return value
    return None


def parse_role(value: Any) -> Role:
    key = str(value).strip().lower()
    if key in ROLE_SYNONYMS:
        return ROLE_SYNONYMS[key]
    raise IngestError(f"unknown message role: {value!r}")


def parse_time(value: Any) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    offset = CHAT_OFFSET.match(text)
    if offset:
        return CHAT_START + timedelta(minutes=int(offset[1]), seconds=int(offset[2]))
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _build(chat_id: str, records: list[dict[str, Any]]) -> Transcript:
    messages: list[Message] = []
    for record in records:
        role_value = _first(record, ROLE_FIELDS)
        if role_value is None:
            raise IngestError(f"chat {chat_id}: message without a role: {sorted(map(str, record))}")
        text = _first(record, TEXT_FIELDS)
        text = "" if text is None else str(text).strip()
        if _first(record, ATTACHMENT_FIELDS):
            text = f"{text} {ATTACHMENT_PLACEHOLDER}".strip()
        if not text:
            continue
        time_value = _first(record, TIME_FIELDS)
        messages.append(
            Message(
                id=f"M{len(messages) + 1}",
                role=parse_role(role_value),
                text=text,
                timestamp=parse_time(time_value),
                time_text=str(time_value).strip() if time_value is not None else None,
            )
        )
    if not messages:
        raise IngestError(f"chat {chat_id}: no messages found")
    return Transcript(chat_id=chat_id, messages=messages)


def _group_rows(default_id: str, rows: list[dict[str, Any]]) -> list[Transcript]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        chat_id = _first(row, CHAT_ID_FIELDS)
        groups.setdefault(str(chat_id) if chat_id is not None else default_id, []).append(row)
    return [_build(chat_id, records) for chat_id, records in groups.items()]


def parse_json_object(data: Any, default_id: str = "chat") -> list[Transcript]:
    """Accept one chat, a list of chats or a flat list of messages."""
    if isinstance(data, dict):
        messages = _first(data, MESSAGE_LIST_FIELDS)
        if isinstance(messages, list):
            chat_id = _first(data, CHAT_ID_FIELDS) or data.get("id") or default_id
            return [_build(str(chat_id), messages)]
        for wrapper in ("chats", "dialogs", "conversations", "transcripts", "data"):
            if isinstance(data.get(wrapper), list):
                return parse_json_object(data[wrapper], default_id)
        raise IngestError("JSON object has no message list")
    if isinstance(data, list) and data and all(isinstance(item, dict) for item in data):
        if _first(data[0], MESSAGE_LIST_FIELDS) is not None:
            chats: list[Transcript] = []
            for index, item in enumerate(data, start=1):
                chats.extend(parse_json_object(item, f"{default_id}-{index}"))
            return chats
        return _group_rows(default_id, data)
    raise IngestError("unsupported JSON structure")


def parse_text(text: str, default_id: str = "chat") -> list[Transcript]:
    """Parse lines like '[12:01:05] Client: text'. Unmatched lines continue the previous message."""
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = TXT_LINE.match(line)
        if match and match["role"].strip().lower() in ROLE_SYNONYMS:
            records.append({"role": match["role"], "text": match["text"], "time": match["time"]})
        elif records:
            records[-1]["text"] = f"{records[-1]['text']}\n{line.strip()}"
        else:
            raise IngestError(f"cannot parse line: {line[:80]!r}")
    return [_build(default_id, records)]


def _parse_csv(text: str, default_id: str) -> list[Transcript]:
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return _group_rows(default_id, list(csv.DictReader(io.StringIO(text), dialect=dialect)))


def _parse_xlsx(data: bytes, default_id: str) -> list[Transcript]:
    from openpyxl import load_workbook

    sheet = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
    rows = sheet.iter_rows(values_only=True)
    header = [str(cell).strip() if cell is not None else "" for cell in next(rows, ())]
    if not any(header):
        raise IngestError("spreadsheet has no header row")
    return _group_rows(default_id, [dict(zip(header, row)) for row in rows if any(row)])


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestError("cannot decode the file as UTF-8 or CP1251")


def parse_bytes(filename: str, data: bytes) -> list[Transcript]:
    stem = Path(filename).stem or "chat"
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        try:
            return parse_json_object(json.loads(_decode(data)), stem)
        except json.JSONDecodeError as exc:
            raise IngestError(f"invalid JSON: {exc}") from exc
    if suffix == ".csv":
        return _parse_csv(_decode(data), stem)
    if suffix == ".xlsx":
        return _parse_xlsx(data, stem)
    if suffix in (".txt", ".log", ""):
        return parse_text(_decode(data), stem)
    raise IngestError(f"unsupported file type: {suffix}")


def parse_file(path: str | Path) -> list[Transcript]:
    path = Path(path)
    return parse_bytes(path.name, path.read_bytes())
