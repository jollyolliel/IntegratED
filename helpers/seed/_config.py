"""Reading and validating `seed/seed.toml`. Pure: nothing here touches the database."""

from __future__ import annotations

import os
import tomllib
from typing import Any, TypedDict

from helpers.paths import get_resource_path
from helpers.problems import ProblemsError

__all__ = [
    "CONFIG_PATH",
    "EMPTY_CONFIG",
    "FILES_DIR",
    "STATIC_DIR",
    "USER_TYPES",
    "SeedConfig",
    "SeedConfigError",
    "SeedError",
    "check_files",
    "identities",
    "load_config",
    "validate",
]

CONFIG_PATH = get_resource_path("seed/seed.toml")
#: Mirrors the bucket's layout (`content/`, `worksheets/`); copied into an empty dev bucket.
FILES_DIR = get_resource_path("seed/files")
STATIC_DIR = get_resource_path("static")

#: Creation order: a learner or volunteer names a teacher, so teachers come first.
USER_TYPES = ("administrator", "school_admin", "teacher", "volunteer", "learner")
_NEEDS_PASSWORD = {"administrator", "school_admin", "learner"}
_NEEDS_USERNAME = {"administrator", "school_admin", "learner"}
_NEEDS_EMAIL = {"teacher", "volunteer"}
#: Google sign-in only: a username or password here would never let them in.
_GOOGLE_ONLY = {"teacher", "volunteer"}
_NEEDS_SCHOOL = {"school_admin", "teacher", "volunteer", "learner"}


class SeedConfig(TypedDict):
    """`seed.toml`, every section present. Each entry is the TOML table as written."""

    schools: list[dict[str, Any]]
    users: list[dict[str, Any]]
    articles: list[dict[str, Any]]
    team_members: list[dict[str, Any]]
    site_content: dict[str, str]


EMPTY_CONFIG = SeedConfig(schools=[], users=[], articles=[], team_members=[], site_content={})


class SeedError(ValueError):
    """`seed.toml` is invalid or seeding is not allowed here; nothing was written."""


class SeedConfigError(SeedError, ProblemsError):
    """`seed.toml` has problems, listed in `problems`; nothing was written."""


def identities(user: dict[str, Any]) -> list[str]:
    """The keys other entries may name a user by: its username and email, where given."""
    return [value for value in (user.get("username"), user.get("email")) if value]


def validate(config: SeedConfig) -> list[str]:
    """Check a config's shape and every cross-reference.

    Args:
        config (SeedConfig): The parsed config.

    Returns:
        list[str]: One message per problem, each starting with where it is (`users[2]: ...`).
    """
    problems: list[str] = []
    school_names: set[str] = set()
    for index, school in enumerate(config["schools"]):
        name = school.get("name")
        if not name:
            problems.append(f"schools[{index}]: name is required")
        elif name in school_names:
            problems.append(f'schools[{index}]: duplicate school "{name}"')
        else:
            school_names.add(name)

    seen: set[str] = set()
    teacher_keys: set[str] = set()
    admin_keys: set[str] = set()
    for index, user in enumerate(config["users"]):
        where = f"users[{index}]"
        kind = user.get("type")
        if kind not in USER_TYPES:
            problems.append(f"{where}: type must be one of {', '.join(USER_TYPES)} (got {kind!r})")
            continue
        if kind in _NEEDS_USERNAME and not user.get("username"):
            problems.append(f"{where}: a {kind} needs a username")
        if kind in _NEEDS_EMAIL and not user.get("email"):
            problems.append(f"{where}: a {kind} needs an email")
        if kind in _NEEDS_PASSWORD and not user.get("password"):
            problems.append(f"{where}: a {kind} needs a password")
        if kind in _GOOGLE_ONLY and (user.get("username") or user.get("password")):
            problems.append(f"{where}: a {kind} signs in with Google only; remove its username and password")
        if kind in _NEEDS_SCHOOL and user.get("school") not in school_names:
            problems.append(f'{where}: school "{user.get("school")}" is not in [[schools]]')
        for key in identities(user):
            if key in seen:
                problems.append(f'{where}: duplicate username/email "{key}"')
            seen.add(key)
        if kind == "teacher":
            teacher_keys.update(identities(user))
        if kind == "administrator":
            admin_keys.update(identities(user))

    for index, user in enumerate(config["users"]):
        teacher = user.get("teacher")
        if teacher and teacher not in teacher_keys:
            problems.append(f'users[{index}]: teacher "{teacher}" is not a teacher in [[users]]')

    for index, article in enumerate(config["articles"]):
        where = f"articles[{index}]"
        if not article.get("title"):
            problems.append(f"{where}: title is required")
        if bool(article.get("body")) == bool(article.get("file")):
            problems.append(f"{where}: give exactly one of body or file")
        # Only administrators write articles in the app, and only deleting one reassigns them.
        if article.get("author") not in admin_keys:
            problems.append(f'{where}: author "{article.get("author")}" is not an administrator in [[users]]')

    for index, member in enumerate(config["team_members"]):
        if not member.get("name"):
            problems.append(f"team_members[{index}]: name is required")
    return problems


def load_config(path: str = CONFIG_PATH) -> SeedConfig:
    """Read and validate `seed.toml`.

    Args:
        path (str): Config file; a missing file is an empty config.

    Returns:
        SeedConfig: The config, with every section present.

    Raises:
        SeedError: The file is not valid TOML or breaks the contract; the message lists every problem.
    """
    parsed: dict[str, Any] = {}
    if os.path.isfile(path):
        try:
            with open(path, "rb") as handle:
                parsed = tomllib.load(handle)
        except tomllib.TOMLDecodeError as error:
            raise SeedError(f"{os.path.basename(path)} is not valid TOML: {error}") from error
    config = SeedConfig(
        schools=parsed.get("schools", []),
        users=parsed.get("users", []),
        articles=parsed.get("articles", []),
        team_members=parsed.get("team_members", []),
        site_content=parsed.get("site_content", {}),
    )
    problems = validate(config)
    if problems:
        raise SeedConfigError(os.path.basename(path), problems)
    return config


def check_files(config: SeedConfig, files_dir: str, static_dir: str = STATIC_DIR) -> None:
    """Every file the config names must exist before anything is written.

    Args:
        config (SeedConfig): A validated config.
        files_dir (str): Folder holding article body files and hero images.
        static_dir (str): The app's `static/`, where school photos and logos live.

    Raises:
        SeedError: A named file is missing; the message lists each one.
    """
    named = [
        (f"schools[{i}].{field}", static_dir, "static/", school[field])
        for i, school in enumerate(config["schools"])
        for field in ("photo", "logo")
        if school.get(field)
    ]
    named += [
        (f"articles[{i}].{field}", files_dir, "seed/files/", article[field])
        for i, article in enumerate(config["articles"])
        for field in ("file", "hero_image")
        if article.get(field)
    ]
    missing = [
        f"{where}: {label}{name} does not exist"
        for where, folder, label, name in named
        if not os.path.isfile(os.path.join(folder, name))
    ]
    if missing:
        raise SeedConfigError("seed.toml", missing)
