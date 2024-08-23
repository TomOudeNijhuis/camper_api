"""cascade 2

Revision ID: 267a59f70073
Revises: cc539da76949
Create Date: 2024-08-23 21:02:26.241130

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '267a59f70073'
down_revision: Union[str, None] = 'cc539da76949'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
