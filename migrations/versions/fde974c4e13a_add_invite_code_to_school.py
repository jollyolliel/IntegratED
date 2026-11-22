"""add invite code to school

Revision ID: fde974c4e13a
Revises: 56fce739018a
Create Date: 2026-06-06 11:04:29.265799

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'fde974c4e13a'
down_revision = '56fce739018a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.add_column(sa.Column('invite_code', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('invite_code_expires_at', sa.DateTime(), nullable=True))

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'translation_cache' in inspector.get_table_names():
        with op.batch_alter_table('translation_cache', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_translation_cache_content_hash'))

        op.drop_table('translation_cache')


def downgrade():
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.drop_column('invite_code_expires_at')
        batch_op.drop_column('invite_code')

    op.create_table('translation_cache',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('content_hash', sa.VARCHAR(length=64), nullable=False),
    sa.Column('target_lang', sa.VARCHAR(length=10), nullable=False),
    sa.Column('translated_html', sa.TEXT(), nullable=False),
    sa.Column('created_at', sa.DATETIME(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('content_hash', 'target_lang', name=op.f('uq_translation_cache'))
    )
    with op.batch_alter_table('translation_cache', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_translation_cache_content_hash'), ['content_hash'], unique=False)
