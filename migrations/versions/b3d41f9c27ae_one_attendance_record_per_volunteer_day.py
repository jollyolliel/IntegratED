"""collapse a volunteer's duplicate attendance records for a day into one

Revision ID: b3d41f9c27ae
Revises: 37267c1e8817
Create Date: 2026-08-22 00:00:00.000000

Data-only — no schema change. A volunteer holding several learners was written
one mirrored record per learner, so their own hours read as a multiple of the
clock time they actually gave. They keep one record per day now; this collapses
what was already written. Grouping happens in Python rather than in SQL because
`attendance.date` carries a time of day and day-truncation is not spelled the
same way in SQLite (dev) and Postgres (prod).
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b3d41f9c27ae'
down_revision = '37267c1e8817'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT a.id, a.user_id, a.date, a.duration, a.is_present, a.partner_id "
        "FROM attendance a JOIN volunteers v ON v.id = a.user_id "
        "ORDER BY a.user_id, a.date, a.id"
    )).fetchall()

    days = {}
    for row in rows:
        days.setdefault((row.user_id, str(row.date)[:10]), []).append(row)

    for records in days.values():
        if len(records) < 2:
            continue
        keep = records[0]
        present = [r for r in records if r.is_present]
        # The duplicates mirror one session, so the longest covers it — the
        # same rule the write path applies to a group whose rows disagree.
        duration = max((r.duration or 0.0) for r in present) if present else 0.0
        # A record naming one of several learners would claim that one was the
        # session; none of them was, on their own.
        partners = {r.partner_id for r in records}
        partner_id = keep.partner_id if len(partners) == 1 else None

        bind.execute(
            sa.text(
                "UPDATE attendance SET duration = :duration, is_present = :is_present, "
                "partner_id = :partner_id WHERE id = :id"
            ),
            {"duration": duration, "is_present": bool(present),
             "partner_id": partner_id, "id": keep.id},
        )
        for extra in records[1:]:
            bind.execute(sa.text("DELETE FROM attendance WHERE id = :id"), {"id": extra.id})


def downgrade():
    # The duplicates carried no information the surviving record lacks, and
    # which learner each named is gone — nothing to restore.
    pass
