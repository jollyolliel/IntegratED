"""
Check that every shared CSS class in static/css/components/*.css carries its
own doc comment — a `/* .class-name: what it's for */` line directly above
the class's selector.

There is no markdown index to keep in sync (a table here would just be a
second copy of what the CSS already says, and it would drift the way the old
one did). To find what a class is for or where it's used: read the comment
in the CSS directly, or `grep -rhn "^/\\* \\." static/css/components/*.css`
for the whole catalogue in one shot.

WORKFLOW FOR AI AGENTS:
  Add/rename/remove a class in static/css/components/*.css -> add or update
  its `/* .class-name: what it's for */` comment on the line immediately
  above the selector (one comment line per class name when several share one
  selector — see buttons.css for the pattern), then run this script.

Usage:
  python scripts/check_css_class_docs.py    # exit 1 and list gaps if any class lacks a comment
"""

import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")
COMPONENTS_DIR = os.path.join(ROOT, "static", "css", "components")

# Load order from static/css/components.css. Also the tie-break for a class
# touched by more than one file: the earliest file that mentions it is where
# it's defined, later ones only reference it (e.g. modal.css styling a
# .btn-clay inside its actions row).
FILE_ORDER = [
    "base.css", "buttons.css", "cards.css", "badges.css", "forms.css",
    "tables.css", "worksheet.css", "misc.css", "nav.css", "toast.css",
    "modal.css", "announcement.css", "assistant.css", "journey.css",
]

CLASS_RE = re.compile(r"\.(-?[A-Za-z_][\w-]*)")
# Splits a complex selector into compounds: descendant/child/sibling combinators.
COMBINATOR_RE = re.compile(r"[\s>+~]+")
NOTE_RE = re.compile(r"^/\*\s*\.([\w-]+):\s*(.+?)\s*\*/\s*$")


def strip_comments(css: str) -> str:
    """Blank out /* */ comments but keep line count so line numbers stay true."""
    out = []
    i = 0
    while i < len(css):
        start = css.find("/*", i)
        if start == -1:
            out.append(css[i:])
            break
        out.append(css[i:start])
        end = css.find("*/", start + 2)
        if end == -1:
            out.append("\n" * css.count("\n", start))
            break
        out.append("\n" * css.count("\n", start, end))
        i = end + 2
    return "".join(out)


def subject_classes(selector_list: str):
    """Component classes named by a selector list.

    Only the FIRST class of a compound that STARTS with a class counts. That
    drops the two kinds of noise that would otherwise flood the check:
      .btn-lang.active            -> btn-lang    (.active is a state modifier)
      .clay-table thead th.text-right -> clay-table (.text-right is a utility)
    """
    for complex_sel in selector_list.split(","):
        for compound in COMBINATOR_RE.split(complex_sel.strip()):
            if not compound.startswith("."):
                continue
            match = CLASS_RE.match(compound)
            if match:
                yield match.group(1)


def scan_file(path: str) -> dict:
    """class name -> 1-indexed line of its first appearance as a subject."""
    with open(path, "r", encoding="utf-8") as f:
        css = strip_comments(f.read())

    found = {}
    start = 0  # first char after the previous brace — where this selector begins
    for match in re.finditer(r"[{}]", css):
        if match.group() == "{":
            chunk = css[start:match.start()]
            # Statement at-rules end in ';' and carry no block (@import,
            # @charset) — drop them so they don't swallow the next selector.
            rel = chunk.rfind(";") + 1
            selector = chunk[rel:]
            stripped = selector.strip()
            # Skip at-rule preludes (@media/@supports/@keyframes) — rules nested
            # inside them are picked up on later iterations.
            if stripped and not stripped.startswith("@"):
                offset = start + rel + len(selector) - len(selector.lstrip())
                line = css.count("\n", 0, offset) + 1
                for name in subject_classes(stripped):
                    if name not in found:
                        found[name] = line
        start = match.end()
    return found


def documented_classes(path: str, classes_at_line: dict) -> set:
    """Class names among `classes_at_line` that have a `/* .class: text */`
    comment on the line directly above their selector. Several such comment
    lines may stack when multiple classes share one selector — each is
    matched to its own class by name, not by position, so order doesn't
    matter. Stops walking upward at the first non-matching line."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    lines_by_target = {}
    for name, line_no in classes_at_line.items():
        lines_by_target.setdefault(line_no, set()).add(name)

    found = set()
    for line_no, names in lines_by_target.items():
        i = line_no - 2  # 0-indexed line just above the selector
        while i >= 0:
            m = NOTE_RE.match(lines[i].strip())
            if not m:
                break
            if m.group(1) in names:
                found.add(m.group(1))
            i -= 1
    return found


def collect() -> dict:
    """{css filename: {class: line}} in load order, each class listed once."""
    on_disk = {f for f in os.listdir(COMPONENTS_DIR) if f.endswith(".css")}
    unknown = on_disk - set(FILE_ORDER)
    if unknown:
        raise SystemExit(
            f"ERROR: {', '.join(sorted(unknown))} not in FILE_ORDER.\n"
            f"       Add it there and to static/css/components.css."
        )

    result = {}
    claimed = set()
    for filename in FILE_ORDER:
        path = os.path.join(COMPONENTS_DIR, filename)
        if not os.path.exists(path):
            continue
        classes = {name: line for name, line in scan_file(path).items()
                   if name not in claimed}
        claimed.update(classes)
        if classes:
            result[filename] = classes
    return result


def main() -> int:
    if not os.path.isdir(COMPONENTS_DIR):
        print(f"ERROR: no such directory: {COMPONENTS_DIR}")
        return 2

    data = collect()
    total = sum(len(c) for c in data.values())

    missing = []
    for filename, classes in data.items():
        path = os.path.join(COMPONENTS_DIR, filename)
        documented = documented_classes(path, classes)
        for name, line in sorted(classes.items(), key=lambda kv: kv[1]):
            if name not in documented:
                missing.append(f"  .{name}  ({filename}:{line})")

    if missing:
        print(f"{len(missing)} of {total} class(es) have no `/* .class: text */` "
              f"doc comment above their selector:\n")
        for line in missing:
            print(line)
        print("\nAdd the comment on the line directly above the selector, then re-run.")
        return 1

    print(f"OK: all {total} classes across {len(data)} files have a doc comment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
