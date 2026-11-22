"""Unit tests for the changed-code test selector behind the default pytest run."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


ROUTE_SOURCE = '''
from flask import Blueprint, render_template
from helpers.matching import score_match

teacher_bp = Blueprint("teacher", __name__, url_prefix="/teacher")

CAPACITY = 4


@teacher_bp.route("/roster")
def roster():
    return render_template("teacher/roster.html", rows=score_match(1, 2))


@teacher_bp.route("/pair/<int:pair_id>", methods=["POST"])
def pair_detail(pair_id):
    return str(pair_id)


class RosterView:
    def render(self):
        return roster()
'''


def test_parse_unified_diff_reads_new_file_line_ranges():
    from scripts.change_selection import parse_unified_diff

    diff = (
        "diff --git a/routes/teacher.py b/routes/teacher.py\n"
        "--- a/routes/teacher.py\n"
        "+++ b/routes/teacher.py\n"
        "@@ -10,0 +11,2 @@\n"
        "+one\n"
        "+two\n"
        "@@ -40,2 +42,0 @@\n"
        "-gone\n"
        "-gone\n"
    )

    assert parse_unified_diff(diff) == {"routes/teacher.py": [(11, 12), (42, 42)]}


def test_parse_unified_diff_marks_a_new_file_as_whole_file_changed():
    from scripts.change_selection import WHOLE_FILE, parse_unified_diff

    diff = (
        "diff --git a/helpers/new.py b/helpers/new.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/helpers/new.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+a\n+b\n+c\n"
    )

    assert parse_unified_diff(diff)["helpers/new.py"] == WHOLE_FILE


def test_parse_unified_diff_ignores_a_deleted_file():
    from scripts.change_selection import parse_unified_diff

    diff = (
        "diff --git a/helpers/old.py b/helpers/old.py\n"
        "deleted file mode 100644\n"
        "--- a/helpers/old.py\n"
        "+++ /dev/null\n"
        "@@ -1,3 +0,0 @@\n"
        "-a\n-b\n-c\n"
    )

    assert parse_unified_diff(diff) == {}


def test_index_source_records_functions_methods_routes_and_templates():
    from scripts.change_selection import index_source

    index = index_source("routes/teacher.py", "routes.teacher", ROUTE_SOURCE)
    symbols = {symbol.qualname: symbol for symbol in index.symbols}

    assert set(symbols) == {"roster", "pair_detail", "RosterView", "RosterView.render"}
    assert symbols["roster"].urls == ("/teacher/roster",)
    assert symbols["roster"].templates == ("teacher/roster.html",)
    assert "score_match" in symbols["roster"].refs
    # A rule with a converter can only be matched as a prefix, which the
    # trailing slash records.
    assert symbols["pair_detail"].urls == ("/teacher/pair/",)
    assert "roster" in symbols["RosterView.render"].refs


def test_index_source_survives_a_file_that_does_not_parse():
    from scripts.change_selection import index_source

    index = index_source("routes/broken.py", "routes.broken", "def oops(:\n")

    assert index.symbols == ()
    assert index.unparsed is True


def test_symbols_touched_maps_a_line_inside_a_function_to_that_function():
    from scripts.change_selection import index_source, symbols_touched

    index = index_source("routes/teacher.py", "routes.teacher", ROUTE_SOURCE)
    line = ROUTE_SOURCE.splitlines().index("def pair_detail(pair_id):") + 2

    touched, module_level = symbols_touched(index, [(line, line)])

    assert touched == {"pair_detail"}
    assert module_level is False


def test_symbols_touched_flags_a_module_level_edit():
    from scripts.change_selection import index_source, symbols_touched

    index = index_source("routes/teacher.py", "routes.teacher", ROUTE_SOURCE)
    line = ROUTE_SOURCE.splitlines().index("CAPACITY = 4") + 1

    _, module_level = symbols_touched(index, [(line, line)])

    assert module_level is True


def test_symbols_touched_takes_the_whole_file_for_a_new_file():
    from scripts.change_selection import WHOLE_FILE, index_source, symbols_touched

    index = index_source("routes/teacher.py", "routes.teacher", ROUTE_SOURCE)

    touched, module_level = symbols_touched(index, WHOLE_FILE)

    assert module_level is True
    assert "roster" in touched


def test_expand_callers_pulls_in_the_route_that_calls_a_changed_helper():
    from scripts.change_selection import expand_callers, index_source

    helper = index_source(
        "helpers/matching.py",
        "helpers.matching",
        "def score_match(a, b):\n    return 1\n",
    )
    route = index_source("routes/teacher.py", "routes.teacher", ROUTE_SOURCE)
    indexes = {helper.path: helper, route.path: route}

    reached = expand_callers({("helpers/matching.py", "score_match")}, indexes)

    assert ("routes/teacher.py", "roster") in reached
    # and one hop further out: the method that calls that route function
    assert ("routes/teacher.py", "RosterView.render") in reached


def test_index_tests_splits_module_level_and_per_test_references():
    from scripts.change_selection import index_tests

    source = (
        "import pytest\n"
        "from helpers.matching import score_match\n"
        "\n"
        "pytestmark = pytest.mark.unit\n"
        "\n"
        "def test_scores():\n"
        "    assert score_match(1, 2)\n"
        "\n"
        "def test_roster(client):\n"
        "    assert client.get('/teacher/roster').status_code == 200\n"
    )

    index = index_tests("tests/unit/test_matching.py", source)

    assert "helpers.matching" in index.file_refs
    assert set(index.tests) == {"test_scores", "test_roster"}
    assert "score_match" in index.tests["test_scores"].refs
    assert "/teacher/roster" in index.tests["test_roster"].literals


def test_url_matches_is_exact_for_a_rule_without_a_converter():
    from scripts.change_selection import url_matches

    assert url_matches("/teacher/", "/teacher")
    assert url_matches("/teacher?tab=roster", "/teacher")
    # a bare blueprint root must not claim everything mounted under it
    assert not url_matches("/teacher/roster", "/teacher")
    # a converter rule matches the whole subtree under it
    assert url_matches("/teacher/pair/3", "/teacher/pair/")
    assert not url_matches("/teacher/pairing", "/teacher/pair/")


def test_a_marker_the_suite_does_not_run_is_left_out(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)
    (tmp_path / "tests" / "web" / "test_teacher.py").write_text(
        "import pytest\n"
        "\n"
        "@pytest.mark.web\n"
        "def test_roster(client):\n"
        "    assert client.get('/teacher/roster').status_code == 200\n"
        "\n"
        "@pytest.mark.slow\n"
        "def test_roster_pdf(client):\n"
        "    assert client.get('/teacher/roster').status_code == 200\n",
        encoding="utf-8",
    )

    selection = compute_selection(
        tmp_path,
        ["tests/unit", "tests/web"],
        git_runner=_fake_git({"routes/teacher.py": [(11, 11)]}),
        wanted_marks={"unit", "web"},
        breadth_limit=1.0,
    )

    assert selection is not None
    assert selection.node_ids() == ["tests/web/test_teacher.py::test_roster"]


def test_select_tests_matches_by_symbol_name_and_by_url():
    from scripts.change_selection import Signals, index_tests, select_tests

    source = (
        "def test_scores():\n"
        "    from helpers.matching import score_match\n"
        "    assert score_match(1, 2)\n"
        "\n"
        "def test_roster(client):\n"
        "    assert client.get('/teacher/roster')\n"
        "\n"
        "def test_unrelated(client):\n"
        "    assert client.get('/about')\n"
    )
    index = index_tests("tests/web/test_x.py", source)

    by_name = select_tests(Signals(names={"score_match"}, modules=set(), urls=set()), [index])
    by_url = select_tests(Signals(names=set(), modules=set(), urls={"/teacher/roster"}), [index])

    assert by_name == {"tests/web/test_x.py": {"test_scores"}}
    assert by_url == {"tests/web/test_x.py": {"test_roster"}}


def test_select_tests_takes_every_test_in_a_file_whose_module_level_code_matches():
    from scripts.change_selection import Signals, index_tests, select_tests

    source = (
        "from helpers.matching import score_match\n"
        "\n"
        "def test_one():\n"
        "    assert True\n"
        "\n"
        "def test_two():\n"
        "    assert True\n"
    )
    index = index_tests("tests/unit/test_m.py", source)

    selected = select_tests(Signals(names=set(), modules={"helpers.matching"}, urls=set()), [index])

    assert selected == {"tests/unit/test_m.py": {"test_one", "test_two"}}


def test_a_changed_test_file_selects_its_own_tests(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)

    selection = compute_selection(
        tmp_path,
        ["tests/unit", "tests/web"],
        git_runner=_fake_git({"tests/unit/test_matching.py": [(3, 4)]}),
    )

    assert selection is not None
    assert selection.node_ids() == ["tests/unit/test_matching.py::test_scores"]


def test_a_changed_helper_reaches_the_route_test_through_its_caller(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)

    selection = compute_selection(
        tmp_path,
        ["tests/unit", "tests/web"],
        git_runner=_fake_git({"helpers/matching.py": [(2, 2)]}),
        # The toy repo only holds three tests, so the real breadth guard would
        # reject the selection for covering too much of it.
        breadth_limit=1.0,
    )

    assert selection is not None
    node_ids = selection.node_ids()
    assert "tests/web/test_teacher.py::test_roster" in node_ids
    assert "tests/web/test_teacher.py::test_unrelated" not in node_ids


def test_no_git_changes_means_run_everything(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)

    assert compute_selection(tmp_path, ["tests/unit"], git_runner=_fake_git({})) is None


def test_a_broken_git_means_run_everything(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)

    def explode(args):
        raise OSError("git is not installed")

    assert compute_selection(tmp_path, ["tests/unit"], git_runner=explode) is None


def test_touching_shared_test_scaffolding_means_run_everything(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)

    selection = compute_selection(
        tmp_path,
        ["tests/unit", "tests/web"],
        git_runner=_fake_git({"tests/conftest.py": [(1, 1)]}),
    )

    assert selection is None


def test_the_fallback_names_the_file_that_forced_it(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)
    notes = []

    compute_selection(
        tmp_path,
        ["tests/unit", "tests/web"],
        git_runner=_fake_git({"tests/conftest.py": [(1, 1)]}),
        notes=notes,
    )

    assert notes == ["tests/conftest.py changed"]


def test_the_fallback_says_when_nothing_changed(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)
    notes = []

    compute_selection(tmp_path, ["tests/unit"], git_runner=_fake_git({}), notes=notes)

    assert notes == ["nothing changed since HEAD"]


def test_the_fallback_says_when_the_change_is_too_broad(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)
    notes = []

    compute_selection(
        tmp_path,
        ["tests/unit", "tests/web"],
        git_runner=_fake_git({"helpers/matching.py": [(2, 2)]}),
        breadth_limit=0.1,
        notes=notes,
    )

    assert notes == ["2 of 3 tests reached, over the 10% limit"]


def test_a_change_nothing_maps_to_means_run_everything(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "app.css").write_text("body{}", encoding="utf-8")

    selection = compute_selection(
        tmp_path,
        ["tests/unit", "tests/web"],
        git_runner=_fake_git({"static/app.css": [(1, 1)]}),
    )

    assert selection is None


def test_a_change_touching_most_of_the_suite_means_run_everything(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)

    selection = compute_selection(
        tmp_path,
        ["tests/unit", "tests/web"],
        git_runner=_fake_git({"helpers/matching.py": [(2, 2)]}),
        breadth_limit=0.1,
    )

    assert selection is None


def test_a_changed_template_selects_the_route_that_renders_it(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)

    selection = compute_selection(
        tmp_path,
        ["tests/unit", "tests/web"],
        git_runner=_fake_git({"templates/teacher/roster.html": [(1, 1)]}),
    )

    assert selection is not None
    assert "tests/web/test_teacher.py::test_roster" in selection.node_ids()


def test_a_changed_jx_page_selects_the_route_that_renders_it(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)
    (tmp_path / "routes" / "teacher.py").write_text(
        ROUTE_SOURCE.replace('"teacher/roster.html"', '"@pages/teacher/roster.jx"'), encoding="utf-8"
    )

    selection = compute_selection(
        tmp_path,
        ["tests/unit", "tests/web"],
        git_runner=_fake_git({"templates/pages/teacher/roster.jx": [(1, 1)]}),
    )

    assert selection is not None
    assert "tests/web/test_teacher.py::test_roster" in selection.node_ids()


def test_a_changed_shared_component_runs_everything(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)

    selection = compute_selection(
        tmp_path,
        ["tests/unit", "tests/web"],
        git_runner=_fake_git({"templates/components/button.jx": [(1, 1)]}),
    )

    assert selection is None


def test_a_changed_shared_component_runs_everything_even_beside_a_mapped_change(tmp_path):
    from scripts.change_selection import compute_selection

    _write_fake_repo(tmp_path)

    selection = compute_selection(
        tmp_path,
        ["tests/unit", "tests/web"],
        git_runner=_fake_git({
            "templates/components/button.jx": [(1, 1)],
            "helpers/matching.py": [(2, 2)],
        }),
        breadth_limit=1.0,  # only the unmapped component may force the full run
    )

    assert selection is None


def _fake_git(files):
    """A git runner that reports `files` as changed against HEAD."""

    def run(args):
        if "ls-files" in args:
            return ""
        chunks = []
        for path, ranges in files.items():
            chunks.append(f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n")
            for start, end in ranges:
                chunks.append(f"@@ -{start},1 +{start},{end - start + 1} @@\n")
        return "".join(chunks)

    return run


def _write_fake_repo(root):
    (root / "helpers").mkdir(parents=True)
    (root / "routes").mkdir()
    (root / "templates" / "teacher").mkdir(parents=True)
    (root / "tests" / "unit").mkdir(parents=True)
    (root / "tests" / "web").mkdir(parents=True)

    (root / "helpers" / "matching.py").write_text(
        "def score_match(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (root / "routes" / "teacher.py").write_text(ROUTE_SOURCE, encoding="utf-8")
    (root / "templates" / "teacher" / "roster.html").write_text("<p>x</p>\n", encoding="utf-8")
    (root / "tests" / "conftest.py").write_text("", encoding="utf-8")
    (root / "tests" / "unit" / "test_matching.py").write_text(
        "from helpers.matching import score_match\n"
        "\n"
        "def test_scores():\n"
        "    assert score_match(1, 2) == 3\n",
        encoding="utf-8",
    )
    (root / "tests" / "web" / "test_teacher.py").write_text(
        "def test_roster(client):\n"
        "    assert client.get('/teacher/roster').status_code == 200\n"
        "\n"
        "def test_unrelated(client):\n"
        "    assert client.get('/about').status_code == 200\n",
        encoding="utf-8",
    )
