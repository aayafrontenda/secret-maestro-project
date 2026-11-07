import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models._mixins import TimestampMixin, UTCDateTime

if TYPE_CHECKING:
    from app.models.evaluation import CriterionResult, Evaluation


class AppealStatus(enum.StrEnum):
    pending = "pending"
    confirmed = "confirmed"  # reviewer kept the original verdict
    changed = "changed"  # reviewer replaced the verdict


class Appeal(TimestampMixin, Base):
    """A dispute raised against one criterion verdict, and the reviewer's decision on it."""

    __tablename__ = "appeals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    criterion_result_id: Mapped[int] = mapped_column(
        ForeignKey("criterion_results.id", ondelete="CASCADE"), nullable=False, index=True
    )
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AppealStatus] = mapped_column(
        Enum(AppealStatus, native_enum=False, length=16),
        default=AppealStatus.pending,
        nullable=False,
        index=True,
    )
    # Verdict before the appeal, kept for the audit trail.
    previous_answer: Mapped[Any] = mapped_column(JSON, nullable=False)
    new_answer: Mapped[Any | None] = mapped_column(JSON)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    decided_by: Mapped[str | None] = mapped_column(String(100))

    evaluation: Mapped["Evaluation"] = relationship(back_populates="appeals")
    criterion_result: Mapped["CriterionResult"] = relationship(back_populates="appeals")
