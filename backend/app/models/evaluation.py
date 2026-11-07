import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models._mixins import TimestampMixin, UTCDateTime

if TYPE_CHECKING:
    from app.models.appeal import Appeal
    from app.models.checklist import Checklist
    from app.models.dialog import Dialog


class EvaluationStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Evaluation(TimestampMixin, Base):
    """One run of a checklist against one dialog."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dialog_id: Mapped[str] = mapped_column(
        ForeignKey("dialogs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    checklist_id: Mapped[int | None] = mapped_column(
        ForeignKey("checklists.id", ondelete="SET NULL"), index=True
    )
    # Immutable copy of the checklist as it was when the evaluation ran.
    checklist_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    status: Mapped[EvaluationStatus] = mapped_column(
        Enum(EvaluationStatus, native_enum=False, length=16),
        default=EvaluationStatus.queued,
        nullable=False,
        index=True,
    )
    error: Mapped[str | None] = mapped_column(Text)
    batch_id: Mapped[str | None] = mapped_column(String(36), index=True)

    provider: Mapped[str | None] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(128))
    # {"prompt_tokens": int, "completion_tokens": int, "cost_usd": float, "calls": int}
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Scores as produced by the model.
    original_total: Mapped[float | None] = mapped_column(Float)
    original_sections: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    grave_error: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Scores after reviewer decisions on appeals (equal to original until a decision changes them).
    final_total: Mapped[float | None] = mapped_column(Float)
    final_sections: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    final_grave_error: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # A supervisor looked at the verdict and closed it (also set when the last appeal is decided).
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    review_note: Mapped[str | None] = mapped_column(Text)

    dialog: Mapped["Dialog"] = relationship(back_populates="evaluations")
    checklist: Mapped["Checklist | None"] = relationship(back_populates="evaluations")
    results: Mapped[list["CriterionResult"]] = relationship(
        back_populates="evaluation",
        cascade="all, delete-orphan",
        order_by="CriterionResult.position",
        passive_deletes=True,
    )
    appeals: Mapped[list["Appeal"]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan", passive_deletes=True
    )


class CriterionResult(Base):
    """The model's verdict for one criterion, plus the reviewer-adjusted final verdict."""

    __tablename__ = "criterion_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    criterion_code: Mapped[str] = mapped_column(String(32), nullable=False)
    criterion_title: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section: Mapped[str | None] = mapped_column(String(200))
    answer_type: Mapped[str] = mapped_column(String(16), nullable=False)
    is_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # "yes" | "no" | "na" | number (for scale criteria). Stored as JSON scalar.
    answer: Mapped[Any] = mapped_column(JSON, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)  # points after N/A redistribution
    effective_weight: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # [{"message_index": 3, "timestamp": "...", "speaker": "...", "text": "..."}]
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # Range of the transcript inspected when an expected action is missing.
    checked_range: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    na_reason: Mapped[str | None] = mapped_column(Text)
    # Set when the backend had to coerce an invalid model answer (e.g. N/A where not allowed).
    normalization_note: Mapped[str | None] = mapped_column(Text)
    # Cascade check from the ML service: {"agrees", "needs_review", "second_answer", "second_model"}.
    review: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    final_answer: Mapped[Any] = mapped_column(JSON, nullable=False)
    final_score: Mapped[float | None] = mapped_column(Float)
    final_effective_weight: Mapped[float | None] = mapped_column(Float)

    evaluation: Mapped[Evaluation] = relationship(back_populates="results")
    appeals: Mapped[list["Appeal"]] = relationship(
        back_populates="criterion_result", order_by="Appeal.created_at"
    )
