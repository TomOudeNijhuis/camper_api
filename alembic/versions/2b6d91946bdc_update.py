"""update

Revision ID: 2b6d91946bdc
Revises: 8815f3804b3e
Create Date: 2024-08-20 20:56:30.667089

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b6d91946bdc'
down_revision: Union[str, None] = '8815f3804b3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
