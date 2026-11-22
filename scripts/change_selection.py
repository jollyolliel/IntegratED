"""Pick the tests worth running for the code that is currently changed.

The default ``pytest`` run asks git what is different from ``HEAD`` (staged,
unstaged and untracked), maps those line ranges onto the functions and classes
that contain them, walks one or two hops out to whatever calls them, and turns
that into a set of test node ids. Anything ambiguous falls back to running the
whole suite — a fast run that misses a regression would be worse than a slow
one.

The whole pass is static: one ``git diff``, then ``ast.parse`` over the source
and test trees. Nothing here imports application code.

Used by ``tests/conftest.py``. See ``docs/development/testing.md``.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

#: Sentinel line range meaning "treat every line of the file as changed".
WHOLE_FILE = "whole-file"

#: Directories and files whose Python is mapped to tests symbol by symbol.
WATCHED_SOURCE_DIRS = ("routes", "helpers")
WATCHED_SOURCE_FILES = ("models.py", "commands.py", "extensions.py", "main.py")

#: Template edits are mapped through the view functions that render them.
TEMPLATE_DIR = "templates"

#: Editing any of these changes how every test runs, so narrowing is unsafe.
FULL_SUITE_TRIGGERS = (
    "tests/conftest.py",
    "tests/support/",
    "pyproject.toml",
    "uv.lock",
    ".coveragerc",
    "scripts/change_selection.py",
)

#: Identifiers too common to carry any signal about what changed.
GENERIC_NAMES = frozenset(
    {
        "get",
        "post",
        "put",
        "delete",
        "run",
        "main",
        "app",
        "db",
        "session",
        "query",
        "data",
        "index",
        "test",
        "setup",
        "value",
        "name",
        "self",
        "cls",
    }
)

#: A selection wider than this share of the suite is not worth the bookkeeping.
DEFAULT_BREADTH_LIMIT = 0.6

#: How many hops of "who calls this" to follow out from a changed symbol.
CALLER_DEPTH = 2

#: A name referenced by more symbols than this is plumbing, not a call edge.
CALLER_FANOUT_LIMIT = 40


@dataclass(frozen=True)
class Symbol:
    """One function, method or class, and what it points at."""

    qualname: str
    start: int
    end: int
    refs: frozenset[str]
    urls: tuple[str, ...] = ()
    raw_urls: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.qualname.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class ModuleIndex:
    """The symbols of one source module plus its module-level references."""

    path: str
    module: str
    symbols: tuple[Symbol, ...] = ()
    module_refs: frozenset[str] = frozenset()
    unparsed: bool = False


@dataclass(frozen=True)
class TestRefs:
    refs: frozenset[str]
    literals: frozenset[str]
    marks: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TestFileIndex:
    path: str
    file_refs: frozenset[str]
    file_literals: frozenset[str]
    tests: dict[str, TestRefs]
    module_marks: frozenset[str] = frozenset()

    def marks_for(self, name: str) -> frozenset[str]:
        test = self.tests.get(name)
        return self.module_marks | (test.marks if test else frozenset())


@dataclass
class Signals:
    """What a change is recognisable by, from a test's point of view."""

    names: set[str] = field(default_factory=set)
    modules: set[str] = field(default_factory=set)
    urls: set[str] = field(default_factory=set)

    def __bool__(self) -> bool:
        return bool(self.names or self.modules or self.urls)


@dataclass
class Selection:
    """The tests to run, and the human-readable reasons they were picked."""

    files: dict[str, set[str]]
    reasons: list[str] = field(default_factory=list)
    total_tests: int = 0

    def node_ids(self) -> list[str]:
        return sorted(
            f"{path}::{test}" for path, tests in self.files.items() for test in tests
        )

    @property
    def count(self) -> int:
        return sum(len(tests) for tests in self.files.values())


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------


def _git(root: Path):
    def run(args: list[str]) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,  # returncode handled explicitly below
        )
        if result.returncode != 0:
            raise OSError(result.stderr.strip() or "git failed")
        return result.stdout

    return run


def parse_unified_diff(text: str) -> dict[str, object]:
    """Map each file in a ``--unified=0`` diff to its changed line ranges.

    Ranges are line numbers in the *new* file. A pure deletion has no new
    lines, so it is recorded as the single line it collapsed onto — that is
    the line whose enclosing function lost code. Added files come back as
    :data:`WHOLE_FILE`; deleted files are dropped, since there is nothing left
    to attribute the change to.
    """

    changed: dict[str, object] = {}
    path: str | None = None
    is_new = False
    is_deleted = False

    for line in text.splitlines():
        if line.startswith("diff --git "):
            path, is_new, is_deleted = None, False, False
            continue
        if line.startswith("new file mode"):
            is_new = True
            continue
        if line.startswith("deleted file mode"):
            is_deleted = True
            continue
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target == "/dev/null":
                path = None
                continue
            path = target.removeprefix("b/")
            if is_deleted:
                path = None
            elif is_new:
                changed[path] = WHOLE_FILE
            continue
        if line.startswith("@@") and path and changed.get(path) is not WHOLE_FILE:
            span = _hunk_span(line)
            if span is not None:
                changed.setdefault(path, []).append(span)  # ty: ignore[unresolved-attribute]  # guarded non-WHOLE_FILE above, so this is always list-shaped

    return {key: value for key, value in changed.items() if value}


def _hunk_span(header: str) -> tuple[int, int] | None:
    """``@@ -3,4 +7,2 @@`` -> ``(7, 8)``; a zero-length hunk -> that one line."""

    try:
        new_part = header.split("+", 1)[1].split("@@", 1)[0].strip()
    except IndexError:
        return None
    start_text, _, count_text = new_part.partition(",")
    try:
        start = int(start_text)
        count = int(count_text) if count_text else 1
    except ValueError:
        return None
    if count == 0:
        # A deletion: attribute it to the line it now sits above.
        return (max(start, 1), max(start, 1))
    return (start, start + count - 1)


def changed_paths(root: Path, git_runner=None) -> dict[str, object] | None:
    """Everything different from ``HEAD``, including untracked files.

    Returns ``None`` when git cannot answer — no repository, no git binary, a
    fresh repo with no commits.
    """

    run = git_runner or _git(root)
    try:
        diff = run(["diff", "HEAD", "--unified=0", "--no-color", "--no-ext-diff"])
        untracked = run(["ls-files", "--others", "--exclude-standard"])
    except (OSError, subprocess.SubprocessError):
        return None

    changed = parse_unified_diff(diff)
    for line in untracked.splitlines():
        name = line.strip()
        if name:
            changed[name] = WHOLE_FILE
    return changed


# --------------------------------------------------------------------------
# source indexing
# --------------------------------------------------------------------------


class _RefCollector(ast.NodeVisitor):
    """Every identifier, dotted import and interesting literal in a subtree."""

    def __init__(self) -> None:
        self.refs: set[str] = set()
        self.literals: set[str] = set()
        self.templates: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        self.refs.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.refs.add(node.attr)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.refs.add(alias.name)
            self.refs.add(alias.name.split(".", 1)[0])
            if alias.asname:
                self.refs.add(alias.asname)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.refs.add(node.module)
            self.refs.add(node.module.rsplit(".", 1)[-1])
        for alias in node.names:
            self.refs.add(alias.name)
            if alias.asname:
                self.refs.add(alias.asname)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            if node.value.startswith("/"):
                self.literals.add(node.value)
            elif node.value.endswith((".html", ".jinja", ".jx")):
                # A jx name is `@` + its path under templates/ (helpers/jx_catalog.py).
                self.templates.add(node.value.removeprefix("@"))


def _collect(nodes) -> _RefCollector:
    collector = _RefCollector()
    for node in nodes:
        collector.visit(node)
    return collector


def _blueprint_prefix(tree: ast.Module) -> str:
    """The ``url_prefix=`` of the first ``Blueprint(...)`` built in a module."""

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if called != "Blueprint":
            continue
        for keyword in node.keywords:
            if keyword.arg == "url_prefix" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value)
    return ""


def _route_paths(node) -> list[str]:
    """Raw path strings from ``@x.route("/p")`` / ``@app.get("/p")`` decorators."""

    paths = []
    for decorator in getattr(node, "decorator_list", []):
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not isinstance(func, ast.Attribute) or func.attr not in {
            "route",
            "get",
            "post",
            "put",
            "patch",
            "delete",
        }:
            continue
        for arg in decorator.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                paths.append(arg.value)
    return paths


def _normalise_url(url: str) -> str:
    """Turn a Flask rule into a comparable form.

    A rule with a converter can only ever be matched as a prefix, so it keeps
    a trailing slash to say so (``/teacher/pair/<id>`` -> ``/teacher/pair/``).
    A rule without one is compared exactly, which is what keeps a bare
    dashboard rule from claiming every URL under its blueprint.
    """

    trimmed = url.split("<", 1)[0].rstrip("/")
    if len(trimmed) <= 1:
        return ""
    return f"{trimmed}/" if "<" in url else trimmed


def url_matches(literal: str, candidate: str) -> bool:
    """Does a URL string written in a test correspond to a route rule?"""

    path = literal.split("?", 1)[0].rstrip("/") or "/"
    base = candidate.rstrip("/")
    if candidate.endswith("/"):
        return path == base or path.startswith(f"{base}/")
    return path == base


def index_source(path: str, module: str, source: str) -> ModuleIndex:
    """Index one source module: its symbols, their refs, routes and templates."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ModuleIndex(path=path, module=module, unparsed=True)

    prefix = _blueprint_prefix(tree)
    symbols: list[Symbol] = []
    module_body: list = []

    def walk(body, qual_prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualname = f"{qual_prefix}{node.name}"
                start = min(
                    [node.lineno] + [d.lineno for d in node.decorator_list]
                )
                end = getattr(node, "end_lineno", node.lineno) or node.lineno
                if isinstance(node, ast.ClassDef):
                    own_body = [
                        child
                        for child in node.body
                        if not isinstance(
                            child,
                            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                        )
                    ]
                    collected = _collect(own_body + list(node.decorator_list))
                else:
                    collected = _collect([node])
                # A rule of "/" carries no signal on its own but does once the
                # blueprint's prefix is on the front, so prefix first, trim
                # after.
                rules = _route_paths(node)
                urls = tuple(
                    sorted({url for url in (_normalise_url(prefix + rule) for rule in rules) if url})
                )
                raw = tuple(
                    sorted({url for url in (_normalise_url(rule) for rule in rules) if url})
                )
                symbols.append(
                    Symbol(
                        qualname=qualname,
                        start=start,
                        end=end,
                        refs=frozenset(collected.refs),
                        urls=urls,
                        raw_urls=tuple(raw),
                        templates=tuple(sorted(collected.templates)),
                    )
                )
                if isinstance(node, ast.ClassDef):
                    walk(node.body, f"{qualname}.")
            else:
                module_body.append(node)

    walk(tree.body, "")
    module_level = _collect(module_body)
    return ModuleIndex(
        path=path,
        module=module,
        symbols=tuple(symbols),
        module_refs=frozenset(module_level.refs),
    )


def symbols_touched(index: ModuleIndex, ranges) -> tuple[set[str], bool]:
    """Which symbols a set of changed line ranges lands in.

    The second value is ``True`` when a change landed outside every symbol —
    an import, a constant, a decorator table — which can affect the whole
    module, so the caller widens to every symbol in the file.
    """

    if ranges is WHOLE_FILE or index.unparsed:
        return {symbol.qualname for symbol in index.symbols}, True

    touched: set[str] = set()
    module_level = False
    for start, end in ranges:
        hit = False
        for symbol in index.symbols:
            if start <= symbol.end and end >= symbol.start:
                touched.add(symbol.qualname)
                hit = True
        if not hit:
            module_level = True

    if module_level:
        touched |= {symbol.qualname for symbol in index.symbols}
    return touched, module_level


def expand_callers(
    seeds: set[tuple[str, str]],
    indexes: dict[str, ModuleIndex],
    depth: int = CALLER_DEPTH,
    fanout_limit: int = CALLER_FANOUT_LIMIT,
) -> set[tuple[str, str]]:
    """Walk out from changed symbols to the symbols that reference them."""

    callers_of: dict[str, set[tuple[str, str]]] = {}
    for index in indexes.values():
        for symbol in index.symbols:
            for ref in symbol.refs:
                callers_of.setdefault(ref, set()).add((index.path, symbol.qualname))

    reached = set(seeds)
    frontier = set(seeds)
    for _ in range(depth):
        found: set[tuple[str, str]] = set()
        for path, qualname in frontier:
            name = qualname.rsplit(".", 1)[-1]
            callers = callers_of.get(name, set())
            if not callers or len(callers) > fanout_limit:
                continue
            found |= callers - reached
        if not found:
            break
        reached |= found
        frontier = found
    return reached


# --------------------------------------------------------------------------
# test indexing
# --------------------------------------------------------------------------


def _mark_names(nodes) -> set[str]:
    """``pytest.mark.web`` / ``pytest.mark.parametrize(...)`` -> ``{"web", …}``."""

    names: set[str] = set()
    for node in nodes:
        target = node.func if isinstance(node, ast.Call) else node
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Attribute)
            and target.value.attr == "mark"
        ):
            names.add(target.attr)
    return names


def _module_marks(tree: ast.Module) -> set[str]:
    """Marks from a module-level ``pytestmark = …`` assignment."""

    marks: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in node.targets
        ):
            continue
        value = node.value
        items = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
        marks |= _mark_names(items)
    return marks


def index_tests(path: str, source: str) -> TestFileIndex:
    """Index one test module: module-level refs plus per-test refs and marks."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        # An unparseable test file is its own failure; keep it selectable.
        return TestFileIndex(path, frozenset({"*"}), frozenset(), {})

    tests: dict[str, TestRefs] = {}
    shared: list = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test"
        ):
            collected = _collect([node])
            tests[node.name] = TestRefs(
                refs=frozenset(collected.refs),
                literals=frozenset(collected.literals | collected.templates),
                marks=frozenset(_mark_names(node.decorator_list)),
            )
        else:
            shared.append(node)

    module_level = _collect(shared)
    return TestFileIndex(
        path=path,
        file_refs=frozenset(module_level.refs),
        file_literals=frozenset(module_level.literals | module_level.templates),
        tests=tests,
        module_marks=frozenset(_module_marks(tree)),
    )


def _matches(refs, literals, signals: Signals) -> bool:
    if refs & signals.names or refs & signals.modules:
        return True
    if "*" in refs:
        return True
    return any(
        url_matches(literal, url) for literal in literals for url in signals.urls
    )


def select_tests(signals: Signals, indexes) -> dict[str, set[str]]:
    """Tests whose own code — or their file's shared code — matches a signal."""

    selected: dict[str, set[str]] = {}
    for index in indexes:
        if _matches(index.file_refs, index.file_literals, signals):
            if index.tests:
                selected[index.path] = set(index.tests)
            continue
        hits = {
            name
            for name, test in index.tests.items()
            if _matches(test.refs, test.literals, signals)
        }
        if hits:
            selected[index.path] = hits
    return selected


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


def _module_name(rel_path: str) -> str:
    return rel_path[:-3].replace("/", ".").replace("\\", ".")


def _iter_source_files(root: Path):
    for name in WATCHED_SOURCE_FILES:
        candidate = root / name
        if candidate.is_file():
            yield name
    for directory in WATCHED_SOURCE_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path.relative_to(root).as_posix()


def _iter_test_files(root: Path, test_dirs):
    for directory in test_dirs:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("test_*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path.relative_to(root).as_posix()


def _load_index(root: Path, cache: dict | None, rel_path: str, builder):
    """Build an index for one file, reusing a cache entry when it is current."""

    full = root / rel_path
    try:
        stat = full.stat()
    except OSError:
        return None
    stamp = [int(stat.st_mtime_ns), stat.st_size]
    if cache is not None:
        entry = cache.get(rel_path)
        if entry and entry.get("stamp") == stamp:
            return entry["index"]
    try:
        source = full.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    index = builder(rel_path, source)
    if cache is not None:
        cache[rel_path] = {"stamp": stamp, "index": index}
    return index


def compute_selection(
    root,
    test_dirs,
    git_runner=None,
    breadth_limit: float = DEFAULT_BREADTH_LIMIT,
    cache: dict | None = None,
    wanted_marks=None,
    notes: list | None = None,
) -> Selection | None:
    """The tests worth running right now, or ``None`` to run everything.

    ``None`` is the answer whenever narrowing would be a guess: git cannot
    report, nothing changed, shared test scaffolding changed, the change maps
    to no test at all, or the mapping fans out over most of the suite. Every
    one of those appends the reason to ``notes`` — a silent fallback reads as a
    broken selector.
    """

    def give_up(reason: str) -> None:
        if notes is not None:
            notes.append(reason)

    root = Path(root)
    changed = changed_paths(root, git_runner)
    if changed is None:
        return give_up("git could not report what changed")
    if not changed:
        return give_up("nothing changed since HEAD")

    reasons: list[str] = []
    changed_tests: dict[str, object] = {}
    changed_sources: dict[str, object] = {}
    changed_templates: list[str] = []

    for raw_path, ranges in changed.items():
        path = raw_path.replace("\\", "/")
        trigger = next(
            (t for t in FULL_SUITE_TRIGGERS if path == t or path.startswith(t)), None
        )
        if trigger is not None:
            return give_up(f"{path} changed")
        if path.startswith(f"{TEMPLATE_DIR}/"):
            changed_templates.append(path[len(TEMPLATE_DIR) + 1 :])
            continue
        if any(path.startswith(f"{directory}/") for directory in test_dirs):
            if path.endswith(".py"):
                changed_tests[path] = ranges
            continue
        if path.startswith("tests/"):
            continue  # a layer this suite does not run
        if not path.endswith(".py"):
            continue
        in_watched_dir = any(
            path.startswith(f"{directory}/") for directory in WATCHED_SOURCE_DIRS
        )
        if in_watched_dir or path in WATCHED_SOURCE_FILES:
            changed_sources[path] = ranges

    if not (changed_tests or changed_sources or changed_templates):
        return give_up("no mapped file changed")

    source_cache = cache.setdefault("source", {}) if cache is not None else None
    test_cache = cache.setdefault("tests", {}) if cache is not None else None

    source_indexes: dict[str, ModuleIndex] = {}
    for rel_path in _iter_source_files(root):
        index = _load_index(
            root,
            source_cache,
            rel_path,
            lambda path, text: index_source(path, _module_name(path), text),
        )
        if index is not None:
            source_indexes[rel_path] = index

    seeds: set[tuple[str, str]] = set()
    signals = Signals()

    for path, ranges in changed_sources.items():
        index = source_indexes.get(path)
        if index is None:
            source = (root / path).read_text(encoding="utf-8", errors="replace")
            index = index_source(path, _module_name(path), source)
            source_indexes[path] = index
        touched, module_level = symbols_touched(index, ranges)
        seeds |= {(path, qualname) for qualname in touched}
        if module_level:
            signals.modules.add(index.module)
            signals.modules.add(index.module.rsplit(".", 1)[-1])
        reasons.append(
            f"{path}: {', '.join(sorted(touched)[:4]) or 'module level'}"
            + (" +more" if len(touched) > 4 else "")
        )

    for template in changed_templates:
        renderers = {
            (index.path, symbol.qualname)
            for index in source_indexes.values()
            for symbol in index.symbols
            if template in symbol.templates
        }
        if not renderers:  # a shared component, partial or include: its reach is unknown
            return give_up(f"templates/{template} changed and no view renders it by name")
        seeds |= renderers
        reasons.append(f"templates/{template}: {len(renderers)} view(s)")

    if seeds:
        for path, qualname in expand_callers(seeds, source_indexes):
            index = source_indexes.get(path)
            if index is None:
                continue
            for symbol in index.symbols:
                if symbol.qualname != qualname:
                    continue
                name = symbol.name
                if len(name) > 2 and name.lower() not in GENERIC_NAMES:
                    signals.names.add(name)
                signals.urls.update(url for url in symbol.urls if url)
                signals.urls.update(url for url in symbol.raw_urls if url)

    test_indexes = []
    for rel_path in _iter_test_files(root, test_dirs):
        index = _load_index(root, test_cache, rel_path, index_tests)
        if index is not None:
            test_indexes.append(index)

    by_path = {index.path: index for index in test_indexes}

    def runnable(path: str, name: str) -> bool:
        """Would this test survive the suite's own marker filter?"""

        if not wanted_marks:
            return True
        index = by_path.get(path)
        return bool(index and index.marks_for(name) & set(wanted_marks))

    total_tests = sum(
        1
        for index in test_indexes
        for name in index.tests
        if runnable(index.path, name)
    )
    selected = select_tests(signals, test_indexes) if signals else {}

    for path, ranges in changed_tests.items():
        index = by_path.get(path)
        if index is None:
            index = _load_index(root, test_cache, path, index_tests)
            if index is None:
                continue
            by_path[path] = index
            total_tests += sum(1 for name in index.tests if runnable(path, name))
        names = _tests_touched(index, ranges, root / path)
        if names:
            selected.setdefault(path, set()).update(names)
            reasons.append(f"{path}: {len(names)} changed test(s)")

    selected = {
        path: {name for name in names if runnable(path, name)}
        for path, names in selected.items()
    }
    selected = {path: names for path, names in selected.items() if names}

    if not selected:
        return give_up("the change reaches no test")

    selection = Selection(files=selected, reasons=reasons, total_tests=total_tests)
    if total_tests and selection.count / total_tests > breadth_limit:
        return give_up(
            f"{selection.count} of {total_tests} tests reached, "
            f"over the {breadth_limit:.0%} limit"
        )
    return selection


def _tests_touched(index: TestFileIndex, ranges, full_path: Path) -> set[str]:
    """Which tests in an edited test file the edit landed in."""

    if ranges is WHOLE_FILE:
        return set(index.tests)
    try:
        tree = ast.parse(full_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return set(index.tests)

    spans = {
        node.name: (
            min([node.lineno] + [d.lineno for d in node.decorator_list]),
            getattr(node, "end_lineno", node.lineno) or node.lineno,
        )
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    }

    touched: set[str] = set()
    for start, end in ranges:
        hit = False
        for name, (first, last) in spans.items():
            if start <= last and end >= first:
                touched.add(name)
                hit = True
        if not hit:
            # A shared fixture or import moved: the whole file is in play.
            return set(index.tests)
    return touched


# --------------------------------------------------------------------------
# on-disk cache
# --------------------------------------------------------------------------


def load_cache(path) -> dict:
    """Read the index cache, or start an empty one.

    Cache entries are keyed by path and validated against ``(mtime_ns, size)``,
    so a stale entry is simply rebuilt rather than trusted.
    """

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"source": {}, "tests": {}}
    return {
        "source": {
            key: {"stamp": value["stamp"], "index": _module_from_json(value["index"])}
            for key, value in raw.get("source", {}).items()
        },
        "tests": {
            key: {"stamp": value["stamp"], "index": _test_from_json(value["index"])}
            for key, value in raw.get("tests", {}).items()
        },
    }


def save_cache(path, cache: dict) -> None:
    payload = {
        "source": {
            key: {"stamp": value["stamp"], "index": _module_to_json(value["index"])}
            for key, value in cache.get("source", {}).items()
        },
        "tests": {
            key: {"stamp": value["stamp"], "index": _test_to_json(value["index"])}
            for key, value in cache.get("tests", {}).items()
        },
    }
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass


def _module_to_json(index: ModuleIndex) -> dict:
    return {
        "path": index.path,
        "module": index.module,
        "unparsed": index.unparsed,
        "module_refs": sorted(index.module_refs),
        "symbols": [
            {
                "qualname": symbol.qualname,
                "start": symbol.start,
                "end": symbol.end,
                "refs": sorted(symbol.refs),
                "urls": list(symbol.urls),
                "raw_urls": list(symbol.raw_urls),
                "templates": list(symbol.templates),
            }
            for symbol in index.symbols
        ],
    }


def _module_from_json(raw: dict) -> ModuleIndex:
    return ModuleIndex(
        path=raw["path"],
        module=raw["module"],
        unparsed=raw["unparsed"],
        module_refs=frozenset(raw["module_refs"]),
        symbols=tuple(
            Symbol(
                qualname=item["qualname"],
                start=item["start"],
                end=item["end"],
                refs=frozenset(item["refs"]),
                urls=tuple(item["urls"]),
                raw_urls=tuple(item["raw_urls"]),
                templates=tuple(item["templates"]),
            )
            for item in raw["symbols"]
        ),
    )


def _test_to_json(index: TestFileIndex) -> dict:
    return {
        "path": index.path,
        "file_refs": sorted(index.file_refs),
        "file_literals": sorted(index.file_literals),
        "module_marks": sorted(index.module_marks),
        "tests": {
            name: {
                "refs": sorted(test.refs),
                "literals": sorted(test.literals),
                "marks": sorted(test.marks),
            }
            for name, test in index.tests.items()
        },
    }


def _test_from_json(raw: dict) -> TestFileIndex:
    return TestFileIndex(
        path=raw["path"],
        file_refs=frozenset(raw["file_refs"]),
        file_literals=frozenset(raw["file_literals"]),
        module_marks=frozenset(raw.get("module_marks", ())),
        tests={
            name: TestRefs(
                refs=frozenset(item["refs"]),
                literals=frozenset(item["literals"]),
                marks=frozenset(item.get("marks", ())),
            )
            for name, item in raw["tests"].items()
        },
    )
