"""Weekly Postgres backup to GCS, run by the daily `integrated-backup` Cloud Run Job,
and a forced one at every deploy's `flask release`.

The job fires daily and the 7-day check below keeps it weekly. Content-hashed like git:
a new snapshot is only uploaded to GCS when the dump actually differs from the
last one, so redeploys/restarts inside the same week (or with no data changes)
never write duplicate storage.
"""
import gzip
import hashlib
import json
import logging
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import Flask

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "backups/"
MANIFEST_BLOB = BACKUP_PREFIX + "latest.json"
BACKUP_INTERVAL = timedelta(days=7)

__all__ = ["run_backup_check"]
PG_DUMP_TIMEOUT_SECONDS = 300


def run_backup_check(app: Flask, *, force: bool = False) -> str | None:
    """Back up the production Postgres to the bucket; a no-op in any other environment.

    The daily `flask backup-db` waits 7 days between dumps and only logs a
    failure. `flask release` passes ``force``: it dumps now and raises on a
    failure, so the deploy stops before content is pruned.

    Args:
        app (Flask): The Flask app, whose settings name the environment, database and bucket.
        force (bool): Skip the 7-day wait; raise on failure.

    Returns:
        str | None: The blob holding the current dump, or None when skipped or not due.
    """
    settings = app.config["SETTINGS"]
    if not settings.is_production:
        logger.info("DB backup: skipped (not production).")
        return None

    database_url = settings.database_url
    if not database_url.startswith(("postgres://", "postgresql://")):
        logger.info("DB backup: skipped (no Postgres DATABASE_URL).")
        return None

    bucket_name = settings.gcs_bucket_name
    try:
        from google.cloud import storage as gcs
        bucket = gcs.Client().bucket(bucket_name)
    except Exception:
        logger.exception("DB backup: could not create GCS client.")
        if force:
            raise
        return None

    try:
        return _check_and_backup(bucket, database_url, force=force)
    except Exception:
        logger.exception("DB backup: check failed.")
        if force:
            raise
        # The next daily run retries.
        return None


def _check_and_backup(bucket: Any, database_url: str, *, force: bool = False) -> str | None:
    """Run the dump-and-upload cycle if a backup is due (always, with ``force``).

    Args:
        bucket (Any): GCS bucket to read/write the manifest and backup blobs.
        database_url (str): Postgres connection string for `pg_dump`.
        force (bool): Dump even when the last check is under 7 days old.

    Returns:
        str | None: The blob holding the current dump, or None when not due.
    """
    now = datetime.now(UTC)
    manifest = _read_manifest(bucket)

    if manifest and not force:
        last_checked = datetime.fromisoformat(manifest["checked_at"])
        if now - last_checked < BACKUP_INTERVAL:
            logger.info(
                "DB backup: last check %s < 7 days ago — not due yet.",
                last_checked.isoformat(),
            )
            return None

    logger.info("DB backup: %s — dumping database.", "forced" if force else "weekly check due")
    dump_bytes = _pg_dump(database_url)
    sha256 = hashlib.sha256(dump_bytes).hexdigest()

    if manifest and manifest.get("sha256") == sha256:
        logger.info("DB backup: content unchanged since last backup — skipping upload.")
        manifest["checked_at"] = now.isoformat()
        _write_manifest(bucket, manifest)
        return manifest.get("blob")

    compressed = gzip.compress(dump_bytes, mtime=0)
    blob_name = f"{BACKUP_PREFIX}db_{now.strftime('%Y%m%dT%H%M%SZ')}.sql.gz"
    bucket.blob(blob_name).upload_from_string(compressed, content_type="application/gzip")

    manifest = {
        "blob": blob_name,
        "sha256": sha256,
        "checked_at": now.isoformat(),
        "created_at": now.isoformat(),
        "size_bytes": len(compressed),
    }
    _write_manifest(bucket, manifest)
    logger.info("DB backup: uploaded new backup %s (%d bytes).", blob_name, len(compressed))
    return blob_name


def _pg_dump(database_url: str) -> bytes:
    """Run `pg_dump` and return the raw dump.

    Args:
        database_url (str): Postgres connection string.

    Returns:
        bytes: Raw SQL dump output.
    """
    try:
        result = subprocess.run(
            ["pg_dump", "--format=plain", "--no-owner", "--no-privileges", database_url],
            capture_output=True,
            timeout=PG_DUMP_TIMEOUT_SECONDS,
            check=False,  # returncode handled explicitly below
        )
    except FileNotFoundError:
        raise RuntimeError("pg_dump not found — install postgresql-client in the Docker image.")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"pg_dump timed out after {PG_DUMP_TIMEOUT_SECONDS}s.")

    if result.returncode != 0:
        # stderr from pg_dump doesn't echo the connection string, safe to log.
        stderr = result.stderr.decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"pg_dump failed (exit {result.returncode}): {stderr}")

    return result.stdout


def _read_manifest(bucket: Any) -> dict[str, Any] | None:
    """Read `backups/latest.json` from GCS, if present.

    Args:
        bucket (Any): GCS bucket to read from.

    Returns:
        dict[str, Any] | None: The manifest, or None if missing/unparsable.
    """
    blob = bucket.blob(MANIFEST_BLOB)
    if not blob.exists():
        return None
    try:
        return json.loads(blob.download_as_text(encoding="utf-8"))
    except (ValueError, KeyError):
        return None


def _write_manifest(bucket: Any, manifest: dict[str, Any]) -> None:
    """Write the backup manifest to GCS.

    Args:
        bucket (Any): GCS bucket to write to.
        manifest (dict[str, Any]): Manifest payload to persist.

    Returns:
        None
    """
    bucket.blob(MANIFEST_BLOB).upload_from_string(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        content_type="application/json",
    )
