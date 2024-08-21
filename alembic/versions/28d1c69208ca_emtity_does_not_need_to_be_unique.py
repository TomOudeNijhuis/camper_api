"""emtity does not need to be unique

Revision ID: 28d1c69208ca
Revises: 2b6d91946bdc
Create Date: 2024-08-21 22:03:19.732211

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28d1c69208ca'
down_revision: Union[str, None] = '2b6d91946bdc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
