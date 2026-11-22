"""initial schema

Revision ID: 7971df202dad
Revises: 
Create Date: 2026-05-09 07:21:26.853870

The schema as `models.py` declared it when Alembic was introduced (commit
16eae1b). Databases that predate Alembic were built by `db.create_all()` and
stamped past this revision, so this only ever runs against an empty database —
where every later revision assumes these tables already exist.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '7971df202dad'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('schools',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('mission_statement', sa.Text(), nullable=True),
    sa.Column('volunteer_domain', sa.String(length=100), nullable=True),
    sa.Column('teacher_domain', sa.String(length=100), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('site_content',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('subjects',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('icon', sa.String(length=100), nullable=False),
    sa.Column('map_test_only', sa.Boolean(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('team_members',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('job', sa.String(length=150), nullable=True),
    sa.Column('strengths', sa.Text(), nullable=True),
    sa.Column('bio', sa.Text(), nullable=True),
    sa.Column('image_url', sa.String(length=300), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_type', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('worksheets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('subject', sa.String(length=100), nullable=False),
    sa.Column('topic', sa.String(length=100), nullable=True),
    sa.Column('filepath', sa.String(length=255), nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('file_type', sa.String(length=10), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_worksheets_filepath'), 'worksheets', ['filepath'], unique=True)
    op.create_table('administrators',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=80), nullable=False),
    sa.Column('password_hash', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_administrators_username'), 'administrators', ['username'], unique=True)
    op.create_table('articles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('content_markdown', sa.Text(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('donations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('stripe_session_id', sa.String(length=200), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('donor_name', sa.String(length=150), nullable=True),
    sa.Column('donor_email', sa.String(length=150), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('school_name', sa.String(length=200), nullable=True),
    sa.Column('school_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stripe_session_id')
    )
    op.create_table('map_questions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subject_id', sa.Integer(), nullable=False),
    sa.Column('level', sa.Integer(), nullable=False),
    sa.Column('content_type', sa.String(length=50), nullable=False),
    sa.Column('question_prompt', sa.String(length=300), nullable=False),
    sa.Column('question_text', sa.Text(), nullable=False),
    sa.Column('options', sa.JSON(), nullable=True),
    sa.Column('answer', sa.String(length=300), nullable=True),
    sa.Column('question_sound', sa.Boolean(), nullable=True),
    sa.Column('question_sound_url', sa.String(length=500), nullable=True),
    sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('school_admins',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=80), nullable=False),
    sa.Column('password_hash', sa.String(length=200), nullable=False),
    sa.Column('school_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_school_admins_username'), 'school_admins', ['username'], unique=True)
    op.create_table('teachers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('google_sub', sa.String(length=128), nullable=False),
    sa.Column('email', sa.String(length=150), nullable=False),
    sa.Column('user_picture', sa.String(length=250), nullable=True),
    sa.Column('school_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_teachers_email'), 'teachers', ['email'], unique=True)
    op.create_index(op.f('ix_teachers_google_sub'), 'teachers', ['google_sub'], unique=True)
    op.create_table('topics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subject_id', sa.Integer(), nullable=False),
    sa.Column('icon', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('title', sa.String(length=150), nullable=False),
    sa.Column('overview_markdown', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('subtopics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=False),
    sa.Column('icon', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('title', sa.String(length=150), nullable=False),
    sa.Column('overview_markdown', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['topic_id'], ['topics.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('volunteers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('google_sub', sa.String(length=128), nullable=False),
    sa.Column('completed_survey', sa.Boolean(), nullable=True),
    sa.Column('email', sa.String(length=150), nullable=False),
    sa.Column('user_picture', sa.String(length=250), nullable=True),
    sa.Column('school_id', sa.Integer(), nullable=True),
    sa.Column('hours_volunteered', sa.Float(), nullable=True),
    sa.Column('survey_data', sa.JSON(), nullable=True),
    sa.Column('is_matched', sa.Boolean(), nullable=True),
    sa.Column('teacher_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ),
    sa.ForeignKeyConstraint(['teacher_id'], ['teachers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_volunteers_email'), 'volunteers', ['email'], unique=True)
    op.create_index(op.f('ix_volunteers_google_sub'), 'volunteers', ['google_sub'], unique=True)
    op.create_table('learners',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=80), nullable=False),
    sa.Column('password_hash', sa.String(length=200), nullable=False),
    sa.Column('plain_password', sa.String(length=200), nullable=True),
    sa.Column('completed_survey', sa.Boolean(), nullable=True),
    sa.Column('completed_map_test', sa.Boolean(), nullable=True),
    sa.Column('subject_levels', sa.JSON(), nullable=False),
    sa.Column('school_id', sa.Integer(), nullable=True),
    sa.Column('survey_data', sa.JSON(), nullable=True),
    sa.Column('map_test_data', sa.JSON(), nullable=True),
    sa.Column('hours_learned', sa.Float(), nullable=True),
    sa.Column('quiz_progress', sa.JSON(), nullable=True),
    sa.Column('is_matched', sa.Boolean(), nullable=True),
    sa.Column('volunteer_id', sa.Integer(), nullable=True),
    sa.Column('teacher_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ),
    sa.ForeignKeyConstraint(['teacher_id'], ['teachers.id'], ),
    sa.ForeignKeyConstraint(['volunteer_id'], ['volunteers.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('volunteer_id')
    )
    op.create_index(op.f('ix_learners_username'), 'learners', ['username'], unique=True)
    op.create_table('questions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subject_id', sa.Integer(), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=False),
    sa.Column('subtopic_id', sa.Integer(), nullable=False),
    sa.Column('content_type', sa.String(length=50), nullable=False),
    sa.Column('question_sound', sa.Boolean(), nullable=True),
    sa.Column('question_sound_url', sa.String(length=300), nullable=True),
    sa.Column('option_sound', sa.Boolean(), nullable=True),
    sa.Column('option_sound_url', sa.JSON(), nullable=True),
    sa.Column('question_prompt', sa.String(length=300), nullable=False),
    sa.Column('question_subtext', sa.String(length=300), nullable=True),
    sa.Column('question_text', sa.Text(), nullable=False),
    sa.Column('options', sa.JSON(), nullable=True),
    sa.Column('answer', sa.String(length=300), nullable=True),
    sa.Column('context_group_id', sa.String(length=100), nullable=True),
    sa.Column('context_text', sa.Text(), nullable=True),
    sa.Column('context_image', sa.String(length=300), nullable=True),
    sa.Column('word_selection_correct_words', sa.JSON(), nullable=True),
    sa.Column('fill_blank_options', sa.JSON(), nullable=True),
    sa.Column('word_bank', sa.JSON(), nullable=True),
    sa.Column('word_type', sa.String(length=50), nullable=True),
    sa.Column('max_attempts', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ),
    sa.ForeignKeyConstraint(['subtopic_id'], ['subtopics.id'], ),
    sa.ForeignKeyConstraint(['topic_id'], ['topics.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_questions_subtopic_id'), 'questions', ['subtopic_id'], unique=False)
    op.create_table('attendance',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('date', sa.DateTime(), nullable=False),
    sa.Column('duration', sa.Float(), nullable=False),
    sa.Column('teacher_id', sa.Integer(), nullable=False),
    sa.Column('learner_id', sa.Integer(), nullable=False),
    sa.Column('volunteer_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['learner_id'], ['learners.id'], ),
    sa.ForeignKeyConstraint(['teacher_id'], ['teachers.id'], ),
    sa.ForeignKeyConstraint(['volunteer_id'], ['volunteers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('learner_completed_subtopics',
    sa.Column('learner_id', sa.Integer(), nullable=False),
    sa.Column('subtopic_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['learner_id'], ['learners.id'], ),
    sa.ForeignKeyConstraint(['subtopic_id'], ['subtopics.id'], ),
    sa.PrimaryKeyConstraint('learner_id', 'subtopic_id')
    )
    op.create_table('learner_completed_topics',
    sa.Column('learner_id', sa.Integer(), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['learner_id'], ['learners.id'], ),
    sa.ForeignKeyConstraint(['topic_id'], ['topics.id'], ),
    sa.PrimaryKeyConstraint('learner_id', 'topic_id')
    )
    op.create_table('map_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('learner_id', sa.Integer(), nullable=False),
    sa.Column('levels', sa.JSON(), nullable=False),
    sa.Column('asked_ids', sa.JSON(), nullable=False),
    sa.Column('history', sa.JSON(), nullable=False),
    sa.Column('count', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['learner_id'], ['learners.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('learner_id')
    )
    op.create_table('worksheet_assignments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('assigned_at', sa.DateTime(), nullable=False),
    sa.Column('completed', sa.Boolean(), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('teacher_id', sa.Integer(), nullable=False),
    sa.Column('learner_id', sa.Integer(), nullable=False),
    sa.Column('volunteer_id', sa.Integer(), nullable=True),
    sa.Column('worksheet_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['learner_id'], ['learners.id'], ),
    sa.ForeignKeyConstraint(['teacher_id'], ['teachers.id'], ),
    sa.ForeignKeyConstraint(['volunteer_id'], ['volunteers.id'], ),
    sa.ForeignKeyConstraint(['worksheet_id'], ['worksheets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('worksheet_assignments')
    op.drop_table('map_sessions')
    op.drop_table('learner_completed_topics')
    op.drop_table('learner_completed_subtopics')
    op.drop_table('attendance')
    op.drop_index(op.f('ix_questions_subtopic_id'), table_name='questions')
    op.drop_table('questions')
    op.drop_index(op.f('ix_learners_username'), table_name='learners')
    op.drop_table('learners')
    op.drop_index(op.f('ix_volunteers_google_sub'), table_name='volunteers')
    op.drop_index(op.f('ix_volunteers_email'), table_name='volunteers')
    op.drop_table('volunteers')
    op.drop_table('subtopics')
    op.drop_table('topics')
    op.drop_index(op.f('ix_teachers_google_sub'), table_name='teachers')
    op.drop_index(op.f('ix_teachers_email'), table_name='teachers')
    op.drop_table('teachers')
    op.drop_index(op.f('ix_school_admins_username'), table_name='school_admins')
    op.drop_table('school_admins')
    op.drop_table('map_questions')
    op.drop_table('donations')
    op.drop_table('articles')
    op.drop_index(op.f('ix_administrators_username'), table_name='administrators')
    op.drop_table('administrators')
    op.drop_index(op.f('ix_worksheets_filepath'), table_name='worksheets')
    op.drop_table('worksheets')
    op.drop_table('users')
    op.drop_table('team_members')
    op.drop_table('subjects')
    op.drop_table('site_content')
    op.drop_table('schools')
