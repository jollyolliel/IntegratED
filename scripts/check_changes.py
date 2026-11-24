"""Check everything this session changed, once, at the end of the turn.

Wired as the repo's single Stop/SubagentStop hook (see .claude/settings.json).
It asks git what differs from HEAD — staged, unstaged and untracked, the same
view `scripts/change_selection.py` gives pytest — and runs each check only on
the files, and the line ranges, that actually moved:

  *.py                        -> docstring longer than 1/3 of its function, or
                                 reading as a design justification
  .claude/rules/*.md, docs/** -> dated lines; ADRs (docs/adr/) are records
                                 and keep theirs (docs/README.md)
  static/css/components/*.css -> every shared class has its own doc comment
  templates/**, static/css/** -> ast-grep design-system lint (sgconfig.yml,
                                 lint/rules/), error-level findings only
  templates/**/*.jx           -> component-tag lint (scripts/lint_jx.py)
  templates/**, static/css/** -> *.css: unbalanced braces, unclosed comments

With parallel agents in one working tree, only files this session edited
through Edit/Write (read from the hook payload's transcript) are checked.

Exit 0 = clean. Exit 2 = the findings go to stderr as blocking feedback, so
the agent fixes them in the same turn. A second Stop in a row never blocks
(`stop_hook_active`), so an unfixable finding cannot trap the session.

Usage:
  python scripts/check_changes.py                 # hook mode (payload on stdin)
  python scripts/check_changes.py path [path...]  # check named files in full
  python scripts/check_changes.py --all           # whole repo, for CI
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.change_selection import WHOLE_FILE, changed_paths

RULES_DIR = os.path.join(".claude", "rules")
DOCS_DIR = "docs"
ADR_DIR = os.path.join("docs", "adr")
COMPONENTS_DIR = os.path.join("static", "css", "components")

# --- docstrings -----------------------------------------------------------

RATIO_NUM = 1  # flag when docstring_lines / code_lines > RATIO_NUM / RATIO_DEN
RATIO_DEN = 3
MIN_DOC_LINES = 2  # a one-line docstring is never "too detailed"

# Google-style structured sections document one line per parameter or return
# value, so they run long even for a short function. Only the summary above
# the first such header counts toward the ratio.
SECTION_HEADER_RE = re.compile(
    r"^\s*(Args|Arguments|Returns|Return|Raises|Yields|Yield|Attributes|"
    r"Note|Notes|Example|Examples)\s*:\s*$"
)

# Phrasing that signals "why we did it this way" / "options we considered" —
# architecture-decision content, which belongs in an ADR or a code comment.
DECISION_RE = re.compile(
    r"\b("
    r"instead of|rather than|as opposed to|"
    r"trade[- ]?off|workaround|"
    r"we (?:decided|chose|opted)|decided to|chosen (?:over|because)|"
    r"in order to avoid|to avoid \w+ing|"
    r"alternative(?:ly)?|"
    r"because \w+ (?:is|was|does|doesn't|can't|cannot)"
    r")\b",
    re.IGNORECASE,
)

# --- rules files ----------------------------------------------------------

BEGIN_GEN = "<!-- BEGIN GENERATED"
END_GEN = "<!-- END GENERATED"
DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def read_text(path: str) -> str | None:
    """File contents, or None when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def touched_lines(path: str, ranges) -> set:
    """Line numbers the diff reports for `path`, with WHOLE_FILE expanded."""
    if ranges != WHOLE_FILE:
        lines = set()
        for start, end in ranges:
            lines.update(range(start, end + 1))
        return lines
    text = read_text(path)
    if text is None:
        return set()
    return set(range(1, len(text.splitlines()) + 1))


def where(path: str, root: str, line: int | None = None) -> str:
    """`path:line` relative to the repo root, for a finding's location."""
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        rel = path
    rel = rel.replace(os.sep, "/")
    return f"{rel}:{line}" if line else rel


# --------------------------------------------------------------------------
# python
# --------------------------------------------------------------------------


def ratio_doc_lines(doc_text: str, total_doc_lines: int) -> int:
    """Docstring length to judge, with Args/Returns/etc. sections dropped."""
    text_lines = doc_text.splitlines()
    for index, line in enumerate(text_lines):
        if not SECTION_HEADER_RE.match(line):
            continue
        end = index
        while end > 0 and not text_lines[end - 1].strip():
            end -= 1
        return end
    return total_doc_lines


def docstring_span(node):
    """(lineno, end_lineno, text) of node's docstring, or None."""
    if not node.body:
        return None
    first = node.body[0]
    if (isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        return first.lineno, first.end_lineno, first.value.value
    return None


def check_docstrings(path: str, lines: set, source: str, root: str) -> list:
    """Flag bloated or justifying docstrings on the functions that changed."""
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError):
        return []  # mid-edit / not valid Python yet — nothing to check

    problems, seen = [], set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        assert node.end_lineno is not None  # ast.parse() always sets it
        span = (node.lineno, node.end_lineno)
        if span in seen or not any(span[0] <= n <= span[1] for n in lines):
            continue
        seen.add(span)

        doc = docstring_span(node)
        if doc is None:
            continue
        doc_start, doc_end, doc_text = doc
        raw_doc_lines = doc_end - doc_start + 1
        doc_lines = ratio_doc_lines(doc_text, raw_doc_lines)
        code_lines = (span[1] - span[0] + 1) - raw_doc_lines
        if code_lines <= 0:
            continue

        site = f"{where(path, root, node.lineno)} {node.name}()"

        if doc_lines >= MIN_DOC_LINES and doc_lines * RATIO_DEN > code_lines * RATIO_NUM:
            problems.append(
                f"{site}: docstring is {doc_lines} lines for {code_lines} lines "
                f"of code (> 1/3). Too detailed — code should be "
                f"self-explanatory, docstring just a quick overview."
            )

        hit = DECISION_RE.search(doc_text)
        if hit:
            snippet = doc_text.strip().splitlines()
            line = next(
                (l for l in snippet if hit.group(0).lower() in l.lower()), snippet[0]
            )
            problems.append(
                f"{site}: docstring reads like an architectural justification "
                f"(matched \"{hit.group(0)}\"): \"{line.strip()[:100]}\". Move the "
                f"reasoning to a code comment or an ADR; keep the docstring to "
                f"what the function does."
            )

    return problems


def check_python(path: str, lines: set, root: str = ROOT) -> list:
    """Every Python finding for the changed lines of one file."""
    source = read_text(path)
    if source is None:
        return []
    return check_docstrings(path, lines, source, root)


# --------------------------------------------------------------------------
# rules files
# --------------------------------------------------------------------------


def handwritten_lines(text: str) -> list:
    """(number, line, in_code_fence) for each line outside a GENERATED block.

    Fenced code is prose the agent must read but not prose it wrote, so a date
    in a sample payload is data, not changelog.
    """
    kept, in_generated, in_fence = [], False, False
    for number, line in enumerate(text.split("\n"), 1):
        has_begin, has_end = BEGIN_GEN in line, END_GEN in line
        # Both markers on one line = prose quoting them, not a real block;
        # treating it as one swallows the whole file.
        if has_begin and not has_end:
            in_generated = True
            continue
        if has_end and not has_begin:
            in_generated = False
            continue
        if in_generated:
            continue
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        kept.append((number, line, in_fence))
    return kept


def check_rules_file(path: str, lines: set, root: str = ROOT) -> list:
    """Flag dated lines among the changed lines of one rules file."""
    text = read_text(path)
    if text is None:
        return []

    dated = [(number, line.strip())
             for number, line, fenced in handwritten_lines(text)
             if number in lines and not fenced and DATE_RE.search(line)]
    if not dated:
        return []

    name = where(path, root)
    detail = "\n".join(f"    {name}:{n}: {l[:90]}" for n, l in dated[:5])
    more = f"\n    …and {len(dated) - 5} more" if len(dated) > 5 else ""
    return [(
        f"{name}: {len(dated)} dated line(s). Rules describe present state only "
        f"— git holds the history.\n{detail}{more}\n  Keep the lesson, drop the "
        f"incident: rewrite as a timeless rule with no date and no file name."
    )]


# --------------------------------------------------------------------------
# css
# --------------------------------------------------------------------------


def check_class_index(root: str = ROOT) -> list:
    """Run the shared-CSS-class doc check over static/css/components."""
    result = subprocess.run(
        [sys.executable, os.path.join(root, "scripts", "check_css_class_docs.py")],
        capture_output=True, text=True, cwd=root,
        check=False,  # returncode handled explicitly below
    )
    if result.returncode == 0:
        return []
    return [
        "A shared CSS class in static/css/components/*.css is missing its doc "
        "comment.\n  Run: python scripts/check_css_class_docs.py\n"
        + "\n".join(f"  {line}" for line in result.stdout.strip().split("\n"))
    ]


def css_brace_errors(text: str) -> list:
    """(line, message) for each unbalanced brace or unclosed comment."""
    # ast-grep's CSS parser recovers from these silently, and CSS itself
    # auto-closes blocks at end of file, so nothing else reports them.
    errors, open_lines = [], []
    line, i, quote = 1, 0, None
    while i < len(text):
        char = text[i]
        if char == "\n":
            line += 1
            quote = None  # a CSS string cannot span lines
        elif quote:
            if char == "\\":
                i += 1
            elif char == quote:
                quote = None
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                errors.append((line, "comment is never closed"))
                break
            line += text.count("\n", i, end)
            i = end + 1
        elif char in "\"'":
            quote = char
        elif char == "{":
            open_lines.append(line)
        elif char == "}":
            if open_lines:
                open_lines.pop()
            else:
                errors.append((line, "`}` has no matching `{`"))
        i += 1
    errors += [(opened, "`{` is never closed") for opened in open_lines]
    return sorted(errors)


def check_css(path: str, root: str = ROOT) -> list:
    """Brace and comment balance of one stylesheet, as findings."""
    text = read_text(path)
    if text is None:
        return []
    return [f"{where(path, root, line)}: {message}" for line, message in css_brace_errors(text)]


# --------------------------------------------------------------------------
# design-system lint (ast-grep)
# --------------------------------------------------------------------------

LINT_DIRS = ("templates", "static/css")


def lintable(rel_path: str) -> bool:
    """A template or stylesheet the ast-grep rules cover."""
    rel = rel_path.replace(os.sep, "/")
    return rel.endswith((".html", ".jx", ".css")) and rel.startswith(tuple(d + "/" for d in LINT_DIRS))


def ast_grep_findings(root: str, rel_paths: list) -> list:
    """`ast-grep scan` records for these files; [] when ast-grep is unavailable.

    Raises RuntimeError (with ast-grep's stderr) when the scan itself fails.
    """
    binary = shutil.which("ast-grep", path=os.path.dirname(sys.executable)) or shutil.which("ast-grep")
    if binary is None or not os.path.isfile(os.path.join(root, "sgconfig.yml")):
        return []
    result = subprocess.run(
        [binary, "scan", "--json=stream", *rel_paths],
        capture_output=True, text=True, encoding="utf-8", cwd=root,
        check=False,  # exit 1 just means "found errors"; the JSON says which
    )
    if result.returncode not in (0, 1):
        raise RuntimeError((result.stderr or "").strip() or f"exit code {result.returncode}")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def lint_problems(findings: list, touched: dict, root: str) -> list:
    """Error-level findings that overlap a changed line, one problem each."""
    problems = []
    for finding in findings:
        if finding.get("severity") != "error":
            continue
        # ast-grep on Windows reports backslash paths; os.sep won't catch them elsewhere.
        rel = where(os.path.join(root, finding["file"].replace("\\", "/")), root)
        first = finding["range"]["start"]["line"] + 1
        last = finding["range"]["end"]["line"] + 1
        if not touched.get(rel, set()) & set(range(first, last + 1)):
            continue
        note = (finding.get("note") or "").strip().replace("\n", "\n    ")
        problems.append(
            f"{rel}:{first}: [{finding['ruleId']}] {finding['message'].strip()}"
            + (f"\n    {note}" if note else "")
        )
    return problems


def check_jx(path: str, lines: set, root: str = ROOT) -> list:
    """scripts/lint_jx.py findings on the changed lines of one `.jx` file."""
    import jx

    from scripts.lint_jx import lint_jx

    source = read_text(path)
    if source is None:
        return []
    try:
        findings = lint_jx(source, where(path, root))
    except jx.JxException:
        return []  # mid-edit syntax — the catalog check in pytest reports it
    return [str(finding) for finding in findings if finding.line in lines]


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------


def in_dir(rel_path: str, directory: str) -> bool:
    """True when `rel_path` sits directly inside `directory`."""
    return os.path.dirname(os.path.normpath(rel_path)) == directory


def under(rel_path: str, directory: str) -> bool:
    """True when `rel_path` sits anywhere below `directory`."""
    return os.path.normpath(rel_path).startswith(directory + os.sep)


def is_present_tense_doc(rel_path: str) -> bool:
    """A rules file or a doc under docs/ — prose that must not carry dates."""
    if not rel_path.endswith(".md"):
        return False
    return in_dir(rel_path, RULES_DIR) or (under(rel_path, DOCS_DIR) and not under(rel_path, ADR_DIR))


def collect(root: str, changed: dict) -> list:
    """Every finding for a {relative path: changed ranges} mapping."""
    problems, css_touched, lint_lines = [], False, {}

    for rel_path in sorted(changed):
        path = os.path.join(root, rel_path)
        if not os.path.isfile(path):
            continue  # deleted, or renamed away
        lines = touched_lines(path, changed[rel_path])
        if not lines:
            continue
        if rel_path.endswith(".py"):
            problems += check_python(path, lines, root)
        elif is_present_tense_doc(rel_path):
            problems += check_rules_file(path, lines, root)
        elif rel_path.endswith(".css") and in_dir(rel_path, COMPONENTS_DIR):
            css_touched = True
        elif rel_path.endswith(".jx") and lintable(rel_path):
            problems += check_jx(path, lines, root)
        if lintable(rel_path):
            lint_lines[rel_path.replace(os.sep, "/")] = lines
            if rel_path.endswith(".css"):
                problems += check_css(path, root)

    if css_touched:
        problems += check_class_index(root)
    if lint_lines:
        try:
            findings = ast_grep_findings(root, list(lint_lines))
        except RuntimeError as crash:
            problems.append(
                "ast-grep scan failed, so no template or stylesheet was linted "
                f"(check sgconfig.yml and lint/):\n  {crash}"
            )
        else:
            problems += lint_problems(findings, lint_lines, root)
    return problems


def everything(root: str) -> dict:
    """Whole-repo selection: all rules files and docs plus the component stylesheets."""
    changed = {}
    for directory in (RULES_DIR, COMPONENTS_DIR):
        full = os.path.join(root, directory)
        if not os.path.isdir(full):
            continue
        for name in sorted(os.listdir(full)):
            if name.endswith((".md", ".css")):
                changed[f"{directory}/{name}".replace(os.sep, "/")] = WHOLE_FILE
    for path in sorted(Path(root, DOCS_DIR).rglob("*.md")):
        changed[path.relative_to(root).as_posix()] = WHOLE_FILE
    return changed


def key_for(path: str, root: str) -> str:
    """Selection key for a path named on the command line."""
    full = os.path.abspath(path)
    try:
        rel = os.path.relpath(full, root)
    except ValueError:
        return full
    return rel.replace(os.sep, "/") if not rel.startswith("..") else full


def repo_root() -> str:
    """Repo root of the working directory, falling back to this script's."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
        check=False,  # not a repo / no git -> fall back
    )
    top = result.stdout.strip()
    return os.path.abspath(top) if result.returncode == 0 and top else ROOT


def hook_payload() -> dict:
    """The Stop hook's JSON on stdin, or {} when there is none."""
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        return json.load(sys.stdin) or {}
    except (json.JSONDecodeError, ValueError, OSError):
        return {}


EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def session_files(transcript_path: str | None, root: str) -> set | None:
    """Repo-relative files this session edited through Edit/Write tools, from its transcript.

    None when the transcript can't be read, so the caller checks everything git reports.
    Edits made through a shell command are not visible here.
    """
    if not transcript_path:
        return None
    text = read_text(transcript_path)
    if text is None:
        return None
    files = set()
    for line in text.splitlines():
        try:
            content = json.loads(line)["message"]["content"]
        except (ValueError, KeyError, TypeError):
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not (isinstance(block, dict) and block.get("name") in EDIT_TOOLS):
                continue
            path = (block.get("input") or {}).get("file_path") or (block.get("input") or {}).get("notebook_path")
            if path:
                files.add(key_for(os.path.join(root, path), root))
    return files


def scope_to_session(changed: dict, mine: set | None) -> dict:
    """`changed` narrowed to the files this session edited; unchanged when `mine` is None."""
    if mine is None:
        return changed
    return {path: ranges for path, ranges in changed.items() if path.replace(os.sep, "/") in mine}


def main(argv: list, payload: dict | None = None) -> int:
    root = repo_root()  # the worktree that is actually being edited
    paths = [arg for arg in argv if not arg.startswith("-")]

    if paths:
        changed = {key_for(path, root): WHOLE_FILE for path in paths}
    elif "--all" in argv:
        changed = everything(root)
    else:
        if payload is None:
            payload = hook_payload()
        if payload.get("stop_hook_active"):
            return 0  # already reported last turn — never loop the agent
        changed = changed_paths(Path(root))
        if changed is None:
            return 0  # no git, no repo, no answer — not a failure
        # Parallel agents share one working tree; check only what this session edited.
        changed = scope_to_session(changed, session_files(payload.get("transcript_path"), root))

    problems = collect(root, changed)

    if problems:
        print("End-of-turn checks failed on the files you changed:\n", file=sys.stderr)
        for problem in problems:
            print("- " + problem + "\n", file=sys.stderr)
        return 2

    if "--all" in argv:
        print("OK: no dated lines in rules files or docs, every CSS class documented.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
