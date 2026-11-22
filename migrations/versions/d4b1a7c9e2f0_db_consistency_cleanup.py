"""db consistency cleanup

Removes redundant / drift-prone columns and adds missing indexes:
  #1  merge completed_rocket/word_storm/match_up_subtopics -> completed_minigame_subtopics
  #2  Learner.subject_levels default -> {} (python-side only, no DDL)
  #3  drop Learner.hours_learned / Volunteer.hours_volunteered (computed from Attendance)
  #4  drop Donation.school_name (join via school_id)
  #6  index Question.subject_id / topic_id
  #7  index Teacher.school_id
  #8  drop MapSession.levels (derive from subject_state)
  #9  drop Learner.map_test_data (MapSession is the only history source)
  #10 widen Question.question_sound_url 300 -> 500

Revision ID: d4b1a7c9e2f0
Revises: 5b8b50f9bb3e
Create Date: 2026-06-16 00:00:00.000000

"""
import json

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd4b1a7c9e2f0'
down_revision = '5b8b50f9bb3e'
branch_labels = None
depends_on = None


def _learners_table():
    return sa.table(
        'learners',
        sa.column('id', sa.Integer),
        sa.column('completed_rocket_subtopics', sa.JSON),
        sa.column('completed_word_storm_subtopics', sa.JSON),
        sa.column('completed_match_up_subtopics', sa.JSON),
        sa.column('completed_minigame_subtopics', sa.JSON),
    )


def _as_dict(raw):
    if isinstance(raw, str):
        return json.loads(raw or '{}')
    return raw or {}


def _merge_minigame_data(bind):
    """#1 upgrade: fold the three per-game JSON maps into one, tagging game_type."""
    learners = _learners_table()
    rows = bind.execute(sa.select(
        learners.c.id,
        learners.c.completed_rocket_subtopics,
        learners.c.completed_word_storm_subtopics,
        learners.c.completed_match_up_subtopics,
    )).mappings().all()
    for row in rows:
        merged = {}
        for game_type, raw in (
            ('rocket', row['completed_rocket_subtopics']),
            ('word_storm', row['completed_word_storm_subtopics']),
            ('match_up', row['completed_match_up_subtopics']),
        ):
            for st_id, payload in _as_dict(raw).items():
                entry = dict(payload or {})
                entry.setdefault('game_type', game_type)
                merged[str(st_id)] = entry
        bind.execute(
            learners.update()
            .where(learners.c.id == row['id'])
            .values(completed_minigame_subtopics=merged)
        )


def _split_minigame_data(bind):
    """#1 downgrade: scatter the merged map back into three per-game maps."""
    learners = _learners_table()
    rows = bind.execute(sa.select(
        learners.c.id,
        learners.c.completed_minigame_subtopics,
    )).mappings().all()
    for row in rows:
        rocket, storm, match = {}, {}, {}
        for st_id, payload in _as_dict(row['completed_minigame_subtopics']).items():
            entry = dict(payload or {})
            game_type = entry.pop('game_type', None)
            target = {'rocket': rocket, 'word_storm': storm, 'match_up': match}.get(game_type)
            if target is not None:
                target[str(st_id)] = entry
        bind.execute(
            learners.update()
            .where(learners.c.id == row['id'])
            .values(
                completed_rocket_subtopics=rocket,
                completed_word_storm_subtopics=storm,
                completed_match_up_subtopics=match,
            )
        )


def upgrade():
    bind = op.get_bind()

    # #1 add merged column, migrate data, drop the three originals (+ #3/#9 learner drops)
    with op.batch_alter_table('learners', schema=None) as batch_op:
        batch_op.add_column(sa.Column('completed_minigame_subtopics', sa.JSON(), nullable=True))

    _merge_minigame_data(bind)

    with op.batch_alter_table('learners', schema=None) as batch_op:
        batch_op.drop_column('completed_rocket_subtopics')
        batch_op.drop_column('completed_word_storm_subtopics')
        batch_op.drop_column('completed_match_up_subtopics')
        batch_op.drop_column('hours_learned')      # #3
        batch_op.drop_column('map_test_data')      # #9

    with op.batch_alter_table('volunteers', schema=None) as batch_op:
        batch_op.drop_column('hours_volunteered')  # #3

    with op.batch_alter_table('donations', schema=None) as batch_op:
        batch_op.drop_column('school_name')        # #4

    with op.batch_alter_table('map_sessions', schema=None) as batch_op:
        batch_op.drop_column('levels')             # #8

    # #6 indexes + #10 widen sound url
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.alter_column(
            'question_sound_url',
            existing_type=sa.String(length=300),
            type_=sa.String(length=500),
            existing_nullable=True,
        )
        batch_op.create_index('ix_questions_subject_id', ['subject_id'])
        batch_op.create_index('ix_questions_topic_id', ['topic_id'])

    # #7 index Teacher.school_id
    with op.batch_alter_table('teachers', schema=None) as batch_op:
        batch_op.create_index('ix_teachers_school_id', ['school_id'])


def downgrade():
    bind = op.get_bind()

    with op.batch_alter_table('teachers', schema=None) as batch_op:
        batch_op.drop_index('ix_teachers_school_id')

    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.drop_index('ix_questions_topic_id')
        batch_op.drop_index('ix_questions_subject_id')
        batch_op.alter_column(
            'question_sound_url',
            existing_type=sa.String(length=500),
            type_=sa.String(length=300),
            existing_nullable=True,
        )

    with op.batch_alter_table('map_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('levels', sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

    with op.batch_alter_table('donations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('school_name', sa.String(length=200), nullable=True))

    with op.batch_alter_table('volunteers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hours_volunteered', sa.Float(), nullable=True, server_default='0'))

    with op.batch_alter_table('learners', schema=None) as batch_op:
        batch_op.add_column(sa.Column('map_test_data', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('hours_learned', sa.Float(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('completed_rocket_subtopics', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('completed_word_storm_subtopics', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('completed_match_up_subtopics', sa.JSON(), nullable=True))

    _split_minigame_data(bind)

    with op.batch_alter_table('learners', schema=None) as batch_op:
        batch_op.drop_column('completed_minigame_subtopics')
