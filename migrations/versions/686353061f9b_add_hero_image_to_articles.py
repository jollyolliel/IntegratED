"""add hero_image to articles

Revision ID: 686353061f9b
Revises: d7b1e4a9c2f6
Create Date: 2026-10-25 15:16:24.876203

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '686353061f9b'
down_revision = 'd7b1e4a9c2f6'
branch_labels = None
depends_on = None


def upgrade():
    # A database built by db.create_all() already has the column.
    if "hero_image" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("articles")}:
        return
    with op.batch_alter_table('articles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hero_image', sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table('articles', schema=None) as batch_op:
        batch_op.drop_column('hero_image')
