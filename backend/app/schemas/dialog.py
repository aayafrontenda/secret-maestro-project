from pydantic import BaseModel, Field, field_validator

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
