"""Add missing FK indexes on learners, volunteers, attendance, worksheet_assignments

Revision ID: b3e8a1c40d27
Revises: fde974c4e13a
Create Date: 2026-06-12

Dashboards filter and aggregate on these FK columns constantly (teacher
dashboard, school admin attendance sums) — without indexes every one of those
queries is a sequential scan.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b3e8a1c40d27'
down_revision = 'fde974c4e13a'
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_learners_school_id", "learners", "school_id"),
    ("ix_learners_teacher_id", "learners", "teacher_id"),
    ("ix_volunteers_school_id", "volunteers", "school_id"),
    ("ix_volunteers_teacher_id", "volunteers", "teacher_id"),
    ("ix_attendance_teacher_id", "attendance", "teacher_id"),
    ("ix_attendance_learner_id", "attendance", "learner_id"),
    ("ix_attendance_volunteer_id", "attendance", "volunteer_id"),
    ("ix_worksheet_assignments_teacher_id", "worksheet_assignments", "teacher_id"),
    ("ix_worksheet_assignments_learner_id", "worksheet_assignments", "learner_id"),
    ("ix_worksheet_assignments_volunteer_id", "worksheet_assignments", "volunteer_id"),
    ("ix_worksheet_assignments_worksheet_id", "worksheet_assignments", "worksheet_id"),
]


def upgrade():
    for name, table, column in INDEXES:
        op.create_index(name, table, [column], unique=False, if_not_exists=True)


def downgrade():
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
