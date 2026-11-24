import os
from collections.abc import Generator
from contextlib import contextmanager

import click
from flask import Flask, current_app
from flask.cli import with_appcontext
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from helpers.announcements import sync_announcements
from helpers.audio_cache import generate_spoken_audio
from helpers.content import (
    ContentError,
    ImportResult,
    PrunePlan,
    import_content,
    plan_prune,
    read_content,
)
from helpers.content_source import ContentSourceError, staged_content
from helpers.worksheet_manifest import (
    ManifestError,
    ManifestSync,
    read_manifest,
    sync_worksheet_manifest,
)


def init_migrate(app: Flask) -> None:
    """Attach Flask-Migrate (and Alembic) on first migrate, never at app start."""
    if "migrate" not in app.extensions:
        from flask_migrate import Migrate

        Migrate(app, db)


class MigrateCommands(click.Group):
    """`flask db …`: stands in for Flask-Migrate's group until a `db` command runs.

    `flask --help` lists it from the help text below; parsing a `db` command line
    attaches Flask-Migrate and hands the rest to its real group.
    """

    def __init__(self, app: Flask) -> None:
        super().__init__("db", help="Perform database migrations.")
        self._app = app

    def make_context(self, info_name, args, parent=None, **extra) -> click.Context:
        init_migrate(self._app)
        from flask_migrate.cli import db as migrate_group

        return migrate_group.make_context(info_name, args, parent=parent, **extra)


@contextmanager
def _content_folder() -> Generator[str]:
    """The storage's `content/` folder, staged locally for the block (helpers/content_source.py)."""
    from helpers.storage import get_bucket

    try:
        with staged_content(get_bucket()) as folder:
            yield folder
    except ContentSourceError as error:
        raise click.ClickException(str(error)) from error


def _generate_audio() -> None:
    """Generate every spoken text's audio now, or explain why it can't."""
    from settings import get_settings

    if not get_settings().tts_enabled:
        raise click.ClickException("Generating audio needs TTS_ENABLED=true (and ELEVEN_API_KEY) in the environment.")
    ready, total = generate_spoken_audio()
    click.echo(f"Audio ready for {ready} of {total} spoken texts.")


def _echo_import(result: ImportResult) -> None:
    click.echo(f"Questions: {result.added} added, {result.updated} updated.")


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Clear existing data and create new tables."""
    db.create_all()
    click.echo("Initialized the database.")

@click.command("import-questions")
@click.option("--sound", is_flag=True, help="Also generate the audio of every spoken text now (needs TTS_ENABLED).")
@click.option("--prune", is_flag=True,
              help="List content the file no longer has. A dry run: writes nothing unless --apply is given.")
@click.option("--apply", "apply_prune", is_flag=True,
              help="With --prune: import, then delete what was listed, in one transaction.")
@with_appcontext
def import_questions_command(sound, prune, apply_prune):
    """Validate the storage's content/questions.json and import it (upsert by natural key).

    `--prune` prints what is in the database but no longer in the file — and
    what learners would lose — without writing anything; `--prune --apply`
    imports and removes it in one transaction.
    """
    if apply_prune and not prune:
        raise click.UsageError("--apply only works with --prune.")
    with _content_folder() as folder:
        path = os.path.join(folder, "questions.json")
        try:
            data = read_content(path)
            if prune and not apply_prune:
                click.echo("Would remove:")
                for line in plan_prune(db, data).lines():
                    click.echo(f"  {line}")
                click.echo("Dry run: nothing changed. Re-run with --prune --apply to import and remove these.")
                return
            result = import_content(db, data, prune=prune)
        except ContentError as error:
            raise click.ClickException(str(error)) from error
    _echo_import(result)
    if result.pruned is not None:
        click.echo("Removed:")
        for line in result.pruned.lines():
            click.echo(f"  {line}")
    if sound:
        _generate_audio()


@click.command("backup-db")
@with_appcontext
def backup_db_command():
    """Back up Postgres to GCS when the dump changed (the `integrated-backup` job)."""
    from helpers.backup import run_backup_check
    run_backup_check(current_app)


@click.command("diagnose-teacher")
@with_appcontext
def diagnose_teacher_command():
    """Show teacher, learner, and volunteer assignment state."""
    from models import Learner, School, Teacher, Volunteer
    teachers = db.session.scalars(db.select(Teacher)).all()
    click.echo(f"\n=== Teachers ({len(teachers)}) ===")
    for t in teachers:
        school = db.session.get(School, t.school_id) if t.school_id else None
        click.echo(f"  id={t.id} name={t.name!r} email={t.email!r} school_id={t.school_id} school={school.name if school else None}")
        click.echo(f"    managed_learners={len(t.managed_learners)} managed_volunteers={len(t.managed_volunteers)}")

    learners = db.session.scalars(db.select(Learner)).all()
    click.echo(f"\n=== Learners ({len(learners)}) ===")
    for l in learners:
        click.echo(f"  id={l.id} name={l.name!r} username={l.username!r} school_id={l.school_id} teacher_id={l.teacher_id}")

    volunteers = db.session.scalars(db.select(Volunteer)).all()
    click.echo(f"\n=== Volunteers ({len(volunteers)}) ===")
    for v in volunteers:
        click.echo(f"  id={v.id} name={v.name!r} email={v.email!r} school_id={v.school_id} teacher_id={v.teacher_id}")

    schools = db.session.scalars(db.select(School)).all()
    click.echo(f"\n=== Schools ({len(schools)}) ===")
    for s in schools:
        click.echo(f"  id={s.id} name={s.name!r}")


@click.command("fix-teacher-assignments")
@click.option("--dry-run", is_flag=True, default=False, help="Print changes without applying.")
@with_appcontext
def fix_teacher_assignments_command(dry_run):
    """Assign all unassigned learners/volunteers to the teacher in the same school.

    If only one teacher exists, assigns ALL unassigned learners/volunteers to them.
    Also fixes mismatched school_ids on learners/volunteers.

    Shares its notion of "unassigned" with the teacher dashboard's auto-assign
    via `helpers.teacher_ops.assign_unassigned` — this command is just the
    multi-teacher/dry-run/single-teacher-claims-all surface on top of it.
    """
    from helpers import teacher_ops
    from models import School, Teacher

    teachers = db.session.scalars(db.select(Teacher)).all()
    if not teachers:
        click.echo("No teachers found.")
        return

    single_teacher = len(teachers) == 1
    if single_teacher:
        click.echo(f"Single teacher: {teachers[0].name!r} (id={teachers[0].id})")
    else:
        click.echo(f"Multiple teachers found ({len(teachers)}). Matching by school_id.")

    total_learners_fixed = 0
    total_volunteers_fixed = 0

    for teacher in teachers:
        school = db.session.get(School, teacher.school_id) if teacher.school_id else None
        click.echo(f"\nTeacher {teacher.name!r} (id={teacher.id}, school={school.name if school else 'NONE'})")

        if not single_teacher and not teacher.school_id:
            click.echo("  Teacher has no school_id — skipping.")
            continue

        result = teacher_ops.assign_unassigned(teacher, dry_run=dry_run, all_schools=single_teacher)
        learners, volunteers = result["learners"], result["volunteers"]

        click.echo(f"  Unassigned learners to assign: {len(learners)}")
        for l in learners:
            click.echo(f"    Learner id={l.id} name={l.name!r} username={l.username!r} school_id={l.school_id}")

        click.echo(f"  Unassigned volunteers to assign: {len(volunteers)}")
        for v in volunteers:
            click.echo(f"    Volunteer id={v.id} name={v.name!r} email={v.email!r} school_id={v.school_id}")

        if not dry_run:
            total_learners_fixed += len(learners)
            total_volunteers_fixed += len(volunteers)

    if dry_run:
        click.echo("\n[DRY RUN] No changes applied.")
    else:
        click.echo(f"\nDone. Assigned {total_learners_fixed} learner(s) and {total_volunteers_fixed} volunteer(s).")


@click.command("unmatch-all")
@click.confirmation_option(prompt="Dissolve every volunteer-learner match in the local dev database?")
@with_appcontext
def unmatch_all_command():
    """Dissolve every volunteer-learner match in the local dev DB. SQLite only —
    never runs against Postgres/prod. `--yes` skips the prompt."""
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri.startswith("sqlite"):
        click.echo(f"Refusing: SQLALCHEMY_DATABASE_URI is not sqlite ({uri.split('://')[0]}://...). This command is dev-only.")
        return

    from models import Learner, Volunteer
    learners = db.session.scalars(
        db.select(Learner).where(db.or_(Learner.volunteer_id.is_not(None), Learner.is_matched.is_(True)))
    ).all()
    stale_volunteers = db.session.scalars(db.select(Volunteer).filter_by(is_matched=True)).all()
    if not learners and not stale_volunteers:
        click.echo("No matches to dissolve.")
        return

    for learner in learners:
        learner.unmatch()
    for volunteer in stale_volunteers:
        volunteer.is_matched = False
    db.session.commit()
    click.echo(f"Unmatched {len(learners)} learner(s).")


@click.command("sync-sequences")
@with_appcontext
def sync_sequences_command():
    """Reset PostgreSQL auto-increment sequences to MAX(id). No-op on SQLite."""
    from flask import current_app
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri.startswith("postgresql"):
        click.echo("Not PostgreSQL — skipping sequence sync.")
        return

    # Only tables with their own integer PK sequences (not FK-inherited PKs)
    tables = [
        "users", "schools", "articles", "site_content", "team_members",
        "subjects", "topics", "lessons", "questions", "map_questions",
        "attendance", "worksheets", "worksheet_assignments", "map_sessions", "donations",
    ]

    for table in tables:
        try:
            db.session.execute(db.text(
                f"SELECT setval("
                f"  pg_get_serial_sequence('{table}', 'id'),"
                f"  COALESCE((SELECT MAX(id) FROM {table}), 1)"
                f")"
            ))
            click.echo(f"  Synced {table}.id")
        except SQLAlchemyError as e:
            click.echo(f"  Warning: could not sync {table}: {e}")
            db.session.rollback()

    db.session.commit()
    click.echo("Sequence sync complete.")


@click.command("seed")
@click.option("--audio", is_flag=True, help="Also generate the spoken audio for every spoken question (needs TTS_ENABLED).")
@with_appcontext
def seed_command(audio):
    """Fill the dev bucket and database from seed/ (development only; insert-only, safe to repeat)."""
    from helpers.seed import SeedError, seed_development

    try:
        created = seed_development(force=True)
    except SeedError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Seeded from seed/seed.toml: {created}")
    if audio:
        _generate_audio()


@click.command("sync-announcements")
@with_appcontext
def sync_announcements_command():
    """Insert any new announcement from the storage's content/announcements.json."""
    with _content_folder() as folder:
        inserted = sync_announcements(os.path.join(folder, "announcements.json"))
    click.echo(f"Inserted {len(inserted)} announcement(s): {', '.join(inserted) or 'none'}")


def _echo_worksheet_sync(result: ManifestSync) -> None:
    if not result.found:
        click.echo("Worksheets: no content/worksheets/manifest.json, nothing to sync.")
        return
    click.echo(f"Worksheets: {result.added} added, {result.updated} updated.")
    for name in result.skipped:
        click.echo(f"  Skipped {name}: its file isn't there yet.")


def _sync_worksheets(folder: str) -> None:
    from helpers.storage import get_bucket

    try:
        result = sync_worksheet_manifest(get_bucket(), os.path.join(folder, "worksheets"))
    except ManifestError as error:
        raise click.ClickException(str(error)) from error
    _echo_worksheet_sync(result)


@click.command("sync-worksheets")
@with_appcontext
def sync_worksheets_command():
    """Upsert a worksheet row for each content/worksheets/manifest.json entry (never deletes)."""
    with _content_folder() as folder:
        _sync_worksheets(folder)


def _echo_prune_plan(plan: PrunePlan) -> None:
    click.echo("Prune plan:")
    for line in plan.lines():
        click.echo(f"  {line}")


@click.command("release")
@with_appcontext
def release_command():
    """Bring the database in line with this image and the bucket's content.

    Order: stage and validate the content, take a forced backup, migrate, sync
    announcements, import questions with pruning (audio is generated on first
    request, never here), then sync the worksheet manifest. Nothing is written
    until the content has passed validation, and the backup is taken before the
    migration or the prune can change anything. Any failure exits non-zero.
    """
    # Run by the deploy as the `integrated-release` Cloud Run Job before the
    # new revision takes traffic (ADR 0015); a failure here stops the deploy.
    from flask_migrate import upgrade

    from helpers.backup import run_backup_check

    with _content_folder() as folder:
        try:
            content = read_content(os.path.join(folder, "questions.json"))
            read_manifest(os.path.join(folder, "worksheets"))
        except (ContentError, ManifestError) as error:
            raise click.ClickException(str(error)) from error
        click.echo("Content: valid.")

        # Raises when the production backup fails, before anything is changed.
        backup = run_backup_check(current_app, force=True)
        click.echo(f"Backup: {backup}." if backup else "Backup: skipped (not production Postgres with a bucket).")

        init_migrate(current_app._get_current_object())  # ty: ignore[missing-attribute]  # the proxy's real app, which Flask-Migrate keeps
        upgrade()
        click.echo("Migrations applied.")

        inserted = sync_announcements(os.path.join(folder, "announcements.json"))
        click.echo(f"Inserted {len(inserted)} announcement(s): {', '.join(inserted) or 'none'}")

        _echo_import(import_content(db, content, prune=True, before_prune=_echo_prune_plan))
        _sync_worksheets(folder)


def register_commands(app: Flask) -> None:
    app.cli.add_command(MigrateCommands(app))
    app.cli.add_command(init_db_command)
    app.cli.add_command(import_questions_command)
    app.cli.add_command(backup_db_command)
    app.cli.add_command(diagnose_teacher_command)
    app.cli.add_command(fix_teacher_assignments_command)
    app.cli.add_command(unmatch_all_command)
    app.cli.add_command(sync_sequences_command)
    app.cli.add_command(sync_announcements_command)
    app.cli.add_command(seed_command)
    app.cli.add_command(release_command)
    app.cli.add_command(sync_worksheets_command)
