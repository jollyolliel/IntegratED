#!/bin/sh
set -e

# Serve and nothing else. Migrations and the announcement sync run once per
# deploy (`flask release`, the integrated-release job) and the weekly backup
# runs on a schedule (integrated-backup) — never here, because Cloud Run
# throttles CPU outside requests and background work at boot crawls (ADR 0015).
exec gunicorn \
    --bind 0.0.0.0:${PORT:-8080} \
    --workers 1 \
    --threads 8 \
    --worker-class gthread \
    --preload \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile - \
    "main:app"
