"""make more columns an index

Revision ID: 0938d1488e14
Revises: ba84349899ef
Create Date: 2025-06-29 11:24:25.258645

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0938d1488e14'
down_revision: Union[str, None] = 'ba84349899ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_index(op.f('ix_states_created'), 'states', ['created'], unique=False)
    op.create_index(op.f('ix_states_entity_id'), 'states', ['entity_id'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_states_entity_id'), table_name='states')
    op.drop_index(op.f('ix_states_created'), table_name='states')
    # ### end Alembic commands ###
