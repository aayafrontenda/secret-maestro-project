from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models._mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.evaluation import Evaluation


class Dialog(TimestampMixin, Base):
    """A conversation transcript (chat or voice call) to be evaluated."""

    __tablename__ = "dialogs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # organizer conversation_id
    dataset_group_id: Mapped[str | None] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(32), index=True)  # "agent chat" | "voice call"
    language: Mapped[str] = mapped_column(String(8), index=True)  # RU | KZ | EN
    # [{"index": 0, "timestamp": "00:02", "speaker": "operator", "text": "..."}, ...]
    transcript: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audio_url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="manual")  # organizer_api|file|manual
    # Bot -> operator handoff analysis (app/services/handoff.py) and who produced it.
    handoff: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    handoff_source: Mapped[str | None] = mapped_column(String(16))  # heuristic | llm

    evaluations: Mapped[list["Evaluation"]] = relationship(
        back_populates="dialog", cascade="all, delete-orphan", passive_deletes=True
    )
