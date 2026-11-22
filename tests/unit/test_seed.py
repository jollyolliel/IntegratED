"""`seed/seed.toml`: what a fresh dev database is filled with. Insert-only, and only ever run in development."""

from __future__ import annotations

import textwrap

import pytest

from extensions import db
from helpers import seed
from models import (
    Administrator,
    Article,
    Learner,
    School,
    SchoolAdmin,
    SiteContent,
    Teacher,
    TeamMember,
    User,
    Volunteer,
)
from tests.support.app import use_environment
from tests.support.storage import FakeBucket

pytestmark = pytest.mark.unit

FULL = """
[[schools]]
name = "Example School"
mission_statement = "Learning together."
location = "Athens"
volunteer_domain = "stu.example.test"
teacher_domain = "example.test"

[[users]]
type = "administrator"
username = "root"
name = "Root"
password = "root-pass"

[[users]]
type = "school_admin"
username = "head"
name = "Head"
password = "head-pass"
school = "Example School"

[[users]]
type = "teacher"
email = "teach@example.test"
name = "Teach"
school = "Example School"

[[users]]
type = "volunteer"
email = "vol@stu.example.test"
name = "Vol"
school = "Example School"
teacher = "teach@example.test"

[[users]]
type = "learner"
username = "kid"
name = "Kid"
password = "kid-pass"
school = "Example School"
teacher = "teach@example.test"

[[articles]]
title = "Hello"
author = "root"
body = "# Hi"

[[team_members]]
name = "Pat"
job = "Lead"

[site_content]
team_statement = "We are a team."
"""


def _config(tmp_path, text=FULL):
    path = tmp_path / "seed.toml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return seed.load_config(str(path))


@pytest.fixture
def files(tmp_path):
    folder = tmp_path / "files"
    folder.mkdir()
    return folder


def test_a_full_config_creates_every_kind_of_row(db_session, tmp_path, files):
    counts = seed.apply_config(_config(tmp_path), files_dir=str(files), storage=FakeBucket())

    assert db.session.scalar(db.select(School).filter_by(name="Example School")).location == "Athens"
    assert db.session.scalar(db.select(Administrator).filter_by(username="root")).check_password("root-pass")
    assert db.session.scalar(db.select(SchoolAdmin).filter_by(username="head")).check_password("head-pass")
    teacher = db.session.scalar(db.select(Teacher).filter_by(email="teach@example.test"))
    assert teacher.school.name == "Example School"
    volunteer = db.session.scalar(db.select(Volunteer).filter_by(email="vol@stu.example.test"))
    assert volunteer.teacher_id == teacher.id
    learner = db.session.scalar(db.select(Learner).filter_by(username="kid"))
    assert learner.check_password("kid-pass") and learner.teacher_id == teacher.id
    assert learner.completed_survey and learner.completed_map_test
    assert db.session.scalar(db.select(TeamMember).filter_by(name="Pat")).job == "Lead"
    assert db.session.scalar(db.select(SiteContent).filter_by(key="team_statement")).value == "We are a team."
    assert counts["users"] == 5 and counts["schools"] == 1 and counts["articles"] == 1


def test_an_article_is_authored_by_the_named_user(db_session, tmp_path, files):
    seed.apply_config(_config(tmp_path), files_dir=str(files), storage=FakeBucket())

    article = db.session.scalar(db.select(Article).filter_by(title="Hello"))
    assert article.author.username == "root"
    assert article.content_markdown == "# Hi"


def test_an_article_body_can_come_from_a_file(db_session, tmp_path, files):
    (files / "post.md").write_text("From a file", encoding="utf-8")
    text = FULL.replace('body = "# Hi"', 'file = "post.md"')

    seed.apply_config(_config(tmp_path, text), files_dir=str(files), storage=FakeBucket())

    assert db.session.scalar(db.select(Article).filter_by(title="Hello")).content_markdown == "From a file"


def test_an_article_hero_image_is_stored_in_the_bucket(db_session, tmp_path, files):
    (files / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    text = FULL.replace('body = "# Hi"', 'body = "# Hi"\nhero_image = "hero.png"')
    storage = FakeBucket()

    seed.apply_config(_config(tmp_path, text), files_dir=str(files), storage=storage)

    hero = db.session.scalar(db.select(Article).filter_by(title="Hello")).hero_image
    assert hero.endswith(".png") and hero in storage.under("images/")


def test_a_school_photo_and_logo_are_static_paths(db_session, tmp_path, files):
    photo, logo = "img/acs-athens.jpg", "img/schools/acs-athens-logo.jpg"
    text = FULL.replace('location = "Athens"', f'location = "Athens"\nphoto = "{photo}"\nlogo = "{logo}"')

    seed.apply_config(_config(tmp_path, text), files_dir=str(files), storage=FakeBucket())

    school = db.session.scalar(db.select(School).filter_by(name="Example School"))
    assert school.image_path == photo
    assert school.logo_path == logo


def test_running_twice_creates_nothing_new(db_session, tmp_path, files):
    config = _config(tmp_path)
    seed.apply_config(config, files_dir=str(files), storage=FakeBucket())
    before = db.session.scalar(db.select(db.func.count()).select_from(User))

    second = seed.apply_config(config, files_dir=str(files), storage=FakeBucket())

    assert db.session.scalar(db.select(db.func.count()).select_from(User)) == before
    assert db.session.scalar(db.select(db.func.count()).select_from(School)) == 1
    assert second == {"schools": 0, "users": 0, "articles": 0, "team_members": 0, "site_content": 0}


def test_a_hand_edited_row_survives_a_rerun(db_session, tmp_path, files):
    config = _config(tmp_path)
    seed.apply_config(config, files_dir=str(files), storage=FakeBucket())
    school = db.session.scalar(db.select(School).filter_by(name="Example School"))
    school.mission_statement = "Edited in the app."
    db.session.commit()

    seed.apply_config(config, files_dir=str(files), storage=FakeBucket())

    assert db.session.scalar(db.select(School).filter_by(name="Example School")).mission_statement == "Edited in the app."


def test_it_refuses_to_run_outside_development(app, db_session, monkeypatch):
    use_environment(app, monkeypatch, "production")

    with pytest.raises(seed.SeedError, match="production"):
        seed.seed_development(force=True)
    assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 0


def test_an_article_author_must_be_an_administrator(tmp_path):
    text = FULL.replace('author = "root"', 'author = "teach@example.test"')

    with pytest.raises(seed.SeedError, match=r'articles\[0\]: author "teach@example.test" is not an administrator'):
        _config(tmp_path, text)


def test_a_config_with_no_admin_creates_no_admin(db_session, tmp_path, files):
    text = """
    [[schools]]
    name = "Only"
    """
    seed.apply_config(_config(tmp_path, text), files_dir=str(files), storage=FakeBucket())

    assert db.session.scalar(db.select(db.func.count()).select_from(Administrator)) == 0


def test_an_unknown_user_type_is_an_error(tmp_path):
    text = FULL.replace('type = "administrator"', 'type = "wizard"', 1)

    with pytest.raises(seed.SeedError, match=r"users\[0\]: type"):
        _config(tmp_path, text)


def test_an_unknown_school_reference_is_an_error(tmp_path):
    text = FULL.replace('school = "Example School"', 'school = "Missing School"', 1)

    with pytest.raises(seed.SeedError, match=r'users\[1\]: school "Missing School"'):
        _config(tmp_path, text)


def test_an_unknown_article_author_is_an_error(tmp_path):
    text = FULL.replace('author = "root"', 'author = "nobody"')

    with pytest.raises(seed.SeedError, match=r'articles\[0\]: author "nobody" is not an administrator'):
        _config(tmp_path, text)


def test_a_duplicate_username_is_an_error(tmp_path):
    text = FULL.replace('username = "head"', 'username = "root"')

    with pytest.raises(seed.SeedError, match="duplicate"):
        _config(tmp_path, text)


def test_a_password_login_user_needs_a_password(tmp_path):
    text = FULL.replace('password = "kid-pass"\n', "")

    with pytest.raises(seed.SeedError, match="password"):
        _config(tmp_path, text)


@pytest.mark.parametrize(
    ("email", "field"),
    [("teach@example.test", 'username = "teach"'), ("teach@example.test", 'password = "teach-pass"'),
     ("vol@stu.example.test", 'username = "vol"'), ("vol@stu.example.test", 'password = "vol-pass"')],
)
def test_a_google_sign_in_user_with_a_username_or_password_is_an_error(tmp_path, email, field):
    text = FULL.replace(f'email = "{email}"\n', f'email = "{email}"\n{field}\n')

    with pytest.raises(seed.SeedError, match="Google"):
        _config(tmp_path, text)


def test_an_unknown_photo_file_is_an_error(db_session, tmp_path, files):
    text = FULL.replace('location = "Athens"', 'location = "Athens"\nphoto = "missing.jpg"')

    with pytest.raises(seed.SeedError, match="missing.jpg"):
        seed.apply_config(_config(tmp_path, text), files_dir=str(files), storage=FakeBucket())


def test_a_missing_config_file_is_an_empty_config(tmp_path):
    assert seed.load_config(str(tmp_path / "nope.toml")) == seed.EMPTY_CONFIG


def test_the_database_counts_as_empty_until_a_school_or_user_exists(db_session, tmp_path, files):
    assert seed.database_is_empty() is True

    seed.apply_config(_config(tmp_path, '[[schools]]\nname = "A"\n'), files_dir=str(files), storage=FakeBucket())

    assert seed.database_is_empty() is False


def test_the_shipped_seed_file_is_valid():
    config = seed.load_config(seed.CONFIG_PATH)

    assert config["schools"], "the dev seed should define at least one school"
