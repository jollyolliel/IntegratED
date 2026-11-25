"""
List every PostHog event name already in use — `capture_event(user_id,
"event_name", ...)` calls across the codebase.

Before adding a new event, run this and check the name you're about to add
isn't already covered (or near-covered — `pair_matched` vs
`pair_manually_matched`, `worksheet_assigned` vs `worksheet_uploaded`) under
a slightly different spelling. Names only, no file/line — the point is the
vocabulary, not the location; `grep -rn "capture_event(" routes/ helpers/`
finds a specific call site once you know the name you're looking for.

Usage:
  python scripts/list_analytics_events.py
"""

import ast
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCAN_DIRS = ["routes", "helpers"]  # scanned recursively
SCAN_FILES = ["main.py", "commands.py"]
TARGET_FUNCS = {"capture_event"}


def call_target_name(node: ast.Call) -> str | None:
    """The bare function name of a Call node's target, however it's accessed
    (`capture_event(...)` or `analytics.capture_event(...)`)."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def event_name_from_call(node: ast.Call) -> str | None:
    """The event-name argument as a display string — a literal as-is, a
    computed expression (e.g. `"item_" + action`) as its source text."""
    if len(node.args) < 2:
        return None
    arg = node.args[1]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    try:
        return ast.unparse(arg) + "  [dynamic]"
    except Exception:  # noqa: BLE001 - ast.unparse's failure surface on an arbitrary expression node is unbounded; this is a best-effort dev report, must not crash the scan
        return None


def scan_file(path: str) -> set:
    with open(path, "r", encoding="utf-8") as f:
        try:
            tree = ast.parse(f.read(), filename=path)
        except SyntaxError:
            return set()

    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if call_target_name(node) in TARGET_FUNCS:
            name = event_name_from_call(node)
            if name:
                names.add(name)
        # Also catch a name threaded through as `event_name="..."` to a
        # shared helper or table (e.g. the lesson types in helpers/learning/_games.py) rather than passed
        # straight to capture_event — the literal lives at the call site,
        # not inside the helper.
        for kw in node.keywords:
            if kw.arg == "event_name" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                names.add(kw.value.value)
    return names


def main() -> int:
    all_names = set()

    for scan_dir in SCAN_DIRS:
        base = os.path.join(ROOT, scan_dir)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in
                           (".venv", "__pycache__", "node_modules", ".git")]
            for fname in filenames:
                if fname.endswith(".py"):
                    all_names.update(scan_file(os.path.join(dirpath, fname)))

    for fname in SCAN_FILES:
        path = os.path.join(ROOT, fname)
        if os.path.exists(path):
            all_names.update(scan_file(path))

    literal = sorted(n for n in all_names if "[dynamic]" not in n)
    dynamic = sorted(n for n in all_names if "[dynamic]" in n)

    print(f"{len(literal)} event name(s):\n")
    for name in literal:
        print(f"  {name}")

    if dynamic:
        print(f"\n{len(dynamic)} dynamically-built name(s) — actual value depends on runtime state:\n")
        for name in dynamic:
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
