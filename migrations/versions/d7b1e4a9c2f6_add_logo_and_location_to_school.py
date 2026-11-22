"""add logo and location to school

Each school's public page shows its logo (initials when it has none) and
where it is. Backfill ACS Athens's logo and location.

Revision ID: d7b1e4a9c2f6
Revises: c4e8a2f7d1b3
Create Date: 2026-10-24 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd7b1e4a9c2f6'
down_revision = 'c4e8a2f7d1b3'
branch_labels = None
depends_on = None


def upgrade():
    # A database built by db.create_all() already has the columns.
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("schools")}
    with op.batch_alter_table('schools', schema=None) as batch_op:
        if "logo_path" not in columns:
            batch_op.add_column(sa.Column('logo_path', sa.String(length=255), nullable=True))
        if "location" not in columns:
            batch_op.add_column(sa.Column('location', sa.String(length=120), nullable=True))

    schools = sa.table(
        'schools', sa.column('name', sa.String), sa.column('logo_path', sa.String), sa.column('location', sa.String),
    )
    op.execute(
        schools.update()
        .where(schools.c.name == 'ACS Athens')
        .values(logo_path='img/schools/acs-athens-logo.jpg', location='Athens, Greece')
    )


def downgrade():
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.drop_column('location')
        batch_op.drop_column('logo_path')
