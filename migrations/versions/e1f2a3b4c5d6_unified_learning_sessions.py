"""Unified learning sessions — replace M2M progress tables with JSON columns and rename map_sessions

Changes:
  #1  rename map_sessions -> learning_sessions (or create if needed), add session_type/subtopic + quiz/game fields
  #2  add completed_subtopic_ids + completed_topic_ids JSON columns to learners
  #3  migrate M2M data (learner_completed_subtopics/topics) into the new JSON columns
  #4  drop learner_completed_subtopics and learner_completed_topics tables
  #5  drop quiz_progress and completed_minigame_subtopics from learners

Revision ID: e1f2a3b4c5d6
Revises: d4b1a7c9e2f0
Create Date: 2026-06-16 12:00:00.000000
"""
import json
import logging
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d4b1a7c9e2f0"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def _table_exists(conn, table_name):
    return sa.inspect(conn).has_table(table_name)


def _column_exists(conn, table_name, column_name):
    cols = sa.inspect(conn).get_columns(table_name)
    return any(c["name"] == column_name for c in cols)


def upgrade():
    conn = op.get_bind()

    # ── 1. Ensure learning_sessions exists with all required columns ──────────
    if not _table_exists(conn, "learning_sessions"):
        if _table_exists(conn, "map_sessions"):
            # Rename and add columns
            op.rename_table("map_sessions", "learning_sessions")
            with op.batch_alter_table("learning_sessions", recreate="always") as batch_op:
                batch_op.add_column(
                    sa.Column("session_type", sa.String(20), nullable=False, server_default="placement")
                )
                batch_op.add_column(
                    sa.Column("subtopic_id", sa.Integer(), nullable=True)
                )
                batch_op.add_column(sa.Column("responses", sa.JSON(), nullable=True))
                batch_op.add_column(sa.Column("correct_count", sa.Integer(), nullable=True, server_default="0"))
                batch_op.add_column(sa.Column("questions_completed", sa.Integer(), nullable=True, server_default="0"))
                batch_op.add_column(sa.Column("word_selection_attempts", sa.JSON(), nullable=True))
                batch_op.create_index("ix_learning_sessions_learner_id", ["learner_id"])
                batch_op.create_index("ix_learning_sessions_subtopic_id", ["subtopic_id"])
        else:
            # Fresh create
            op.create_table(
                "learning_sessions",
                sa.Column("id", sa.Integer(), primary_key=True),
                sa.Column("learner_id", sa.Integer(), sa.ForeignKey("learners.id"), nullable=False, index=True),
                sa.Column("session_type", sa.String(20), nullable=False),
                sa.Column("subtopic_id", sa.Integer(), sa.ForeignKey("subtopics.id"), nullable=True, index=True),
                sa.Column("subject_state", sa.JSON(), nullable=False),
                sa.Column("asked_ids", sa.JSON(), nullable=False),
                sa.Column("history", sa.JSON(), nullable=False),
                sa.Column("count", sa.Integer(), nullable=True),
                sa.Column("responses", sa.JSON(), nullable=True),
                sa.Column("correct_count", sa.Integer(), nullable=True),
                sa.Column("questions_completed", sa.Integer(), nullable=True),
                sa.Column("word_selection_attempts", sa.JSON(), nullable=True),
                sa.Column("updated_at", sa.DateTime(), nullable=True),
            )
    else:
        # learning_sessions already exists (created by db.create_all()) — migrate
        # data from map_sessions if it exists, then drop it
        if _table_exists(conn, "map_sessions"):
            insert_verb = "INSERT" if conn.dialect.name == "postgresql" else "INSERT OR IGNORE"
            on_conflict = " ON CONFLICT DO NOTHING" if conn.dialect.name == "postgresql" else ""
            conn.execute(sa.text(
                f"{insert_verb} INTO learning_sessions "
                "(learner_id, session_type, subject_state, asked_ids, history, count, updated_at) "
                "SELECT learner_id, 'placement', subject_state, asked_ids, history, count, updated_at "
                f"FROM map_sessions{on_conflict}"
            ))

    # Drop old map_sessions if still present
    if _table_exists(conn, "map_sessions"):
        op.drop_table("map_sessions")

    # ── 2. Add new JSON columns to learners ───────────────────────────────────
    if not _column_exists(conn, "learners", "completed_subtopic_ids"):
        with op.batch_alter_table("learners") as batch_op:
            batch_op.add_column(sa.Column("completed_subtopic_ids", sa.JSON(), nullable=True))
            batch_op.add_column(sa.Column("completed_topic_ids", sa.JSON(), nullable=True))

    # ── 3. Migrate M2M data into JSON columns ─────────────────────────────────
    if _table_exists(conn, "learner_completed_subtopics"):
        subtopic_rows = conn.execute(
            sa.text("SELECT learner_id, subtopic_id FROM learner_completed_subtopics ORDER BY learner_id")
        ).fetchall()
        learner_subtopics = defaultdict(list)
        for learner_id, subtopic_id in subtopic_rows:
            learner_subtopics[learner_id].append(subtopic_id)
        for learner_id, ids in learner_subtopics.items():
            conn.execute(
                sa.text("UPDATE learners SET completed_subtopic_ids = :v WHERE id = :lid"),
                {"v": json.dumps(ids), "lid": learner_id},
            )

    if _table_exists(conn, "learner_completed_topics"):
        topic_rows = conn.execute(
            sa.text("SELECT learner_id, topic_id FROM learner_completed_topics ORDER BY learner_id")
        ).fetchall()
        learner_topics = defaultdict(list)
        for learner_id, topic_id in topic_rows:
            learner_topics[learner_id].append(topic_id)
        for learner_id, ids in learner_topics.items():
            conn.execute(
                sa.text("UPDATE learners SET completed_topic_ids = :v WHERE id = :lid"),
                {"v": json.dumps(ids), "lid": learner_id},
            )

    # ── 4. Drop old M2M tables ────────────────────────────────────────────────
    if _table_exists(conn, "learner_completed_subtopics"):
        op.drop_table("learner_completed_subtopics")
    if _table_exists(conn, "learner_completed_topics"):
        op.drop_table("learner_completed_topics")

    # ── 5. Drop obsolete columns from learners ────────────────────────────────
    cols_to_drop = []
    if _column_exists(conn, "learners", "quiz_progress"):
        cols_to_drop.append("quiz_progress")
    if _column_exists(conn, "learners", "completed_minigame_subtopics"):
        cols_to_drop.append("completed_minigame_subtopics")
    if cols_to_drop:
        with op.batch_alter_table("learners") as batch_op:
            for col in cols_to_drop:
                batch_op.drop_column(col)


def downgrade():
    # Restore M2M tables
    op.create_table(
        "learner_completed_subtopics",
        sa.Column("learner_id", sa.Integer(), sa.ForeignKey("learners.id"), primary_key=True),
        sa.Column("subtopic_id", sa.Integer(), sa.ForeignKey("subtopics.id"), primary_key=True),
    )
    op.create_table(
        "learner_completed_topics",
        sa.Column("learner_id", sa.Integer(), sa.ForeignKey("learners.id"), primary_key=True),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), primary_key=True),
    )

    conn = op.get_bind()

    rows = conn.execute(
        sa.text("SELECT id, completed_subtopic_ids FROM learners WHERE completed_subtopic_ids IS NOT NULL")
    ).fetchall()
    for learner_id, ids_json in rows:
        ids = json.loads(ids_json) if isinstance(ids_json, str) else (ids_json or [])
        for sid in ids:
            try:
                conn.execute(
                    sa.text("INSERT INTO learner_completed_subtopics (learner_id, subtopic_id) VALUES (:lid, :sid)"),
                    {"lid": learner_id, "sid": sid},
                )
            except Exception as exc:  # noqa: BLE001 - duplicate/invalid row is skipped, DB error surface varies by dialect
                logger.debug("Skipping learner_completed_subtopics row (learner=%s, subtopic=%s): %s", learner_id, sid, exc)

    rows = conn.execute(
        sa.text("SELECT id, completed_topic_ids FROM learners WHERE completed_topic_ids IS NOT NULL")
    ).fetchall()
    for learner_id, ids_json in rows:
        ids = json.loads(ids_json) if isinstance(ids_json, str) else (ids_json or [])
        for tid in ids:
            try:
                conn.execute(
                    sa.text("INSERT INTO learner_completed_topics (learner_id, topic_id) VALUES (:lid, :tid)"),
                    {"lid": learner_id, "tid": tid},
                )
            except Exception as exc:  # noqa: BLE001 - duplicate/invalid row is skipped, DB error surface varies by dialect
                logger.debug("Skipping learner_completed_topics row (learner=%s, topic=%s): %s", learner_id, tid, exc)

    with op.batch_alter_table("learners") as batch_op:
        batch_op.drop_column("completed_subtopic_ids")
        batch_op.drop_column("completed_topic_ids")
        batch_op.add_column(sa.Column("quiz_progress", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("completed_minigame_subtopics", sa.JSON(), nullable=True))

    op.rename_table("learning_sessions", "map_sessions")
    with op.batch_alter_table("map_sessions", recreate="always") as batch_op:
        batch_op.drop_column("session_type")
        batch_op.drop_column("subtopic_id")
        batch_op.drop_column("responses")
        batch_op.drop_column("correct_count")
        batch_op.drop_column("questions_completed")
        batch_op.drop_column("word_selection_attempts")
        batch_op.create_unique_constraint("uq_map_sessions_learner_id", ["learner_id"])
