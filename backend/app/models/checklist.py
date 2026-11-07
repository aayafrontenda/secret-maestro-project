from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models._mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.evaluation import Evaluation


class Checklist(TimestampMixin, Base):
    """An evaluation configuration: an ordered set of weighted criteria."""

    __tablename__ = "checklists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    # Incremented on every update; evaluations record the version they used.
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    criteria: Mapped[list["Criterion"]] = relationship(
        back_populates="checklist",
        cascade="all, delete-orphan",
        order_by="Criterion.position",
        passive_deletes=True,
    )
    evaluations: Mapped[list["Evaluation"]] = relationship(back_populates="checklist")


class Criterion(Base):
    __tablename__ = "criteria"
    __table_args__ = (UniqueConstraint("checklist_id", "code", name="uq_criteria_checklist_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    checklist_id: Mapped[int] = mapped_column(
        ForeignKey("checklists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stable key within the checklist, used in the ML contract (e.g. "c1").
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Human-readable rule the model follows ("Yes — operator greeted in the client's language...").
    rule: Mapped[str] = mapped_column(Text, nullable=False, default="")
    section: Mapped[str | None] = mapped_column(String(200))
    answer_type: Mapped[str] = mapped_column(String(16), nullable=False)  # yes_no | scale
    scale_max: Mapped[int | None] = mapped_column(Integer)
    # Optional discrete steps for scale criteria: [{"value": 20, "label": "..."}, ...]
    scale_steps: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    allow_na: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    na_rule: Mapped[str | None] = mapped_column(Text)
    # Flag-only criterion (e.g. "grave errors"): no points, reported separately.
    is_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    checklist: Mapped[Checklist] = relationship(back_populates="criteria")
