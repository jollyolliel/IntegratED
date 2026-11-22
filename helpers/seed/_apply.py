"""Writing a validated `seed.toml` into the database: one insert-only function per section."""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING, Any, TypedDict

from extensions import db
from helpers.auth_utils import find_by_email, find_by_username
from helpers.images import IMAGE_TYPES, image_key, sniff_image
from helpers.seed._config import (
    FILES_DIR,
    USER_TYPES,
    SeedConfig,
    SeedError,
    check_files,
    identities,
)

if TYPE_CHECKING:
    from helpers.storage import Bucket
    from models import School, Teacher, User

__all__ = [
    "SeedCounts",
    "apply_articles",
    "apply_config",
    "apply_schools",
    "apply_site_content",
    "apply_team_members",
    "apply_users",
]


class SeedCounts(TypedDict):
    """Rows created per `seed.toml` section."""

    schools: int
    users: int
    articles: int
    team_members: int
    site_content: int


def _find_user(key: str) -> User | None:
    return find_by_username(key) or find_by_email(key)


def _make_user(kind: str, spec: dict[str, Any], school: School | None, teacher: User | None) -> User:
    from models import Administrator, Learner, SchoolAdmin, Teacher, Volunteer

    name = spec.get("name")
    school_id = school.id if school else None
    teacher_id = teacher.id if teacher else None
    user: Administrator | SchoolAdmin | Teacher | Volunteer | Learner
    if kind == "administrator":
        user = Administrator(username=spec["username"], name=name)
    elif kind == "school_admin":
        user = SchoolAdmin(username=spec["username"], name=name, school_id=school_id)
    elif kind == "teacher":
        user = Teacher(
            email=spec["email"], google_sub=f"seed:{spec['email']}", name=name, school_id=school_id,
        )
    elif kind == "volunteer":
        user = Volunteer(
            email=spec["email"], google_sub=f"seed:{spec['email']}",
            name=name, school_id=school_id, teacher_id=teacher_id,
            completed_survey=spec.get("completed_survey", True),
        )
    else:
        user = Learner(
            username=spec["username"], name=name, school_id=school_id, teacher_id=teacher_id,
            completed_survey=spec.get("completed_survey", True),
            completed_map_test=spec.get("completed_map_test", True),
        )
    if isinstance(user, (Administrator, SchoolAdmin, Learner)):
        user.set_password(spec["password"])
    return user


def apply_schools(config: SeedConfig) -> int:
    """Insert each school not already there (by name). Photo and logo are paths under `static/`."""
    from models import School

    created = 0
    for spec in config["schools"]:
        if db.session.scalar(db.select(School).filter_by(name=spec["name"])) is not None:
            continue
        db.session.add(School(
            name=spec["name"],
            mission_statement=spec.get("mission_statement"),
            location=spec.get("location"),
            volunteer_domain=spec.get("volunteer_domain"),
            teacher_domain=spec.get("teacher_domain"),
            invite_code=spec.get("invite_code"),
            image_path=spec.get("photo"),
            logo_path=spec.get("logo"),
        ))
        created += 1
    db.session.flush()
    return created


def apply_users(config: SeedConfig) -> int:
    """Insert each user none of whose username/email is taken, teachers before those who name one."""
    from models import School

    created = 0
    for kind in USER_TYPES:
        for spec in (user for user in config["users"] if user["type"] == kind):
            if any(_find_user(key) for key in identities(spec)):
                continue
            school = db.session.scalar(db.select(School).filter_by(name=spec["school"])) if spec.get("school") else None
            teacher = _find_user(spec["teacher"]) if spec.get("teacher") else None
            db.session.add(_make_user(kind, spec, school, teacher))
            db.session.flush()
            created += 1
    return created


def _store_hero(name: str, files_dir: str, storage: Bucket) -> str:
    """Put a hero image in the bucket under the content-hash name the CMS would give it."""
    with open(os.path.join(files_dir, name), "rb") as handle:
        data = handle.read()
    extension = sniff_image(data)
    if extension is None:
        raise SeedError(f"{name} is not a PNG, JPEG, WebP or GIF")
    stored = f"{hashlib.md5(data).hexdigest()}.{extension}"
    storage.write(image_key(stored), data, IMAGE_TYPES[extension])
    return stored


def apply_articles(config: SeedConfig, files_dir: str, storage: Bucket) -> int:
    """Insert each article not already there (by title), authored by the administrator it names."""
    from models import Article

    created = 0
    for spec in config["articles"]:
        if db.session.scalar(db.select(Article).filter_by(title=spec["title"])):
            continue
        body = spec.get("body")
        if body is None:
            with open(os.path.join(files_dir, spec["file"]), encoding="utf-8") as handle:
                body = handle.read()
        author = _find_user(spec["author"])
        if author is None:
            raise SeedError(f'article "{spec["title"]}": author "{spec["author"]}" does not exist')
        db.session.add(Article(
            title=spec["title"], content_markdown=body, author_id=author.id,
            hero_image=_store_hero(spec["hero_image"], files_dir, storage) if spec.get("hero_image") else None,
        ))
        created += 1
    return created


def apply_team_members(config: SeedConfig) -> int:
    """Insert each team member not already there (by name)."""
    from models import TeamMember

    created = 0
    for spec in config["team_members"]:
        if not db.session.scalar(db.select(TeamMember).filter_by(name=spec["name"])):
            db.session.add(TeamMember(
                name=spec["name"], job=spec.get("job"), strengths=spec.get("strengths"), bio=spec.get("bio"),
                image_url=spec.get("image_url"),
            ))
            created += 1
    return created


def apply_site_content(config: SeedConfig) -> int:
    """Insert each site text key not already set."""
    from models import SiteContent

    created = 0
    for key, value in config["site_content"].items():
        if not db.session.scalar(db.select(SiteContent).filter_by(key=key)):
            db.session.add(SiteContent(key=key, value=value))
            created += 1
    return created


def apply_config(config: SeedConfig, *, storage: Bucket, files_dir: str = FILES_DIR) -> SeedCounts:
    """Insert whatever the config describes that is not already there, in one transaction.

    Args:
        config (SeedConfig): A validated config from `load_config`.
        storage (Bucket): The bucket, for article hero images.
        files_dir (str): Folder holding article body files and hero images.

    Returns:
        SeedCounts: Rows created per section.

    Raises:
        SeedError: The config names a file that does not exist; nothing was written.
    """
    check_files(config, files_dir)
    try:
        counts = SeedCounts(
            schools=apply_schools(config),
            users=apply_users(config),
            articles=apply_articles(config, files_dir, storage),
            team_members=apply_team_members(config),
            site_content=apply_site_content(config),
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return counts
