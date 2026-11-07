from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel

# Known values; unknown ones are accepted after normalisation so an unexpected control
# dataset never fails to import.
CHANNELS = ("agent chat", "voice call")
LANGUAGES = ("RU", "KZ", "EN")
SPEAKERS = ("client", "operator", "bot", "system")

_SPEAKER_ALIASES = {
    "agent": "operator",
    "оператор": "operator",
    "customer": "client",
    "user": "client",
    "клиент": "client",
    "assistant": "bot",
    "бот": "bot",
    "system_event": "system",
    "система": "system",
}
_CHANNEL_ALIASES = {
    "chat": "agent chat",
    "agent_chat": "agent chat",
    "agentchat": "agent chat",
    "call": "voice call",
    "voice": "voice call",
    "voice_call": "voice call",
    "voicecall": "voice call",
}
_LANGUAGE_ALIASES = {"KK": "KZ", "KAZ": "KZ", "RUS": "RU", "ENG": "EN"}


def normalize_speaker(value: str) -> str:
    token = value.strip().lower()
    return _SPEAKER_ALIASES.get(token, token)


def normalize_channel(value: str) -> str:
    token = value.strip().lower()
    return _CHANNEL_ALIASES.get(token, token)


def normalize_language(value: str) -> str:
    token = value.strip().upper().replace("-", "_")
    token = token.split("_")[0] if token not in _LANGUAGE_ALIASES else token
    return _LANGUAGE_ALIASES.get(token, token)


class TranscriptMessageIn(BaseModel):
    timestamp: str = Field(description='"MM:SS" for chats, ISO 8601 with timezone for calls')
    speaker: str = Field(min_length=1, description="client | operator | bot | system")
    text: str = ""

    @field_validator("speaker", mode="before")
    @classmethod
    def _speaker(cls, v: str) -> str:
        return normalize_speaker(v) if isinstance(v, str) else v

    @field_validator("timestamp", mode="before")
    @classmethod
    def _timestamp(cls, v: object) -> str:
        return "" if v is None else str(v)


class TranscriptMessage(TranscriptMessageIn):
    index: int = Field(description="0-based position in the transcript; used as evidence reference")


class DialogIn(BaseModel):
    """One record in the organizer's format (also accepted for manual upload)."""

    conversation_id: str = Field(min_length=1, max_length=64)
    channel: str = Field(min_length=1, description='"agent chat" | "voice call"')
    language: str = Field(min_length=1, max_length=8, description="RU | KZ | EN")
    transcript: list[TranscriptMessageIn] = Field(min_length=1)
    audio_url: str | None = None

    @field_validator("channel", mode="before")
    @classmethod
    def _channel(cls, v: str) -> str:
        return normalize_channel(v) if isinstance(v, str) else v

    @field_validator("language", mode="before")
    @classmethod
    def _language(cls, v: str) -> str:
        return normalize_language(v) if isinstance(v, str) else v

    @field_validator("audio_url", mode="before")
    @classmethod
    def _audio(cls, v: object) -> str | None:
        return v or None


class DialogSummary(ORMModel):
    id: str
    dataset_group_id: str | None
    channel: str
    language: str
    message_count: int
    audio_url: str | None
    source: str
    created_at: datetime
    # Latest evaluation, if any.
    latest_evaluation: "EvaluationBrief | None" = None


class DialogDetail(DialogSummary):
    transcript: list[TranscriptMessage]
    evaluations: list["EvaluationBrief"] = []


class EvaluationBrief(ORMModel):
    id: int
    status: str
    checklist_id: int | None
    original_total: float | None
    final_total: float | None
    grave_error: bool
    final_grave_error: bool
    created_at: datetime
    completed_at: datetime | None


class ImportRequest(BaseModel):
    group_id: str = Field(default="DEV", min_length=1, max_length=64)


class ImportResult(BaseModel):
    dataset_group_id: str | None
    received: int
    created: int
    updated: int
    ids: list[str]


DialogSummary.model_rebuild()
DialogDetail.model_rebuild()
