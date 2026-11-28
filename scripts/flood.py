"""Bulk dev data for load-testing admin and teacher tables.

The command line for helpers/flood.py, which floods the local SQLite database with learners,
volunteers, matches, worksheets, worksheet assignments, attendance history, donations and
articles. It works with whatever schools and teachers the database already has (seed them
first: `uv run flask seed`), takes each school's email domain from the school itself, and only
ever adds rows: it never edits or removes one. It refuses to run outside development, or
against any database but the dev SQLite file or `TEST_DATABASE_URL`.

Usage:
  uv run scripts/flood.py
  uv run scripts/flood.py --learners 500 --volunteers 200 --school "Example School"
  uv run scripts/flood.py --seed 7 --password dev-pass --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

# Run as `scripts/flood.py`, the repo root is not on sys.path, so nothing of the app would import.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.flood import flood_database

__all__ = ["flood_database", "main"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    for flag, default, text in (
        ("learners", 200, "learners to add"),
        ("volunteers", 100, "volunteers to add"),
        ("teachers", 0, "teachers to add"),
        ("worksheets", 30, "worksheets to add"),
        ("assignments", 400, "worksheet assignments to add"),
        ("attendance-weeks", 8, "weeks of attendance history per matched pair"),
        ("donations", 60, "donations to add"),
        ("articles", 50, "articles to add"),
    ):
        parser.add_argument(f"--{flag}", type=int, default=default, help=f"{text} (default {default})")
    parser.add_argument("--school", action="append", dest="schools", metavar="NAME", help="only this school (repeatable)")
    parser.add_argument("--seed", type=int, help="repeat a previous run's random choices")
    parser.add_argument("--password", help="password for new learners (default: random, printed)")
    parser.add_argument("--dry-run", action="store_true", help="report what would be added and save nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the flood against the dev database through the real app.

    Args:
        argv (list[str] | None): Command-line arguments; `sys.argv[1:]` when omitted.

    Returns:
        int: Process exit code.
    """
    args = _parser().parse_args(argv)
    from main import app

    options: dict[str, Any] = {
        "learners": args.learners, "volunteers": args.volunteers, "teachers": args.teachers,
        "worksheets": args.worksheets, "assignments": args.assignments,
        "attendance_weeks": args.attendance_weeks, "donations": args.donations, "articles": args.articles,
        "school_names": args.schools, "seed": args.seed, "password": args.password, "dry_run": args.dry_run,
    }
    with app.app_context():
        for line in flood_database(**options):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
