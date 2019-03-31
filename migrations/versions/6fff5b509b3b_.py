from sqlalchemy.dialects import mysql
import sqlalchemy as sa
from alembic import op
"""empty message

Revision ID: 6fff5b509b3b
Revises: b28b5677726e
Create Date: 2019-03-25 04:18:27.108207

"""

# revision identifiers, used by Alembic.
revision = '6fff5b509b3b'
down_revision = 'b28b5677726e'


def upgrade():
    op.create_table('seasons',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('user_id', sa.Integer(), nullable=True),
                    sa.Column('name', sa.String(length=32), nullable=False),
                    sa.Column('start_date', sa.DateTime(), nullable=True),
                    sa.Column('end_date', sa.DateTime(), nullable=True),
                    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
                    sa.PrimaryKeyConstraint('id')
                    )
    op.add_column('match', sa.Column('seasons_id', sa.Integer(), nullable=True))
    op.create_foreign_key('match_season_id_fkey', 'match',
                          'seasons', ['seasons_id'], ['id'])


def downgrade():
    op.drop_constraint(op.f('match_season_id_fkey'), table_name='match', type_='foreignkey')
    op.drop_column('match', 'seasons_id')
    op.drop_table('seasons')
