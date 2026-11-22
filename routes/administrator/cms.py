import uuid
from types import SimpleNamespace

from flask import flash, jsonify, redirect, request, url_for
from flask_login import login_required

from extensions import db
from helpers.analytics import capture_event
from helpers.current_user import current_administrator as current_user
from helpers.images import IMAGE_TYPES, MAX_IMAGE_BYTES, image_key, sniff_image
from helpers.render import render_template
from helpers.utils import wants_json
from models import Article, SiteContent, TeamMember
from routes.administrator import admin_required, administrator_bp


@administrator_bp.route("/settings", methods=["POST"])
@login_required
@admin_required
def update_settings():
    """Upsert every submitted form field as a `SiteContent` key/value pair —
    whatever keys the settings form sends become the whole set of accepted
    keys; there's no fixed schema enforced here."""
    for key, value in request.form.items():
        content = db.session.scalar(db.select(SiteContent).filter_by(key=key))
        if content:
            content.value = value
        else:
            db.session.add(SiteContent(key=key, value=value))
    db.session.commit()
    flash("Settings updated successfully!", "success")
    return redirect(url_for("administrator.dashboard"))

@administrator_bp.route("/team/new", methods=["GET", "POST"])
@login_required
@admin_required
def create_team_member():
    """Add a public "About" page team member."""
    if request.method == "POST":
        name = request.form.get("name")
        job = request.form.get("job")
        strengths = request.form.get("strengths")
        bio = request.form.get("bio")

        if not name:
            flash("Name is required.", "error")
            return render_template("@pages/administrator/edit_team.jx", member=None)

        member = TeamMember(name=name, job=job, strengths=strengths, bio=bio)
        db.session.add(member)
        db.session.commit()
        flash("Team member added successfully!", "success")
        return redirect(url_for("administrator.dashboard"))

    return render_template("@pages/administrator/edit_team.jx", member=None)

@administrator_bp.route("/team/edit/<int:id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_team_member(id):
    """Edit a team member's public profile fields."""
    member = db.get_or_404(TeamMember, id)
    if request.method == "POST":
        member.name = request.form.get("name", "")
        member.job = request.form.get("job")
        member.strengths = request.form.get("strengths")
        member.bio = request.form.get("bio")
        db.session.commit()
        flash("Team member updated successfully!", "success")
        return redirect(url_for("administrator.dashboard"))

    return render_template("@pages/administrator/edit_team.jx", member=member)

@administrator_bp.route("/team/delete/<int:id>", methods=["POST"])
@login_required
@admin_required
def delete_team_member(id):
    """Remove a team member from the public "About" page."""
    member = db.get_or_404(TeamMember, id)
    db.session.delete(member)
    db.session.commit()
    if wants_json():
        return jsonify(success=True, message="Team member removed successfully!")
    flash("Team member removed successfully!", "success")
    return redirect(url_for("administrator.dashboard"))

def _hero_upload() -> tuple[tuple[bytes, str] | None, str | None]:
    """Read and check the article form's hero image file.

    Returns:
        tuple: `((bytes, extension), None)` for a valid image, `(None, None)`
            when no file was chosen, or `(None, error message)`.
    """
    file = request.files.get("hero_image")
    if not file or not file.filename:
        return None, None
    data = file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        return None, "Hero images must be 5 MB or smaller."
    ext = sniff_image(data)
    if ext is None:
        return None, "Hero images must be a PNG, JPEG, WebP or GIF."
    return (data, ext), None


def _apply_hero_image(article: Article, upload: tuple[bytes, str] | None) -> str | None:
    """Store a new hero image or honour "remove image" on the article (uncommitted).

    Args:
        article (Article): The article being saved.
        upload (tuple[bytes, str] | None): A checked image from `_hero_upload`.

    Returns:
        str | None: The replaced image's filename, to delete once the commit succeeds.
    """
    from helpers.storage import get_bucket
    old = article.hero_image
    if upload:
        data, ext = upload
        name = f"{uuid.uuid4().hex}.{ext}"
        get_bucket().write(image_key(name), data, IMAGE_TYPES[ext])
        article.hero_image = name
    elif request.form.get("remove_hero_image"):
        article.hero_image = None
    return old if old and old != article.hero_image else None


def _delete_replaced_image(filename: str | None) -> None:
    """Delete a hero image the article no longer uses."""
    from helpers.storage import get_bucket
    if filename:
        get_bucket().delete(image_key(filename))


@administrator_bp.route("/articles/new", methods=["GET", "POST"])
@login_required
@admin_required
def create_article():
    """Publish a blog article, authored as the current admin — Markdown
    content, rendered on the public side, with an optional hero image."""
    if request.method == "POST":
        title = request.form.get("title")
        content = request.form.get("content")
        upload, error = _hero_upload()

        if not title or not content or error:
            flash(error or "Title and content are required.", "error")
            draft = SimpleNamespace(title=title or "", content_markdown=content or "", hero_image=None)
            return render_template("@pages/administrator/edit_article.jx", article=None, draft=draft)

        article = Article(title=title, content_markdown=content, author_id=current_user.id)
        _apply_hero_image(article, upload)
        db.session.add(article)
        db.session.commit()
        capture_event(str(current_user.id), "article_published",
                      {"article_id": article.id, "has_hero_image": bool(article.hero_image)})
        flash("Article created successfully!", "success")
        return redirect(url_for("administrator.dashboard"))

    return render_template("@pages/administrator/edit_article.jx", article=None)

@administrator_bp.route("/articles/edit/<int:id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_article(id):
    """Edit an existing article's title, content and hero image — author is
    not reassigned, stays whoever created it."""
    article = db.get_or_404(Article, id)
    if request.method == "POST":
        article.title = request.form.get("title", "")
        article.content_markdown = request.form.get("content", "")
        upload, error = _hero_upload()

        if not article.title or not article.content_markdown or error:
            flash(error or "Title and content are required.", "error")
            return render_template("@pages/administrator/edit_article.jx", article=article)

        replaced = _apply_hero_image(article, upload)
        db.session.commit()
        _delete_replaced_image(replaced)
        capture_event(str(current_user.id), "article_updated",
                      {"article_id": article.id, "has_hero_image": bool(article.hero_image)})
        flash("Article updated successfully!", "success")
        return redirect(url_for("administrator.dashboard"))

    return render_template("@pages/administrator/edit_article.jx", article=article)

@administrator_bp.route("/articles/delete/<int:id>", methods=["POST"])
@login_required
@admin_required
def delete_article(id):
    """Permanently remove a published article and its hero image."""
    article = db.get_or_404(Article, id)
    hero_image = article.hero_image
    db.session.delete(article)
    db.session.commit()
    _delete_replaced_image(hero_image)
    if wants_json():
        return jsonify(success=True, message="Article deleted successfully!")
    flash("Article deleted successfully!", "success")
    return redirect(url_for("administrator.dashboard"))
