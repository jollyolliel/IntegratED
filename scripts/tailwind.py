"""Build static/css/tailwind.css with the pinned standalone Tailwind CLI (no Node).

The same command runs in dev, CI and the Docker builder stage, so the CSS a
developer sees is the CSS that ships. pytailwindcss downloads the binary for
TAILWIND_VERSION on first use and caches it per version.

Usage:
  uv run scripts/tailwind.py                         # one minified build
  uv run scripts/tailwind.py --watch                 # rebuild on change (dev)
  uv run scripts/tailwind.py --output x.css --no-minify
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# The only place the Tailwind release is pinned.
TAILWIND_VERSION = "v3.4.19"
INPUT = "static/css/input.css"
OUTPUT = "static/css/tailwind.css"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Everything the build reads: input.css, its @import chain, the config, and the
# config's `content` globs (a test keeps those in step). static/css/pages/*.css
# is linked as separate sheets, so it is deliberately absent.
SOURCE_GLOBS = (
    INPUT,
    "static/css/components.css",
    "static/css/components/*.css",
    "tailwind.config.js",
    "templates/**/*.html",
    "templates/**/*.jx",
    "static/**/*.js",
    "helpers/clay_primitives.py",
)


def needs_build(root: str | Path = ROOT) -> bool:
    """True when the built CSS is missing or older than any file it is built from."""
    root = Path(root)
    output = root / OUTPUT
    if not output.exists():
        return True
    built_at = output.stat().st_mtime
    return any(
        source.stat().st_mtime > built_at
        for pattern in SOURCE_GLOBS
        for source in root.glob(pattern)
    )


def build_if_stale(root: str | Path = ROOT) -> int | None:
    """Run a minified build only if `needs_build`; None when already fresh, else its exit code."""
    if not needs_build(root):
        return None
    output = Path(root) / OUTPUT
    code = main(["--output", str(output)])
    if code == 0 and output.exists():
        # Tailwind leaves an identical output unwritten; stamp it so an edit that
        # changed no CSS doesn't trigger the same rebuild on every later check.
        os.utime(output)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", default=OUTPUT)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--no-minify", dest="minify", action="store_false")
    args = parser.parse_args(argv)

    import pytailwindcss  # dev dependency group only: prod never builds CSS

    cli = ["-i", INPUT, "-o", args.output]
    if args.watch:
        cli.append("--watch")
    elif args.minify:
        cli.append("--minify")
    completed = pytailwindcss.run(
        cli, cwd=ROOT, live_output=True, auto_install=True, version=TAILWIND_VERSION
    )
    # live_output returns the CompletedProcess; the str branch (captured stdout) only comes
    # back on success, since a failing run without live_output raises instead.
    return completed.returncode if isinstance(completed, subprocess.CompletedProcess) else 0


if __name__ == "__main__":
    sys.exit(main())
