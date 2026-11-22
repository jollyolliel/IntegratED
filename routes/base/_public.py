import os

from flask import abort, redirect, request, send_from_directory, url_for

from extensions import db
from helpers.analytics import capture_event
from helpers.images import IMAGE_FILENAME_RE, image_key, image_mimetype
from helpers.programme_stats import programme_stats
from helpers.render import render_template
from helpers.utils import clamp_page, wants_fragment
from models import Donation, Learner, School, Volunteer
from routes.base import base_bp

_SCHOOLS_PAGE_SIZE = 25
_ARTICLES_PAGE_SIZE = 25

# The landing page's "try a question" demo. Copied verbatim from the English
# Grammar course in the content questions.json (a test holds them to that), so the
# demo is the real content a learner meets, not marketing copy. English on
# purpose: English is the subject being taught. `picture` picks the
# illustration pages/index.jx shows beside the question.
LANDING_DEMO_QUESTIONS = [
    {
        "picture": "sun",
        "question_prompt": "Choose the greeting",
        "question_text": "You meet someone in the morning. What do you say?",
        "options": ["Good night", "Good morning", "Goodbye", "See you later"],
        "answer": "Good morning",
    },
    {
        "picture": "letters",
        "question_prompt": "Find the vowel",
        "question_text": "Which one is a vowel?",
        "options": ["B", "C", "E", "G"],
        "answer": "E",
    },
    {
        "picture": "book_on_table",
        "question_prompt": "Choose the preposition",
        "question_text": "The book is ___ the table. (The book is touching the top of the table.)",
        "options": ["in", "under", "on", "behind"],
        "answer": "on",
    },
]


@base_bp.route("/favicon.ico")
def favicon():
    """Serves favicon.ico out of templates/, requested unprompted at the domain root."""
    template_dir = os.path.join(os.path.dirname(base_bp.root_path), "templates")
    return send_from_directory(template_dir, "favicon.ico", mimetype="image/vnd.microsoft.icon")


@base_bp.route("/")
def home():
    """Public landing page — the try-a-question demo, impact stats, latest 3 articles."""
    from models import Article
    capture_event(None, "page_viewed", properties={"page": "home"})

    latest_articles = db.session.scalars(
        db.select(Article).order_by(Article.created_at.desc()).limit(3)
    ).all()

    return render_template(
        "@pages/index.jx",
        stats=programme_stats(),
        latest_articles=latest_articles,
        demo_questions=LANDING_DEMO_QUESTIONS,
    )


def _school_stats_query():
    """Every school with its donations raised (cents) and user count, each from
    its own grouped subquery against the live `Donation`/`Learner`/`Volunteer` tables."""
    donation_totals = (
        db.select(Donation.school_id, db.func.sum(Donation.amount).label("total"))
        .group_by(Donation.school_id).subquery()
    )
    learner_counts = (
        db.select(Learner.school_id, db.func.count(Learner.id).label("cnt"))
        .group_by(Learner.school_id).subquery()
    )
    volunteer_counts = (
        db.select(Volunteer.school_id, db.func.count(Volunteer.id).label("cnt"))
        .group_by(Volunteer.school_id).subquery()
    )
    donations_col = db.func.coalesce(donation_totals.c.total, 0)
    users_col = db.func.coalesce(learner_counts.c.cnt, 0) + db.func.coalesce(volunteer_counts.c.cnt, 0)

    query = (
        db.select(School, donations_col.label("donations_cents"), users_col.label("user_count"))
        .outerjoin(donation_totals, donation_totals.c.school_id == School.id)
        .outerjoin(learner_counts, learner_counts.c.school_id == School.id)
        .outerjoin(volunteer_counts, volunteer_counts.c.school_id == School.id)
    )
    return query, donations_col, users_col


def _stat_rows(rows):
    return [
        {
            "school": school,
            "total_donations": (donations_cents or 0) / 100, "user_count": user_count or 0,
        }
        for school, donations_cents, user_count in rows
    ]


@base_bp.route("/schools")
def schools():
    """Public school directory: the top three by donations raised (only on an
    unsearched first page), then every school A–Z, searchable by name and
    paginated at `_SCHOOLS_PAGE_SIZE`."""
    q = request.args.get("q", "").strip()[:100]
    capture_event(None, "page_viewed", properties={"page": "schools", "searched": bool(q)})

    query, donations_col, users_col = _school_stats_query()
    name_filter = []
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        name_filter = [School.name.ilike(f"%{escaped}%", escape="\\")]

    total = db.session.scalar(db.select(db.func.count()).select_from(School).where(*name_filter))
    page, page_count = clamp_page(total, _SCHOOLS_PAGE_SIZE)
    rows = db.session.execute(
        query.where(*name_filter).order_by(School.name)
        .offset((page - 1) * _SCHOOLS_PAGE_SIZE).limit(_SCHOOLS_PAGE_SIZE)
    ).all()
    top_rows = []
    if not q and page == 1:
        top_rows = db.session.execute(
            query.order_by(donations_col.desc(), users_col.desc(), School.name).limit(3)
        ).all()
    ctx = {
        "school_stats": _stat_rows(rows),
        "top_schools": _stat_rows(top_rows),
        "school_count": total,
        "q": q,
        "page": page,
        "page_count": page_count,
    }
    if wants_fragment():
        return render_template("@page_components/public/schools_results.jx", **ctx)
    return render_template("@pages/schools.jx", **ctx)


@base_bp.route("/schools/<int:id>")
def school_detail(id):
    """One school's public page: photo, logo, mission and its own impact,
    counted from its learners, volunteers, attendance and donations."""
    school = db.get_or_404(School, id)
    capture_event(None, "page_viewed", properties={"page": "school_detail", "school_id": school.id})

    return render_template("@pages/school_detail.jx", school=school, impact=programme_stats(school.id))


@base_bp.route("/about")
def about():
    """Public about page — impact stats, team roster, editable site copy."""
    from models import SiteContent, TeamMember
    capture_event(None, "page_viewed", properties={"page": "about"})

    team_members = db.session.scalars(db.select(TeamMember)).all()
    site_content = {sc.key: sc.value for sc in db.session.scalars(db.select(SiteContent)).all()}

    return render_template(
        "@pages/about.jx",
        stats=programme_stats(),
        team_members=team_members,
        site_content=site_content
    )


@base_bp.route("/error")
def cause_error():
    """Renders the error page directly (no exception raised) for manual style checks."""
    return render_template("@pages/error.jx")


@base_bp.route("/news")
def articles_list():
    """Public News index of articles, newest first, paginated at `_ARTICLES_PAGE_SIZE`."""
    from models import Article
    total = db.session.scalar(db.select(db.func.count()).select_from(Article))
    page, page_count = clamp_page(total, _ARTICLES_PAGE_SIZE)
    articles = db.session.scalars(
        db.select(Article)
        .order_by(Article.created_at.desc())
        .offset((page - 1) * _ARTICLES_PAGE_SIZE)
        .limit(_ARTICLES_PAGE_SIZE)
    ).all()
    ctx = {"articles": articles, "page": page, "page_count": page_count}
    if wants_fragment():
        return render_template("@page_components/public/articles_results.jx", **ctx)
    return render_template("@pages/articles.jx", **ctx)


@base_bp.route("/news/<int:id>")
def article_detail(id):
    """Public single-article page; 404s on an unknown id."""
    from models import Article
    article = db.get_or_404(Article, id)
    return render_template("@pages/article_detail.jx", article=article)


@base_bp.route("/news/images/<filename>")
def article_image(filename):
    """An article's hero image, public and cached for a year: stored names are
    random and never reused, so a replaced image gets a new URL."""
    from helpers.storage import get_bucket
    storage = get_bucket()
    if not IMAGE_FILENAME_RE.fullmatch(filename) or not storage.exists(image_key(filename)):
        abort(404)
    response = storage.send(image_key(filename), image_mimetype(filename))
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@base_bp.route("/articles")
@base_bp.route("/articles/<int:id>")
def legacy_articles(id=None):
    """The News pages' old `/articles` URLs, moved for good."""
    if id is None:
        return redirect(url_for("base.articles_list", page=request.args.get("page")), 301)
    return redirect(url_for("base.article_detail", id=id), 301)


@base_bp.route("/terms")
def terms():
    """Static terms-of-service page."""
    capture_event(None, "page_viewed", properties={"page": "terms"})
    return render_template("@pages/legal/terms.jx")


@base_bp.route("/privacy")
def privacy():
    """Static privacy-policy page."""
    capture_event(None, "page_viewed", properties={"page": "privacy"})
    return render_template("@pages/legal/privacy.jx")
