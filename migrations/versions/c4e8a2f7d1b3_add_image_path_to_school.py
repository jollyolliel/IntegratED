"""add image path to school

School photos were picked in templates by the school's name ("ACS Athens");
each school now names its own photo under static/. Backfill ACS Athens so it
keeps the photo it already showed.

Revision ID: c4e8a2f7d1b3
Revises: a7c3e9f1b2d4
Create Date: 2026-10-24 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c4e8a2f7d1b3'
down_revision = 'a7c3e9f1b2d4'
branch_labels = None
depends_on = None


def upgrade():
    # A database built by db.create_all() already has the column.
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("schools")}
    if "image_path" not in columns:
        with op.batch_alter_table('schools', schema=None) as batch_op:
            batch_op.add_column(sa.Column('image_path', sa.String(length=255), nullable=True))

    schools = sa.table('schools', sa.column('name', sa.String), sa.column('image_path', sa.String))
    op.execute(
        schools.update()
        .where(schools.c.name == 'ACS Athens')
        .values(image_path='img/acs-athens.jpg')
    )


def downgrade():
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.drop_column('image_path')
