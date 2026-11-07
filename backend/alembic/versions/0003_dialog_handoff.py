"""dialog handoff analysis

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-07 18:40:00

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("dialogs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("handoff", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("handoff_source", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("dialogs", schema=None) as batch_op:
        batch_op.drop_column("handoff_source")
        batch_op.drop_column("handoff")
