"""review marks on evaluations, decision author on appeals

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-07 20:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("evaluations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("reviewed_by", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("review_note", sa.Text(), nullable=True))
    with op.batch_alter_table("appeals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("decided_by", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("appeals", schema=None) as batch_op:
        batch_op.drop_column("decided_by")
    with op.batch_alter_table("evaluations", schema=None) as batch_op:
        batch_op.drop_column("review_note")
        batch_op.drop_column("reviewed_by")
        batch_op.drop_column("reviewed_at")
