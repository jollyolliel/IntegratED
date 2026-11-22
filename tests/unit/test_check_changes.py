"""Unit tests for the end-of-turn checker behind the Stop hook."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def write(path, text: str):
    path.write_text(text.lstrip("\n"), encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------
# session scoping
# --------------------------------------------------------------------------


def _transcript(tmp_path, *calls):
    import json

    lines = [
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": name, "input": {"file_path": path}}]}})
        for name, path in calls
    ]
    lines.insert(0, "not json")
    lines.append(json.dumps({"type": "user", "message": {"content": "hi"}}))
    return write(tmp_path / "t.jsonl", "\n".join(lines))


def test_session_files_are_the_ones_this_transcript_edited(tmp_path):
    from scripts.check_changes import session_files

    root = str(tmp_path)
    transcript = _transcript(
        tmp_path,
        ("Edit", str(tmp_path / "a" / "x.py")),
        ("Write", "b/y.md"),
        ("Read", str(tmp_path / "never.py")),
    )

    assert session_files(transcript, root) == {"a/x.py", "b/y.md"}


def test_session_files_is_none_without_a_readable_transcript(tmp_path):
    from scripts.check_changes import session_files

    assert session_files(None, str(tmp_path)) is None
    assert session_files(str(tmp_path / "missing.jsonl"), str(tmp_path)) is None


def test_only_session_files_survive_scoping():
    from scripts.check_changes import scope_to_session

    changed = {"a.py": [(1, 2)], "other_agent.py": [(1, 2)]}

    assert scope_to_session(changed, {"a.py"}) == {"a.py": [(1, 2)]}
    assert scope_to_session(changed, None) == changed


# --------------------------------------------------------------------------
# line selection
# --------------------------------------------------------------------------


def test_touched_lines_whole_file_covers_every_line(tmp_path):
    from scripts.change_selection import WHOLE_FILE
    from scripts.check_changes import touched_lines

    path = write(tmp_path / "a.py", "one\ntwo\nthree\n")

    assert touched_lines(path, WHOLE_FILE) == {1, 2, 3}


def test_touched_lines_expands_ranges(tmp_path):
    from scripts.check_changes import touched_lines

    path = write(tmp_path / "a.py", "one\ntwo\nthree\nfour\n")

    assert touched_lines(path, [(2, 3)]) == {2, 3}


# --------------------------------------------------------------------------
# docstring bloat
# --------------------------------------------------------------------------


BLOATED = '''
def add(a, b):
    """Add two numbers together.

    This walks through the arithmetic at length, explaining that the first
    operand is added to the second operand, producing a sum, which is then
    handed back to whoever asked for it.
    """
    return a + b
'''

JUSTIFYING = '''
def add(a, b):
    """Add two numbers with ``+`` instead of ``operator.add``."""
    return a + b
'''

WITH_ARGS_SECTION = '''
def add(a, b):
    """Add two numbers.

    Args:
        a: first operand.
        b: second operand.

    Returns:
        The sum.
    """
    return a + b
'''


def test_long_docstring_on_a_changed_function_is_flagged(tmp_path):
    from scripts.check_changes import check_python

    path = write(tmp_path / "m.py", BLOATED)

    problems = check_python(path, {8})

    assert len(problems) == 1
    assert "add()" in problems[0]


def test_docstring_of_an_untouched_function_is_ignored(tmp_path):
    from scripts.check_changes import check_python

    path = write(tmp_path / "m.py", "x = 1\n\n" + BLOATED.lstrip("\n"))

    assert check_python(path, {1}) == []


def test_docstring_that_justifies_a_decision_is_flagged(tmp_path):
    from scripts.check_changes import check_python

    path = write(tmp_path / "m.py", JUSTIFYING)

    problems = check_python(path, {2})

    assert len(problems) == 1
    assert "instead of" in problems[0]


def test_args_section_does_not_count_toward_the_ratio(tmp_path):
    from scripts.check_changes import check_python

    path = write(tmp_path / "m.py", WITH_ARGS_SECTION)

    assert check_python(path, {1}) == []


def test_syntax_error_is_not_a_problem(tmp_path):
    from scripts.check_changes import check_python

    path = write(tmp_path / "m.py", "def broken(:\n")

    assert check_python(path, {1}) == []


# --------------------------------------------------------------------------
# rules files
# --------------------------------------------------------------------------


def test_dated_rules_line_is_flagged(tmp_path):
    from scripts.check_changes import check_rules_file

    path = write(tmp_path / "ui-core.md", "# UI\n\nFixed 2026-05-01 for real.\n")

    problems = check_rules_file(path, {3})

    assert len(problems) == 1
    assert "dated line" in problems[0]


def test_dated_rules_line_outside_the_diff_is_ignored(tmp_path):
    from scripts.check_changes import check_rules_file

    path = write(tmp_path / "ui-core.md", "# UI\n\nFixed 2026-05-01 for real.\n")

    assert check_rules_file(path, {1}) == []


def test_date_inside_a_code_fence_is_ignored(tmp_path):
    from scripts.check_changes import check_rules_file

    path = write(
        tmp_path / "api.md",
        '# API\n\n```json\n{"created": "2026-05-01"}\n```\n',
    )

    assert check_rules_file(path, {1, 2, 3, 4, 5}) == []


def test_date_inside_a_generated_block_is_ignored(tmp_path):
    from scripts.check_changes import check_rules_file

    path = write(
        tmp_path / "routes.md",
        "# Routes\n\n<!-- BEGIN GENERATED -->\nrow 2026-05-01\n<!-- END GENERATED -->\n",
    )

    assert check_rules_file(path, {1, 2, 3, 4, 5}) == []


# --------------------------------------------------------------------------
# design-system lint (ast-grep)
# --------------------------------------------------------------------------


def lint_finding(path, line, *, end=None, severity="error", rule="no-restyle-button"):
    """One `ast-grep scan --json=stream` record (its lines are 0-indexed)."""
    return {
        "file": path,
        "ruleId": rule,
        "severity": severity,
        "message": "A clay button owns its padding.",
        "note": "Use a size (btn-sm, btn-lg).",
        "range": {"start": {"line": line - 1}, "end": {"line": (end or line) - 1}},
    }


def test_lint_error_on_a_changed_line_is_reported(tmp_path):
    from scripts.check_changes import lint_problems

    problems = lint_problems(
        [lint_finding("templates/a.html", 3)], {"templates/a.html": {3}}, str(tmp_path)
    )

    assert len(problems) == 1
    assert "templates/a.html:3" in problems[0]
    assert "no-restyle-button" in problems[0]
    assert "btn-sm" in problems[0]


def test_lint_error_outside_the_diff_is_ignored(tmp_path):
    from scripts.check_changes import lint_problems

    problems = lint_problems(
        [lint_finding("templates/a.html", 3)], {"templates/a.html": {9}}, str(tmp_path)
    )

    assert problems == []


def test_lint_warning_never_blocks(tmp_path):
    from scripts.check_changes import lint_problems

    problems = lint_problems(
        [lint_finding("templates/a.html", 3, severity="warning")],
        {"templates/a.html": {3}},
        str(tmp_path),
    )

    assert problems == []


def test_multi_line_lint_error_counts_when_any_of_its_lines_changed(tmp_path):
    from scripts.check_changes import lint_problems

    problems = lint_problems(
        [lint_finding("templates\\a.html", 3, end=6)], {"templates/a.html": {5}}, str(tmp_path)
    )

    assert len(problems) == 1


def test_collect_lints_changed_templates_and_css_in_one_call(tmp_path, monkeypatch):
    from scripts import check_changes
    from scripts.change_selection import WHOLE_FILE

    (tmp_path / "templates").mkdir()
    components = tmp_path / "static" / "css" / "components"
    components.mkdir(parents=True)
    write(tmp_path / "templates" / "a.html", "<div></div>\n")
    write(components / "buttons.css", ".btn {}\n")
    write(tmp_path / "notes.html", "<p></p>\n")

    calls = []
    monkeypatch.setattr(check_changes, "check_class_index", lambda root: [])
    monkeypatch.setattr(
        check_changes, "ast_grep_findings", lambda root, paths: calls.append(sorted(paths)) or []
    )
    check_changes.collect(
        str(tmp_path),
        {
            "templates/a.html": WHOLE_FILE,
            "static/css/components/buttons.css": WHOLE_FILE,
            "notes.html": WHOLE_FILE,
        },
    )

    assert calls == [["static/css/components/buttons.css", "templates/a.html"]]


def test_collect_lints_a_changed_jx_file(tmp_path, monkeypatch):
    from scripts import check_changes
    from scripts.change_selection import WHOLE_FILE

    (tmp_path / "templates" / "pages").mkdir(parents=True)
    write(tmp_path / "templates" / "pages" / "home.jx", "<div></div>\n")

    calls = []
    monkeypatch.setattr(
        check_changes, "ast_grep_findings", lambda root, paths: calls.append(sorted(paths)) or []
    )
    check_changes.collect(str(tmp_path), {"templates/pages/home.jx": WHOLE_FILE})

    assert calls == [["templates/pages/home.jx"]]


def test_collect_runs_the_jx_lint_on_the_changed_lines_of_a_jx_file(tmp_path, monkeypatch):
    from scripts import check_changes

    (tmp_path / "templates" / "pages").mkdir(parents=True)
    write(tmp_path / "templates" / "pages" / "home.jx", '<div class="clay-card"></div>\n<p class="btn-clay"></p>\n')
    monkeypatch.setattr(check_changes, "ast_grep_findings", lambda root, paths: [])

    problems = check_changes.collect(str(tmp_path), {"templates/pages/home.jx": [(2, 2)]})

    assert len(problems) == 1
    assert "templates/pages/home.jx:2: no-raw-clay-class" in problems[0]


def test_ast_grep_crash_is_reported_not_silently_passed(tmp_path, monkeypatch):
    # Exit 1 means "found errors"; anything else (bad rule YAML, bad config)
    # means nothing was linted, so the hook must say so.
    import subprocess

    from scripts import check_changes
    from scripts.change_selection import WHOLE_FILE

    (tmp_path / "templates").mkdir()
    write(tmp_path / "templates" / "a.html", "<div></div>\n")
    write(tmp_path / "sgconfig.yml", "ruleDirs: [lint/rules]\n")

    monkeypatch.setattr(check_changes.shutil, "which", lambda name, path=None: "ast-grep")
    monkeypatch.setattr(
        check_changes.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 2, stdout="", stderr="Error: Cannot parse rule lint/rules/bad.yml"
        ),
    )
    problems = check_changes.collect(str(tmp_path), {"templates/a.html": WHOLE_FILE})

    assert len(problems) == 1
    assert "ast-grep" in problems[0]
    assert "Cannot parse rule lint/rules/bad.yml" in problems[0]


# --------------------------------------------------------------------------
# css syntax
# --------------------------------------------------------------------------


def test_unclosed_css_block_is_reported_at_its_opening_brace():
    from scripts.check_changes import css_brace_errors

    errors = css_brace_errors(".a { color: red; }\n.b {\n  color: blue;\n.c { color: green; }\n")

    assert errors == [(2, "`{` is never closed")]


def test_stray_css_closing_brace_is_reported():
    from scripts.check_changes import css_brace_errors

    errors = css_brace_errors(".a { color: red; }\n}\n")

    assert errors == [(2, "`}` has no matching `{`")]


def test_unterminated_css_comment_is_reported():
    from scripts.check_changes import css_brace_errors

    errors = css_brace_errors(".a { color: red; }\n/* note\n.b { color: blue; }\n")

    assert errors == [(2, "comment is never closed")]


def test_braces_in_css_comments_strings_and_nested_rules_are_not_errors():
    from scripts.check_changes import css_brace_errors

    text = (
        "/* .x { */\n"
        ".a::after { content: \"}\"; }\n"
        ".b::before { content: '{'; }\n"
        "@media (min-width: 40rem) {\n"
        "  .c { @apply flex; }\n"
        "}\n"
    )

    assert css_brace_errors(text) == []


def test_collect_reports_broken_css_in_a_page_stylesheet(tmp_path, monkeypatch):
    from scripts import check_changes
    from scripts.change_selection import WHOLE_FILE

    styles = tmp_path / "static" / "css" / "pages"
    styles.mkdir(parents=True)
    write(styles / "quiz.css", ".quiz {\n  color: red;\n")
    monkeypatch.setattr(check_changes, "ast_grep_findings", lambda root, paths: [])

    problems = check_changes.collect(str(tmp_path), {"static/css/pages/quiz.css": WHOLE_FILE})

    assert problems == ["static/css/pages/quiz.css:1: `{` is never closed"]


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------


def test_collect_routes_each_path_to_its_checker(tmp_path, monkeypatch):
    from scripts import check_changes
    from scripts.change_selection import WHOLE_FILE

    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    write(rules / "ui-core.md", "Fixed 2026-05-01.\n")
    write(tmp_path / "m.py", JUSTIFYING)
    write(tmp_path / "notes.txt", "2026-05-01\n")

    monkeypatch.setattr(check_changes, "check_class_index", lambda root: [])
    problems = check_changes.collect(
        str(tmp_path),
        {
            ".claude/rules/ui-core.md": WHOLE_FILE,
            "m.py": WHOLE_FILE,
            "notes.txt": WHOLE_FILE,
        },
    )

    assert len(problems) == 2
    assert not any("notes.txt" in problem for problem in problems)


def test_collect_flags_a_dated_line_in_a_nested_docs_file(tmp_path):
    from scripts import check_changes
    from scripts.change_selection import WHOLE_FILE

    folder = tmp_path / "docs" / "ui-design"
    folder.mkdir(parents=True)
    write(folder / "building-ui.md", "Fixed 2026-05-01.\n")

    problems = check_changes.collect(str(tmp_path), {"docs/ui-design/building-ui.md": WHOLE_FILE})

    assert len(problems) == 1
    assert "docs/ui-design/building-ui.md" in problems[0]


def test_collect_leaves_dates_in_adrs_alone(tmp_path):
    from scripts import check_changes
    from scripts.change_selection import WHOLE_FILE

    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    write(adr / "0001-x.md", "Decided 2026-05-01.\n")

    assert check_changes.collect(str(tmp_path), {"docs/adr/0001-x.md": WHOLE_FILE}) == []


def test_collect_runs_the_css_class_check_once_per_run(tmp_path, monkeypatch):
    from scripts import check_changes
    from scripts.change_selection import WHOLE_FILE

    components = tmp_path / "static" / "css" / "components"
    components.mkdir(parents=True)
    write(components / "buttons.css", ".btn {}\n")
    write(components / "cards.css", ".card {}\n")

    calls = []
    monkeypatch.setattr(
        check_changes, "check_class_index", lambda root: calls.append(root) or ["boom"]
    )
    problems = check_changes.collect(
        str(tmp_path),
        {
            "static/css/components/buttons.css": WHOLE_FILE,
            "static/css/components/cards.css": WHOLE_FILE,
        },
    )

    assert calls == [str(tmp_path)]
    assert problems == ["boom"]


def test_collect_skips_a_deleted_file(tmp_path):
    from scripts import check_changes
    from scripts.change_selection import WHOLE_FILE

    problems = check_changes.collect(str(tmp_path), {"gone.py": WHOLE_FILE})

    assert problems == []


def test_main_is_quiet_when_nothing_changed(monkeypatch, capsys):
    from scripts import check_changes

    monkeypatch.setattr(check_changes, "changed_paths", lambda root: {})

    assert check_changes.main([], payload={}) == 0
    assert capsys.readouterr().err == ""


def test_main_blocks_on_a_problem(monkeypatch, capsys):
    from scripts import check_changes

    monkeypatch.setattr(check_changes, "changed_paths", lambda root: {"m.py": "whole-file"})
    monkeypatch.setattr(check_changes, "collect", lambda root, changed: ["m.py:1 bad"])

    assert check_changes.main([], payload={}) == 2
    assert "m.py:1 bad" in capsys.readouterr().err


def test_main_does_not_block_twice_in_a_row(monkeypatch, capsys):
    from scripts import check_changes

    monkeypatch.setattr(check_changes, "changed_paths", lambda root: {"m.py": "whole-file"})
    monkeypatch.setattr(check_changes, "collect", lambda root, changed: ["m.py:1 bad"])

    assert check_changes.main([], payload={"stop_hook_active": True}) == 0
    assert capsys.readouterr().err == ""


def test_main_checks_only_the_paths_given_as_arguments(tmp_path, monkeypatch, capsys):
    from scripts import check_changes

    path = write(tmp_path / "m.py", JUSTIFYING)
    monkeypatch.setattr(
        check_changes,
        "changed_paths",
        lambda root: pytest.fail("explicit paths must not consult git"),
    )

    assert check_changes.main([path], payload={}) == 2
    assert "instead of" in capsys.readouterr().err


def test_git_unavailable_is_not_a_failure(monkeypatch):
    from scripts import check_changes

    monkeypatch.setattr(check_changes, "changed_paths", lambda root: None)

    assert check_changes.main([], payload={}) == 0
