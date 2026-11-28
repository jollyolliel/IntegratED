#!/bin/sh
set -e

# PR previews only (ADR 0013). Build the database from nothing, then serve. This
# migrates and seeds at boot, which production must never do, and seeding wipes
# every table, so it refuses to start anywhere else.
if [ "$APP_ENV" != "preview" ]; then
    echo "entrypoint-preview.sh only runs with APP_ENV=preview" >&2
    exit 1
fi

# The PR's own migration chain, against an empty SQLite file.
flask db upgrade
flask seed-preview

exec /bin/sh /app/entrypoint.sh
