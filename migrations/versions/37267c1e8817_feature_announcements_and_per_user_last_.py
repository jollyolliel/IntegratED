"""feature announcements and per-user last seen marker

Revision ID: 37267c1e8817
Revises: f8ed8d0dea3d
Create Date: 2026-08-19 20:55:28.664103

Autogenerate only caught the users column: the dev SQLite DB already carried
feature_announcements from a `db.create_all()`, so the table read as "no
change". It is written out in full below — prod (Postgres) has never seen it.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '37267c1e8817'
down_revision = 'f8ed8d0dea3d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'feature_announcements',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('uid', sa.String(length=100), nullable=False),
        sa.Column('content', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    # `uid` is unique + indexed on the model, which collapses to a single
    # unique index rather than a separate constraint.
    op.create_index(
        op.f('ix_feature_announcements_uid'), 'feature_announcements', ['uid'], unique=True
    )

    # High-water mark, not a foreign key — see the column comment in models.py.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_seen_announcement_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('last_seen_announcement_id')

    op.drop_index(op.f('ix_feature_announcements_uid'), table_name='feature_announcements')
    op.drop_table('feature_announcements')
