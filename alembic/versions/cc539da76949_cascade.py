"""cascade

Revision ID: cc539da76949
Revises: 28d1c69208ca
Create Date: 2024-08-23 20:58:15.442791

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cc539da76949'
down_revision: Union[str, None] = '28d1c69208ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
