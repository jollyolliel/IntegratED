"""ast-grep design-system lint (sgconfig.yml, lint/): rules prove themselves, repo is clean."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


def ast_grep(*args: str) -> subprocess.CompletedProcess:
    binary = shutil.which("ast-grep", path=str(Path(sys.executable).parent)) or shutil.which("ast-grep")
    if binary is None:
        pytest.skip("ast-grep-cli is not installed (uv sync installs the dev group)")
    return subprocess.run(
        [binary, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        check=False,  # callers assert on the exit code with the output attached
    )


def test_every_rule_passes_its_own_valid_and_invalid_cases():
    result = ast_grep("test", "--skip-snapshot-tests")

    assert result.returncode == 0, result.stdout + result.stderr


def test_the_html_rules_also_scan_jx_files(tmp_path):
    # sgconfig.yml's languageGlobs; without it ast-grep skips `.jx` silently.
    page = tmp_path / "page.jx"
    page.write_text('<button class="btn-clay btn-sky p-4">Go</button>\n', encoding="utf-8")

    result = ast_grep("scan", "--json=compact", str(page))

    assert '"ruleId":"no-restyle-button"' in result.stdout, result.stdout + result.stderr


def test_ruff_bans_importing_current_user_from_flask_login(tmp_path):
    # docs/development/python-conventions.md: import it from helpers/current_user.py (typed via cast()).
    source = tmp_path / "view.py"
    source.write_text("from flask_login " + "import current_user\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--config", str(ROOT / "pyproject.toml"),
         "--select", "TID251", "--no-cache", str(source)],
        capture_output=True, text=True, encoding="utf-8",
        check=False,  # exit 1 is the expected "found a violation"
    )

    assert result.returncode == 1
    assert "helpers.current_user" in result.stdout


def test_ruff_bans_importing_render_template_from_flask(tmp_path):
    # helpers/render.py's render_template also renders `.jx` pages.
    source = tmp_path / "view.py"
    source.write_text("from flask " + "import render_template\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--config", str(ROOT / "pyproject.toml"),
         "--select", "TID251", "--no-cache", str(source)],
        capture_output=True, text=True, encoding="utf-8",
        check=False,  # exit 1 is the expected "found a violation"
    )

    assert result.returncode == 1
    assert "helpers.render" in result.stdout


def test_templates_and_css_have_no_error_level_findings():
    # Existing debt is listed per rule under `ignores:`; everything else is clean.
    result = ast_grep("scan", "templates", "static/css")

    assert result.returncode == 0, result.stdout + result.stderr


def test_whole_repo_scan_is_clean():
    # sgconfig.yml documents a bare `ast-grep scan`.
    result = ast_grep("scan")

    assert result.returncode == 0, result.stdout[-2000:] + result.stderr
