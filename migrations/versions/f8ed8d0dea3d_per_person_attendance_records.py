"""per-person attendance records

Attendance moves from one shared row per (date, learner, volunteer) — with the
volunteer's own mark/duration/notes riding as parallel nullable columns on
that same row — to one row per person per session: (user_id, partner_id,
date, is_present, duration, notes, teacher_id). See
docs/adr/0001-per-person-attendance-records.md.

Every existing row becomes the learner's own record (user_id=learner_id,
partner_id=volunteer_id, is_present = status == 'present'). Any row that had
a volunteer also gets a new row for the volunteer's own record
(user_id=volunteer_id, partner_id=learner_id), seeded from the old
volunteer_status/volunteer_duration/volunteer_notes columns:
  - volunteer_status == 'absent'  -> is_present=False, duration=0.0
  - volunteer_status == 'present' -> is_present=True,
        duration = volunteer_duration if set, else the learner's duration
  - volunteer_status is NULL (never marked) -> mirrors the learner's own
        is_present/duration, notes=NULL — this is the one lossless part: the
        old NULL-fallback read logic (Volunteer.hours_volunteered) is now a
        materialized row instead of code that reimplements the fallback at
        every read site.

Revision ID: f8ed8d0dea3d
Revises: 2dfae1eba3c0
Create Date: 2026-08-18
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f8ed8d0dea3d'
down_revision = '2dfae1eba3c0'
branch_labels = None
depends_on = None

_NATURAL_KEY_INDEX = "ix_attendance_natural_key"

# Every existing row becomes the learner's own record.
BACKFILL_UPDATE_SQL = (
    "UPDATE attendance SET "
    "user_id = learner_id, "
    "partner_id = volunteer_id, "
    "is_present = (status = 'present')"
)

# Materializes the volunteer's own record for every pair that had one, from
# the old parallel volunteer_* columns. learner_id is still NOT NULL with no
# default at this point in the migration (it's dropped below) — carried
# through unchanged so the insert satisfies the old constraint; it's
# meaningless on this new row and gone by the time this migration finishes.
# Exposed as a module constant (rather than inlined in upgrade()) so
# tests/test_attendance_migration.py can exercise the backfill's three
# volunteer_status branches directly against a scratch table.
BACKFILL_INSERT_SQL = (
    "INSERT INTO attendance (date, duration, notes, teacher_id, user_id, partner_id, is_present, learner_id) "
    "SELECT "
    "  date, "
    "  CASE "
    "    WHEN volunteer_status = 'absent' THEN 0.0 "
    "    WHEN volunteer_status = 'present' THEN COALESCE(volunteer_duration, duration) "
    "    ELSE duration "
    "  END, "
    "  CASE WHEN volunteer_status IN ('present', 'absent') THEN volunteer_notes ELSE NULL END, "
    "  teacher_id, "
    "  volunteer_id, "
    "  learner_id, "
    "  CASE "
    "    WHEN volunteer_status = 'absent' THEN FALSE "
    "    WHEN volunteer_status = 'present' THEN TRUE "
    "    ELSE (status = 'present') "
    "  END, "
    "  learner_id "
    "FROM attendance "
    "WHERE volunteer_id IS NOT NULL"
)


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {c["name"] for c in inspector.get_columns("attendance")}

    # ── 1. Add the new columns alongside the old ones ──────────────────────
    # Nullable for now — user_id/is_present are backfilled below, then locked
    # to NOT NULL once every row has a value.
    if "user_id" not in existing_columns:
        op.add_column("attendance", sa.Column("user_id", sa.Integer(), nullable=True))
    if "partner_id" not in existing_columns:
        op.add_column("attendance", sa.Column("partner_id", sa.Integer(), nullable=True))
    if "is_present" not in existing_columns:
        op.add_column("attendance", sa.Column("is_present", sa.Boolean(), nullable=True))

    # ── 2. Backfill: every existing row becomes the learner's own record ──
    op.execute(BACKFILL_UPDATE_SQL)

    # ── 3. Materialize the volunteer's own record for every pair that had
    #        one, from the old parallel volunteer_* columns ──────────────
    op.execute(BACKFILL_INSERT_SQL)

    # ── 4. Drop the old columns/indexes/FKs, lock the new columns down,
    #        add the new indexes/FKs ───────────────────────────────────────
    with op.batch_alter_table("attendance", schema=None) as batch_op:
        existing_indexes = {ix["name"] for ix in inspector.get_indexes("attendance")}
        if "ix_attendance_learner_id" in existing_indexes:
            batch_op.drop_index(batch_op.f("ix_attendance_learner_id"))
        if "ix_attendance_volunteer_id" in existing_indexes:
            batch_op.drop_index(batch_op.f("ix_attendance_volunteer_id"))

        # No explicit drop_constraint for the old learner_id/volunteer_id FKs:
        # they're unnamed on SQLite (Alembic can't target an unnamed
        # constraint), and dropping their columns below removes them from the
        # recreated table anyway.
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column(
            "is_present", existing_type=sa.Boolean(),
            nullable=False, server_default="1",
        )

        batch_op.drop_column("volunteer_duration")
        batch_op.drop_column("volunteer_notes")
        batch_op.drop_column("volunteer_status")
        batch_op.drop_column("status")
        batch_op.drop_column("learner_id")
        batch_op.drop_column("volunteer_id")

        batch_op.create_index(batch_op.f("ix_attendance_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_attendance_partner_id"), ["partner_id"], unique=False)
        batch_op.create_index(_NATURAL_KEY_INDEX, ["date", "user_id", "partner_id"], unique=False)
        batch_op.create_foreign_key("fk_attendance_user_id_users", "users", ["user_id"], ["id"])
        batch_op.create_foreign_key("fk_attendance_partner_id_users", "users", ["partner_id"], ["id"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    with op.batch_alter_table("attendance", schema=None) as batch_op:
        # No explicit drop_constraint here either — see upgrade()'s note;
        # dropping user_id/partner_id below takes their FKs with them.
        existing_indexes = {ix["name"] for ix in inspector.get_indexes("attendance")}
        if _NATURAL_KEY_INDEX in existing_indexes:
            batch_op.drop_index(_NATURAL_KEY_INDEX)
        if "ix_attendance_partner_id" in existing_indexes:
            batch_op.drop_index(batch_op.f("ix_attendance_partner_id"))
        if "ix_attendance_user_id" in existing_indexes:
            batch_op.drop_index(batch_op.f("ix_attendance_user_id"))

        batch_op.add_column(sa.Column("volunteer_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("learner_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("status", sa.String(length=10), server_default="present", nullable=False)
        )
        batch_op.add_column(sa.Column("volunteer_status", sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column("volunteer_notes", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("volunteer_duration", sa.Float(), nullable=True))

    # Lossy on purpose: a volunteer's own record may have been edited
    # independently of its learner's since creation (that's the whole point
    # of the redesign), so there is no faithful way back into one shared row
    # per pair. This keeps every learner's own record (learner_id/status from
    # user_id/is_present) and merges in whichever volunteer own-record still
    # matches that same (date, learner, volunteer) pairing as the old
    # volunteer_* columns, then drops the now-redundant volunteer rows.
    op.execute(
        "UPDATE attendance SET "
        "volunteer_id = (SELECT v.partner_id FROM attendance v "
        " WHERE v.user_id = attendance.partner_id AND v.partner_id = attendance.user_id "
        " AND v.date = attendance.date AND v.id != attendance.id), "
        "volunteer_status = (SELECT CASE WHEN v.is_present THEN 'present' ELSE 'absent' END FROM attendance v "
        " WHERE v.user_id = attendance.partner_id AND v.partner_id = attendance.user_id "
        " AND v.date = attendance.date AND v.id != attendance.id), "
        "volunteer_duration = (SELECT v.duration FROM attendance v "
        " WHERE v.user_id = attendance.partner_id AND v.partner_id = attendance.user_id "
        " AND v.date = attendance.date AND v.id != attendance.id), "
        "volunteer_notes = (SELECT v.notes FROM attendance v "
        " WHERE v.user_id = attendance.partner_id AND v.partner_id = attendance.user_id "
        " AND v.date = attendance.date AND v.id != attendance.id)"
    )
    # Every volunteer-owned row is exactly one step 3 inserted in upgrade() —
    # its data was just folded onto the matching learner row above.
    op.execute(
        "DELETE FROM attendance WHERE user_id IN "
        "(SELECT id FROM users WHERE user_type = 'volunteer')"
    )
    op.execute(
        "UPDATE attendance SET learner_id = user_id, "
        "status = CASE WHEN is_present THEN 'present' ELSE 'absent' END"
    )

    with op.batch_alter_table("attendance", schema=None) as batch_op:
        batch_op.alter_column("learner_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(batch_op.f("ix_attendance_learner_id"), ["learner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_attendance_volunteer_id"), ["volunteer_id"], unique=False)
        batch_op.create_foreign_key("fk_attendance_learner_id_learners", "learners", ["learner_id"], ["id"])
        batch_op.create_foreign_key("fk_attendance_volunteer_id_volunteers", "volunteers", ["volunteer_id"], ["id"])
        batch_op.drop_column("partner_id")
        batch_op.drop_column("user_id")
        batch_op.drop_column("is_present")
