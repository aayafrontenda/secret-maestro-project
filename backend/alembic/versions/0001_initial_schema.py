"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-07 14:08:43.371788

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "checklists",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("checklists", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_checklists_is_default"), ["is_default"], unique=False)

    op.create_table(
        "dialogs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("dataset_group_id", sa.String(length=64), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("transcript", sa.JSON(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("audio_url", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("dialogs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_dialogs_channel"), ["channel"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_dialogs_dataset_group_id"), ["dataset_group_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_dialogs_language"), ["language"], unique=False)

    op.create_table(
        "criteria",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("checklist_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("section", sa.String(length=200), nullable=True),
        sa.Column("answer_type", sa.String(length=16), nullable=False),
        sa.Column("scale_max", sa.Integer(), nullable=True),
        sa.Column("scale_steps", sa.JSON(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("allow_na", sa.Boolean(), nullable=False),
        sa.Column("na_rule", sa.Text(), nullable=True),
        sa.Column("is_flag", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["checklist_id"], ["checklists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checklist_id", "code", name="uq_criteria_checklist_code"),
    )
    with op.batch_alter_table("criteria", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_criteria_checklist_id"), ["checklist_id"], unique=False
        )

    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dialog_id", sa.String(length=64), nullable=False),
        sa.Column("checklist_id", sa.Integer(), nullable=True),
        sa.Column("checklist_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "completed",
                "failed",
                name="evaluationstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("batch_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("original_total", sa.Float(), nullable=True),
        sa.Column("original_sections", sa.JSON(), nullable=True),
        sa.Column("grave_error", sa.Boolean(), nullable=False),
        sa.Column("final_total", sa.Float(), nullable=True),
        sa.Column("final_sections", sa.JSON(), nullable=True),
        sa.Column("final_grave_error", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["checklist_id"], ["checklists.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dialog_id"], ["dialogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("evaluations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_evaluations_batch_id"), ["batch_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_evaluations_checklist_id"), ["checklist_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_evaluations_dialog_id"), ["dialog_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_evaluations_status"), ["status"], unique=False)

    op.create_table(
        "criterion_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=False),
        sa.Column("criterion_code", sa.String(length=32), nullable=False),
        sa.Column("criterion_title", sa.String(length=200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=200), nullable=True),
        sa.Column("answer_type", sa.String(length=16), nullable=False),
        sa.Column("is_flag", sa.Boolean(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("answer", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("effective_weight", sa.Float(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("checked_range", sa.JSON(), nullable=True),
        sa.Column("na_reason", sa.Text(), nullable=True),
        sa.Column("normalization_note", sa.Text(), nullable=True),
        sa.Column("final_answer", sa.JSON(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("final_effective_weight", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["evaluation_id"], ["evaluations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("criterion_results", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_criterion_results_evaluation_id"), ["evaluation_id"], unique=False
        )

    op.create_table(
        "appeals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=False),
        sa.Column("criterion_result_id", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "confirmed", "changed", name="appealstatus", native_enum=False, length=16
            ),
            nullable=False,
        ),
        sa.Column("previous_answer", sa.JSON(), nullable=False),
        sa.Column("new_answer", sa.JSON(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["criterion_result_id"], ["criterion_results.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["evaluation_id"], ["evaluations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("appeals", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_appeals_criterion_result_id"), ["criterion_result_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_appeals_evaluation_id"), ["evaluation_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_appeals_status"), ["status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("appeals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_appeals_status"))
        batch_op.drop_index(batch_op.f("ix_appeals_evaluation_id"))
        batch_op.drop_index(batch_op.f("ix_appeals_criterion_result_id"))

    op.drop_table("appeals")
    with op.batch_alter_table("criterion_results", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_criterion_results_evaluation_id"))

    op.drop_table("criterion_results")
    with op.batch_alter_table("evaluations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_evaluations_status"))
        batch_op.drop_index(batch_op.f("ix_evaluations_dialog_id"))
        batch_op.drop_index(batch_op.f("ix_evaluations_checklist_id"))
        batch_op.drop_index(batch_op.f("ix_evaluations_batch_id"))

    op.drop_table("evaluations")
    with op.batch_alter_table("criteria", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_criteria_checklist_id"))

    op.drop_table("criteria")
    with op.batch_alter_table("dialogs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_dialogs_language"))
        batch_op.drop_index(batch_op.f("ix_dialogs_dataset_group_id"))
        batch_op.drop_index(batch_op.f("ix_dialogs_channel"))

    op.drop_table("dialogs")
    with op.batch_alter_table("checklists", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_checklists_is_default"))

    op.drop_table("checklists")
