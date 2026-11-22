from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    request,
    url_for,
)
from flask_login import login_required

from extensions import db, limiter
from helpers import roster_ops
from helpers.announcements import get_pending_announcement
from helpers.auth_utils import clean_credential, has_whitespace
from helpers.current_user import current_school_admin as current_user
from helpers.render import render_template
from helpers.utils import clamp_page, wants_fragment, wants_json
from models import (
    Attendance,
    Donation,
    Learner,
    School,
    Teacher,
    Volunteer,
    WorksheetAssignment,
)

school_admin_bp = Blueprint("school_admin", __name__, url_prefix="/school")
limiter.limit("120 per minute")(school_admin_bp)

# The /people roster is one page, three tables — each pages independently
# against its own `?<kind>_page=` query param (clamp_page's `arg`), so hopping
# one table's page never resets the other two.
_PAGE_SIZE = 25
# Person-detail attendance previews show this many, newest first, then link
# out to /school-admin/attendance filtered to that person (docs/ui-design/page-behaviour.md).
_PREVIEW_SIZE = 7

@school_admin_bp.before_request
@login_required
def require_school_admin():
    if current_user.user_type != "school_admin":
        abort(403)

@school_admin_bp.route("/")
def dashboard():
    school = current_user.school
    learner_count = db.session.scalar(
        db.select(db.func.count()).select_from(Learner).filter_by(school_id=school.id)
    )
    volunteer_count = db.session.scalar(
        db.select(db.func.count()).select_from(Volunteer).filter_by(school_id=school.id)
    )
    teacher_count = db.session.scalar(
        db.select(db.func.count()).select_from(Teacher).filter_by(school_id=school.id)
    )

    learner_ids = db.session.scalars(
        db.select(Learner.id).filter_by(school_id=school.id)
    ).all()
    total_hours = db.session.scalar(
        db.select(db.func.sum(Attendance.duration))
        .where(Attendance.user_id.in_(learner_ids), Attendance.is_present)
    ) or 0

    total_donations_cents = db.session.scalar(
        db.select(db.func.sum(Donation.amount)).filter_by(school_id=school.id)
    ) or 0
    recent_donations = db.session.scalars(
        db.select(Donation)
        .filter_by(school_id=school.id)
        .order_by(Donation.created_at.desc())
        .limit(5)
    ).all()

    return render_template(
        "@pages/school_admin/dashboard.jx",
        school=school,
        learner_count=learner_count,
        volunteer_count=volunteer_count,
        teacher_count=teacher_count,
        total_hours=round(total_hours, 1),
        total_donations=total_donations_cents / 100,
        recent_donations=recent_donations,
        pending_announcement=get_pending_announcement(current_user),
    )

@school_admin_bp.route("/people")
def people():
    """One roster page, three independently paged tables — each keeps its own
    `?<kind>_page=` so paging one never resets the other two."""
    school = current_user.school

    teacher_total = db.session.scalar(
        db.select(db.func.count()).select_from(Teacher).filter_by(school_id=school.id)
    )
    learner_total = db.session.scalar(
        db.select(db.func.count()).select_from(Learner).filter_by(school_id=school.id)
    )
    volunteer_total = db.session.scalar(
        db.select(db.func.count()).select_from(Volunteer).filter_by(school_id=school.id)
    )
    teacher_page, teacher_page_count = clamp_page(teacher_total, _PAGE_SIZE, arg="teacher_page")
    learner_page, learner_page_count = clamp_page(learner_total, _PAGE_SIZE, arg="learner_page")
    volunteer_page, volunteer_page_count = clamp_page(volunteer_total, _PAGE_SIZE, arg="volunteer_page")

    teachers = db.session.scalars(
        db.select(Teacher).filter_by(school_id=school.id).order_by(Teacher.id.desc())
        .offset((teacher_page - 1) * _PAGE_SIZE).limit(_PAGE_SIZE)
    ).all()
    learners = db.session.scalars(
        db.select(Learner).filter_by(school_id=school.id).order_by(Learner.id.desc())
        .offset((learner_page - 1) * _PAGE_SIZE).limit(_PAGE_SIZE)
    ).all()
    volunteers = db.session.scalars(
        db.select(Volunteer).filter_by(school_id=school.id).order_by(Volunteer.id.desc())
        .offset((volunteer_page - 1) * _PAGE_SIZE).limit(_PAGE_SIZE)
    ).all()

    # Each table's page hop must carry the other two tables' current pages too
    # (docs/ui-design/page-behaviour.md) — a single `target='main'` swap re-renders all three from
    # these args, so a plain hop on one leaves the others exactly where they were.
    common_args = {
        "teacher_page": teacher_page, "learner_page": learner_page, "volunteer_page": volunteer_page,
    }
    ctx = {
        "school": school,
        "teachers": teachers,
        "learners": learners,
        "volunteers": volunteers,
        "teacher_count": teacher_total,
        "learner_count": learner_total,
        "volunteer_count": volunteer_total,
        "teacher_page": teacher_page, "teacher_page_count": teacher_page_count,
        "learner_page": learner_page, "learner_page_count": learner_page_count,
        "volunteer_page": volunteer_page, "volunteer_page_count": volunteer_page_count,
        "common_args": common_args,
    }
    if wants_fragment():
        return render_template("@page_components/school_admin/people_results.jx", **ctx)
    return render_template("@pages/school_admin/people.jx", **ctx)

@school_admin_bp.route("/people/teachers/<int:teacher_id>")
def teacher_detail(teacher_id):
    """A preview, not the archive: the newest `_PREVIEW_SIZE` sessions, with
    the full filterable ledger one click away (docs/ui-design/page-behaviour.md)."""
    school = current_user.school
    teacher = db.first_or_404(
        db.select(Teacher).filter_by(id=teacher_id, school_id=school.id)
    )
    # Scoped to the learners' own records — one row per session logged, not
    # doubled up by each pair's mirrored volunteer record.
    attendance_stmt = (
        db.select(Attendance).join(Learner, Learner.id == Attendance.user_id)
        .where(Attendance.teacher_id == teacher.id)
    )
    attendance_total = db.session.scalar(
        db.select(db.func.count()).select_from(attendance_stmt.subquery())
    )
    total_hours = db.session.scalar(
        attendance_stmt.with_only_columns(db.func.coalesce(db.func.sum(Attendance.duration), 0.0))
    ) or 0.0
    attendance_records = db.session.scalars(
        attendance_stmt.order_by(Attendance.date.desc()).limit(_PREVIEW_SIZE)
    ).all()
    return render_template(
        "@pages/school_admin/teacher_detail.jx",
        school=school,
        teacher=teacher,
        attendance_records=attendance_records,
        attendance_total=attendance_total,
        total_hours=round(total_hours, 1),
    )

@school_admin_bp.route("/people/volunteers/<int:volunteer_id>")
def volunteer_detail(volunteer_id):
    """Preview of the volunteer's own sessions; link-out counts the matching
    learners' rows instead (same asymmetry as `teacher_volunteer_detail`)."""
    school = current_user.school
    volunteer = db.first_or_404(
        db.select(Volunteer).filter_by(id=volunteer_id, school_id=school.id)
    )
    attendance_stmt = db.select(Attendance).filter_by(user_id=volunteer.id)
    attendance_total = db.session.scalar(
        db.select(db.func.count()).select_from(attendance_stmt.subquery())
    )
    total_hours = db.session.scalar(
        attendance_stmt.with_only_columns(db.func.coalesce(db.func.sum(Attendance.duration), 0.0))
    ) or 0.0
    attendance_records = db.session.scalars(
        attendance_stmt.order_by(Attendance.date.desc()).limit(_PREVIEW_SIZE)
    ).all()
    return render_template(
        "@pages/school_admin/volunteer_detail.jx",
        school=school,
        volunteer=volunteer,
        attendance_records=attendance_records,
        attendance_total=attendance_total,
        total_hours=round(total_hours, 1),
    )

@school_admin_bp.route("/people/learners/<int:learner_id>")
def learner_detail(learner_id):
    """A preview, not the archive: the newest `_PREVIEW_SIZE` sessions, with
    the full filterable ledger one click away (docs/ui-design/page-behaviour.md)."""
    school = current_user.school
    learner = db.first_or_404(
        db.select(Learner).filter_by(id=learner_id, school_id=school.id)
    )
    attendance_stmt = db.select(Attendance).filter_by(user_id=learner.id)
    attendance_total = db.session.scalar(
        db.select(db.func.count()).select_from(attendance_stmt.subquery())
    )
    attendance_records = db.session.scalars(
        attendance_stmt.order_by(Attendance.date.desc()).limit(_PREVIEW_SIZE)
    ).all()
    assignment_stmt = db.select(WorksheetAssignment).filter_by(learner_id=learner.id)
    assignment_total = db.session.scalar(
        db.select(db.func.count()).select_from(assignment_stmt.subquery())
    )
    assignments = db.session.scalars(
        assignment_stmt.order_by(WorksheetAssignment.assigned_at.desc()).limit(_PREVIEW_SIZE)
    ).all()
    return render_template(
        "@pages/school_admin/learner_detail.jx",
        school=school,
        learner=learner,
        attendance_records=attendance_records,
        attendance_total=attendance_total,
        assignments=assignments,
        assignment_total=assignment_total,
    )

@school_admin_bp.route("/people/learners/<int:learner_id>/delete", methods=["POST"])
def delete_learner(learner_id):
    school = current_user.school
    learner = db.first_or_404(
        db.select(Learner).filter_by(id=learner_id, school_id=school.id)
    )

    roster_ops.delete_user(learner)
    flash("Learner deleted.", "success")
    return redirect(url_for("school_admin.people"))

@school_admin_bp.route("/people/volunteers/<int:volunteer_id>/delete", methods=["POST"])
def delete_volunteer(volunteer_id):
    school = current_user.school
    volunteer = db.first_or_404(
        db.select(Volunteer).filter_by(id=volunteer_id, school_id=school.id)
    )

    roster_ops.delete_user(volunteer)
    flash("Volunteer deleted.", "success")
    return redirect(url_for("school_admin.people"))

@school_admin_bp.route("/people/learners/<int:learner_id>/set-password", methods=["POST"])
def set_learner_password(learner_id):
    school = current_user.school
    learner = db.first_or_404(
        db.select(Learner).filter_by(id=learner_id, school_id=school.id)
    )
    new_password = clean_credential(request.form.get("password"))
    if not new_password:
        if wants_json():
            return jsonify(success=False, message="Password cannot be empty."), 400
        flash("Password cannot be empty.", "error")
        return redirect(url_for("school_admin.learner_detail", learner_id=learner_id))
    if has_whitespace(new_password):
        if wants_json():
            return jsonify(success=False, message="Password cannot contain spaces."), 400
        flash("Password cannot contain spaces.", "error")
        return redirect(url_for("school_admin.learner_detail", learner_id=learner_id))
    learner.set_password(new_password)
    db.session.commit()
    if wants_json():
        return jsonify(success=True, message="Password updated.")
    flash("Password updated.", "success")
    return redirect(url_for("school_admin.learner_detail", learner_id=learner_id))

@school_admin_bp.route("/donations")
def donations():
    """Paginated (25/page) donation ledger for the school admin's own school."""
    school = current_user.school
    stmt = db.select(Donation).filter_by(school_id=school.id)
    donation_count = db.session.scalar(
        db.select(db.func.count()).select_from(stmt.subquery())
    )
    page, page_count = clamp_page(donation_count, _PAGE_SIZE)
    total = (db.session.scalar(
        stmt.with_only_columns(db.func.coalesce(db.func.sum(Donation.amount), 0))
    ) or 0) / 100
    donations_list = db.session.scalars(
        stmt.order_by(Donation.created_at.desc())
        .offset((page - 1) * _PAGE_SIZE)
        .limit(_PAGE_SIZE)
    ).all()
    ctx = {
        "school": school,
        "donations": donations_list,
        "donation_count": donation_count,
        "total": total,
        "page": page,
        "page_count": page_count,
    }
    if wants_fragment():
        return render_template("@page_components/school_admin/donations_results.jx", **ctx)
    return render_template("@pages/school_admin/donations.jx", **ctx)

@school_admin_bp.route("/settings", methods=["GET", "POST"])
def settings():
    school = current_user.school
    if request.method == "POST":
        mission = request.form.get("mission_statement", "").strip()
        vol_domain = request.form.get("volunteer_domain", "").strip().lower() or None
        tch_domain = request.form.get("teacher_domain", "").strip().lower() or None

        if vol_domain and db.session.scalar(
            db.select(School).where(
                School.volunteer_domain == vol_domain, School.id != school.id
            )
        ):
            flash("Volunteer domain already claimed by another school.", "error")
            return render_template("@pages/school_admin/settings.jx", school=school)

        if tch_domain and db.session.scalar(
            db.select(School).where(
                School.teacher_domain == tch_domain, School.id != school.id
            )
        ):
            flash("Teacher domain already claimed by another school.", "error")
            return render_template("@pages/school_admin/settings.jx", school=school)

        school.mission_statement = mission or None
        school.volunteer_domain = vol_domain
        school.teacher_domain = tch_domain
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("school_admin.settings"))

    return render_template("@pages/school_admin/settings.jx", school=school)

@school_admin_bp.route("/attendance")
def attendance():
    """Paginated (25/page) attendance ledger, scoped to the school's own
    learners' records — the same set `teacher_detail`/`volunteer_detail`/
    `learner_detail` preview and link out to via `?teacher=`/`?volunteer=`/
    `?learner=`."""
    school = current_user.school
    learner_ids = db.session.scalars(
        db.select(Learner.id).filter_by(school_id=school.id)
    ).all()
    teacher_id_filter = request.args.get("teacher", type=int)
    learner_id_filter = request.args.get("learner", type=int)
    volunteer_id_filter = request.args.get("volunteer", type=int)

    stmt = db.select(Attendance).where(Attendance.user_id.in_(learner_ids))
    if teacher_id_filter:
        stmt = stmt.where(Attendance.teacher_id == teacher_id_filter)
    if learner_id_filter:
        stmt = stmt.where(Attendance.user_id == learner_id_filter)
    if volunteer_id_filter:
        stmt = stmt.where(Attendance.partner_id == volunteer_id_filter)

    total = db.session.scalar(db.select(db.func.count()).select_from(stmt.subquery()))
    page, page_count = clamp_page(total, _PAGE_SIZE)
    total_hours = round(
        db.session.scalar(
            stmt.with_only_columns(db.func.coalesce(db.func.sum(Attendance.duration), 0.0))
        ) or 0.0, 1
    )
    records = db.session.scalars(
        stmt.order_by(Attendance.date.desc())
        .offset((page - 1) * _PAGE_SIZE)
        .limit(_PAGE_SIZE)
    ).all()
    ctx = {
        "school": school,
        "records": records,
        "record_count": total,
        "total_hours": total_hours,
        "page": page,
        "page_count": page_count,
        "page_args": {
            "teacher": teacher_id_filter or None,
            "learner": learner_id_filter or None,
            "volunteer": volunteer_id_filter or None,
        },
    }
    if wants_fragment():
        return render_template("@page_components/school_admin/attendance_results.jx", **ctx)
    return render_template("@pages/school_admin/attendance.jx", **ctx)
