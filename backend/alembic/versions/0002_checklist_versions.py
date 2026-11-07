"""checklist versions

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07 15:16:10.349075

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "checklist_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("checklist_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["checklist_id"], ["checklists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checklist_id", "version", name="uq_checklist_versions"),
    )
    with op.batch_alter_table("checklist_versions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_checklist_versions_checklist_id"), ["checklist_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("checklist_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_checklist_versions_checklist_id"))

    op.drop_table("checklist_versions")
