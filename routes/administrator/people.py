"""School/user CRUD, the org dashboard, and the donations view — the admin
panel's core people-and-org-stats routes."""

from flask import flash, jsonify, redirect, request, url_for
from flask_login import login_required
from sqlalchemy import text

from extensions import db
from helpers import roster_ops
from helpers.announcements import get_pending_announcement
from helpers.auth_utils import clean_credential, has_whitespace, username_taken
from helpers.current_user import current_administrator as current_user
from helpers.render import render_template
from helpers.utils import clamp_page, wants_fragment, wants_json
from models import (
    Administrator,
    Article,
    Attendance,
    Donation,
    Learner,
    School,
    SchoolAdmin,
    SiteContent,
    Teacher,
    TeamMember,
    User,
    Volunteer,
)
from routes.administrator import admin_required, administrator_bp

# Staff-facing sheets (schools/users/donations) page at 25 — the raw DB table
# browser (db_console.py) is a different, 50-row convention.
_PAGE_SIZE = 25
# School-detail people/donations tables preview this many, newest first, then
# link out to the paged /admin/users or /admin/donations view (docs/ui-design/page-behaviour.md).
_PREVIEW_SIZE = 7

# ===================== Dashboard =====================

@administrator_bp.route("/dashboard")
@login_required
@admin_required
def dashboard():
    """Org-wide totals plus the CMS content (articles/team/site copy) the
    dashboard template edits inline — this page doubles as the CMS editor,
    not just a stats view."""
    total_schools = db.session.scalar(db.select(db.func.count()).select_from(School))
    total_learners = db.session.scalar(db.select(db.func.count()).select_from(Learner))
    total_volunteers = db.session.scalar(db.select(db.func.count()).select_from(Volunteer))
    total_teachers = db.session.scalar(db.select(db.func.count()).select_from(Teacher))
    total_donations_cents = db.session.scalar(db.select(db.func.sum(Donation.amount))) or 0
    total_hours = Attendance.programme_hours()
    recent_donations = db.session.scalars(
        db.select(Donation).order_by(Donation.created_at.desc()).limit(5)
    ).all()

    # The dashboard is a CMS editor for many things, not an articles archive —
    # this card previews the newest few and links out to the public list
    # (docs/ui-design/page-behaviour.md: a table on a page about something else previews).
    article_count = db.session.scalar(db.select(db.func.count()).select_from(Article))
    articles = db.session.scalars(
        db.select(Article).order_by(Article.created_at.desc()).limit(_PREVIEW_SIZE)
    ).all()
    team_members = db.session.scalars(db.select(TeamMember)).all()
    site_content = {sc.key: sc.value for sc in db.session.scalars(db.select(SiteContent)).all()}

    return render_template(
        "@pages/administrator/dashboard.jx",
        total_schools=total_schools,
        total_learners=total_learners,
        total_volunteers=total_volunteers,
        total_teachers=total_teachers,
        total_donations=total_donations_cents / 100,
        total_hours=round(total_hours, 1),
        recent_donations=recent_donations,
        articles=articles,
        article_count=article_count,
        team_members=team_members,
        site_content=site_content,
        pending_announcement=get_pending_announcement(current_user),
    )

# ===================== Schools =====================

@administrator_bp.route("/schools")
@login_required
@admin_required
def schools():
    """Paginated (25/page) school list with per-school headcounts and donation
    total, scoped to the page's own rows, never the whole table."""
    total = db.session.scalar(db.select(db.func.count()).select_from(School))
    page, page_count = clamp_page(total, _PAGE_SIZE)
    page_schools = db.session.scalars(
        db.select(School)
        .order_by(School.name.asc())
        .offset((page - 1) * _PAGE_SIZE)
        .limit(_PAGE_SIZE)
    ).all()
    school_stats = []
    for school in page_schools:
        school_stats.append({
            "school": school,
            "learner_count": db.session.scalar(
                db.select(db.func.count()).select_from(Learner).filter_by(school_id=school.id)
            ),
            "volunteer_count": db.session.scalar(
                db.select(db.func.count()).select_from(Volunteer).filter_by(school_id=school.id)
            ),
            "teacher_count": db.session.scalar(
                db.select(db.func.count()).select_from(Teacher).filter_by(school_id=school.id)
            ),
            "donations_total": (
                db.session.scalar(
                    db.select(db.func.sum(Donation.amount)).filter_by(school_id=school.id)
                ) or 0
            ) / 100,
        })
    ctx = {"school_stats": school_stats, "page": page, "page_count": page_count}
    if wants_fragment():
        return render_template("@page_components/administrator/schools_results.jx", **ctx)
    return render_template("@pages/administrator/schools.jx", **ctx)

@administrator_bp.route("/schools/new", methods=["GET", "POST"])
@login_required
@admin_required
def create_school():
    """Create a school and, optionally, its first `SchoolAdmin` in one step —
    the admin account isn't required, but a school with no admin has no one
    who can log in and manage it until one is added later."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        volunteer_domain = request.form.get("volunteer_domain", "").strip().lower() or None
        teacher_domain = request.form.get("teacher_domain", "").strip().lower() or None
        mission_statement = request.form.get("mission_statement", "").strip() or None
        admin_username = clean_credential(request.form.get("admin_username"))
        admin_password = clean_credential(request.form.get("admin_password"))
        admin_name = request.form.get("admin_name", "").strip()

        if not name:
            flash("School name is required.", "error")
            return render_template("@pages/administrator/school_form.jx")

        if db.session.scalar(db.select(School).filter_by(name=name)):
            flash("A school with that name already exists.", "error")
            return render_template("@pages/administrator/school_form.jx")

        if has_whitespace(admin_username) or has_whitespace(admin_password):
            flash("Admin username and password cannot contain spaces.", "error")
            return render_template("@pages/administrator/school_form.jx")

        if admin_username and username_taken(admin_username):
            flash("Admin username already exists.", "error")
            return render_template("@pages/administrator/school_form.jx")

        school = School(
            name=name,
            volunteer_domain=volunteer_domain,
            teacher_domain=teacher_domain,
            mission_statement=mission_statement,
        )
        db.session.add(school)
        db.session.flush()

        if admin_username and admin_password:
            school_admin = SchoolAdmin(
                username=admin_username,
                name=admin_name or admin_username,
                school_id=school.id,
            )
            school_admin.set_password(admin_password)
            db.session.add(school_admin)

        db.session.commit()
        flash(f'School "{name}" created.', "success")
        return redirect(url_for("administrator.schools"))

    return render_template("@pages/administrator/school_form.jx")

@administrator_bp.route("/schools/<int:school_id>")
@login_required
@admin_required
def school_detail(school_id):
    """One school — previews (`_PREVIEW_SIZE` newest) of its people and
    donations, each linking out to its paged `/admin/users` or
    `/admin/donations` view, plus hours summed only over its learners (a
    volunteer's own attendance rows would double the count since each
    session already has a matching learner row)."""
    school = db.get_or_404(School, school_id)
    learner_count = db.session.scalar(
        db.select(db.func.count()).select_from(Learner).filter_by(school_id=school_id)
    )
    volunteer_count = db.session.scalar(
        db.select(db.func.count()).select_from(Volunteer).filter_by(school_id=school_id)
    )
    teacher_count = db.session.scalar(
        db.select(db.func.count()).select_from(Teacher).filter_by(school_id=school_id)
    )
    donation_count = db.session.scalar(
        db.select(db.func.count()).select_from(Donation).filter_by(school_id=school_id)
    )

    learners = db.session.scalars(
        db.select(Learner).filter_by(school_id=school_id).order_by(Learner.id.desc()).limit(_PREVIEW_SIZE)
    ).all()
    volunteers = db.session.scalars(
        db.select(Volunteer).filter_by(school_id=school_id).order_by(Volunteer.id.desc()).limit(_PREVIEW_SIZE)
    ).all()
    teachers = db.session.scalars(
        db.select(Teacher).filter_by(school_id=school_id).order_by(Teacher.id.desc()).limit(_PREVIEW_SIZE)
    ).all()
    donations = db.session.scalars(
        db.select(Donation)
        .filter_by(school_id=school_id)
        .order_by(Donation.created_at.desc())
        .limit(_PREVIEW_SIZE)
    ).all()

    total_donations = (
        db.session.scalar(db.select(db.func.sum(Donation.amount)).filter_by(school_id=school_id)) or 0
    ) / 100
    hours = db.session.scalar(
        db.select(db.func.sum(Attendance.duration))
        .join(Learner, Learner.id == Attendance.user_id)
        .where(Learner.school_id == school_id, Attendance.is_present)
    ) or 0
    return render_template(
        "@pages/administrator/school_detail.jx",
        school=school,
        learners=learners,
        volunteers=volunteers,
        teachers=teachers,
        donations=donations,
        learner_count=learner_count,
        volunteer_count=volunteer_count,
        teacher_count=teacher_count,
        donation_count=donation_count,
        total_donations=total_donations,
        total_hours=round(hours, 1),
    )

@administrator_bp.route("/schools/<int:school_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_school(school_id):
    """Delete a school, unlinking its people (learners/volunteers/teachers
    survive as unaffiliated accounts) and its donations, and dissolving
    their matches."""
    school = db.get_or_404(School, school_id)
    # Dissolve matches too — otherwise pairs survive with is_matched=True and
    # dangling volunteer_id pointers after the school boundary disappears.
    db.session.execute(
        db.update(Learner)
        .where(Learner.school_id == school_id)
        .values(school_id=None, teacher_id=None, volunteer_id=None, is_matched=False)
    )
    db.session.execute(
        db.update(Volunteer)
        .where(Volunteer.school_id == school_id)
        .values(school_id=None, teacher_id=None, is_matched=False)
    )
    db.session.execute(
        db.update(Teacher).where(Teacher.school_id == school_id).values(school_id=None)
    )
    # Donations stay in the totals, no longer credited to any school.
    db.session.execute(
        db.update(Donation).where(Donation.school_id == school_id).values(school_id=None)
    )
    if school.school_admin:
        db.session.delete(school.school_admin)
    db.session.delete(school)
    db.session.commit()
    if wants_json():
        return jsonify(success=True, message=f'School "{school.name}" deleted.')
    flash(f'School "{school.name}" deleted.', "success")
    return redirect(url_for("administrator.schools"))

# ===================== Users =====================

@administrator_bp.route("/users")
@login_required
@admin_required
def users():
    """Cross-school user list, filterable by role and/or school, paginated at
    25/page (`_PAGE_SIZE`). A type+school filter pushes `LIMIT`/`OFFSET` into
    SQL on the concrete subclass table; "all types" instead collects matching
    ids first (id-only columns, not full rows), since `User` carries no
    `school_id` of its own, then pages that id list before loading only the
    page's own `User` rows.

    `display_email`/`display_username`/`display_school` are resolved here,
    not read as `.email`/`.username`/`.school` in the template: those are
    joined-table-inheritance columns deferred onto the subclass table, and an
    orphaned `users` row (no matching subclass row) raises `KeyError` on
    access — which Jinja's `is defined` test does not catch, so it must be
    swallowed here or the page 500s."""
    user_type_filter = request.args.get("type", "all")
    school_id_filter = request.args.get("school_id", type=int)

    type_model = {
        "learner": Learner, "volunteer": Volunteer,
        "teacher": Teacher, "school_admin": SchoolAdmin,
    }.get(user_type_filter)

    if type_model is not None:
        stmt = db.select(type_model)
        if school_id_filter:
            stmt = stmt.filter_by(school_id=school_id_filter)
        total = db.session.scalar(
            db.select(db.func.count()).select_from(stmt.subquery())
        )
        page, page_count = clamp_page(total, _PAGE_SIZE)
        all_users = db.session.scalars(
            stmt.order_by(type_model.id.desc())
            .offset((page - 1) * _PAGE_SIZE)
            .limit(_PAGE_SIZE)
        ).all()
    else:
        if school_id_filter:
            l_ids = db.session.scalars(db.select(Learner.id).filter_by(school_id=school_id_filter)).all()
            v_ids = db.session.scalars(db.select(Volunteer.id).filter_by(school_id=school_id_filter)).all()
            t_ids = db.session.scalars(db.select(Teacher.id).filter_by(school_id=school_id_filter)).all()
            sa_ids = db.session.scalars(db.select(SchoolAdmin.id).filter_by(school_id=school_id_filter)).all()
            all_ids = sorted(list(l_ids) + list(v_ids) + list(t_ids) + list(sa_ids), reverse=True)
        else:
            all_ids = db.session.scalars(db.select(User.id).order_by(User.id.desc())).all()
        total = len(all_ids)
        page, page_count = clamp_page(total, _PAGE_SIZE)
        page_ids = all_ids[(page - 1) * _PAGE_SIZE : page * _PAGE_SIZE]
        by_id = {u.id: u for u in db.session.scalars(db.select(User).where(User.id.in_(page_ids))).all()}
        all_users = [by_id[i] for i in page_ids if i in by_id]

    # Base `User` rows that subclass `user_type` (learner/administrator/
    # school_admin) lazy-load their username/email/school from the subclass
    # table. If that row is missing (orphaned `users` row), SQLAlchemy raises
    # a KeyError on access instead of AttributeError, which Jinja's `is
    # defined` test does not catch. A subclass that has no such column at all
    # (e.g. `Administrator` has no `email`) raises a plain AttributeError
    # instead. Resolve safely here so the page can't 500 either way.
    for u in all_users:
        try:
            u.display_email = u.email
        except (KeyError, AttributeError):
            u.display_email = None
        try:
            u.display_username = u.username
        except (KeyError, AttributeError):
            u.display_username = None
        try:
            u.display_school = u.school
        except (KeyError, AttributeError):
            u.display_school = None

    schools = db.session.scalars(db.select(School)).all()
    # The filter values a page hop must not drop — see docs/ui-design/page-behaviour.md.
    page_args = {"type": user_type_filter, "school_id": school_id_filter or None}
    ctx = {
        "users": all_users,
        "user_type": user_type_filter,
        "schools": schools,
        "selected_school_id": school_id_filter,
        "page": page,
        "page_count": page_count,
        "page_args": page_args,
        "total_users": total,
    }
    if wants_fragment():
        return render_template("@page_components/administrator/users_results.jx", **ctx)
    return render_template("@pages/administrator/users.jx", **ctx)

@administrator_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    """Delete any user, admins deleting themselves excepted (would sever the
    session mid-request). Learners, volunteers, teachers and administrators
    go through `roster_ops.delete_user`, so every role's cascade runs in one
    transaction (an administrator's articles pass to the one deleting them). An orphaned `users` row (base row with
    no matching subclass row) is detected via raw SQL and deleted with a
    plain `DELETE FROM users` — see comment below for why."""
    user = db.get_or_404(User, user_id)

    if user.id == current_user.id:
        if wants_json():
            return jsonify(success=False, message="Cannot delete your own account."), 400
        flash("Cannot delete your own account.", "error")
        return redirect(url_for("administrator.users"))

    # `users` rows are joined-table inheritance: a row can be orphaned (no
    # matching row in the subtype table, e.g. from a manual DB edit). Loading
    # `user` via the base `User` mapper leaves subtype columns deferred, and
    # for an orphan those deferred loaders raise KeyError instead of
    # returning None/empty — both on direct attribute access and when
    # SQLAlchemy's flush walks relationship dependencies for `db.session.delete`.
    # Check for the subtype row via raw SQL first and short-circuit to a plain
    # row delete so we never touch those deferred attributes for an orphan.
    subtype_table = {
        "learner": Learner.__tablename__,
        "volunteer": Volunteer.__tablename__,
        "teacher": Teacher.__tablename__,
        "administrator": Administrator.__tablename__,
        "school_admin": SchoolAdmin.__tablename__,
    }.get(user.user_type)

    has_subtype_row = subtype_table and db.session.execute(
        text(f"SELECT 1 FROM {subtype_table} WHERE id = :id"), {"id": user_id}
    ).first()

    if not has_subtype_row:
        db.session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        db.session.commit()
        if wants_json():
            return jsonify(success=True, message="User deleted.")
        flash("User deleted.", "success")
        return redirect(url_for("administrator.users"))

    heir = db.session.get(Administrator, current_user.id) if user.user_type == "administrator" else None
    roster_ops.delete_user(user, heir=heir)

    if wants_json():
        return jsonify(success=True, message="User deleted.")
    flash("User deleted.", "success")
    return redirect(url_for("administrator.users"))

# ===================== Donations =====================

@administrator_bp.route("/donations")
@login_required
@admin_required
def donations():
    """Paginated (25/page) donation list, optionally scoped to one
    `?school_id=` (the school-detail preview's link-out). Donations with no
    `school_id` group under "Unattributed" in the per-school breakdown, which
    is its own grouped-sum query covering every matching donation, not just
    the current page."""
    school_id_filter = request.args.get("school_id", type=int)

    stmt = db.select(Donation)
    if school_id_filter:
        stmt = stmt.filter_by(school_id=school_id_filter)

    total_amount = db.session.scalar(
        stmt.with_only_columns(db.func.coalesce(db.func.sum(Donation.amount), 0))
    )
    total = total_amount / 100
    donation_count = db.session.scalar(
        db.select(db.func.count()).select_from(stmt.subquery())
    )
    page, page_count = clamp_page(donation_count, _PAGE_SIZE)
    page_donations = db.session.scalars(
        stmt.order_by(Donation.created_at.desc())
        .offset((page - 1) * _PAGE_SIZE)
        .limit(_PAGE_SIZE)
    ).all()

    by_school_rows = db.session.execute(
        stmt.outerjoin(School, Donation.school_id == School.id)
        .with_only_columns(
            db.func.coalesce(School.name, "Unattributed"),
            db.func.sum(Donation.amount),
        )
        .group_by(db.func.coalesce(School.name, "Unattributed"))
    ).all()
    by_school = sorted(
        ((name, amount / 100) for name, amount in by_school_rows),
        key=lambda pair: pair[1],
        reverse=True,
    )

    ctx = {
        "donations": page_donations,
        "total": total,
        "donation_count": donation_count,
        "by_school": by_school,
        "page": page,
        "page_count": page_count,
        "page_args": {"school_id": school_id_filter or None},
        "school_filter": db.session.get(School, school_id_filter) if school_id_filter else None,
    }
    if wants_fragment():
        return render_template("@page_components/administrator/donations_results.jx", **ctx)
    return render_template("@pages/administrator/donations.jx", **ctx)
