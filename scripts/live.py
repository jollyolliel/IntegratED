"""
Open, refine, accept and discard live variant sessions in templates/**/*.jx.

Claude writes only the variants, to .live/<id>.jx; this script does every edit
to the template itself, each as one validated, atomic write. The formats are
in .claude/skills/live/format.md.

Usage:
  uv run scripts/live.py new-id
  uv run scripts/live.py wrap --id ID --action ACTION --file PATH --lines A-B
  uv run scripts/live.py wrap --id ID --action ACTION --file PATH --insert-after N   # or --insert-before N
  uv run scripts/live.py refine ID --keep N
  uv run scripts/live.py accept ID N [--knobs '{"scale": 1.15, "gap": "airy"}']
  uv run scripts/live.py accept ID --variants .live/ID.jx   # close with an element finished by hand
  uv run scripts/live.py discard ID
  uv run scripts/live.py show ID [--variant N [--knobs '{"gap": "airy"}']]
  uv run scripts/live.py status

--variants PATH overrides the default .live/<id>.jx for wrap and refine.
`show` tells a chat that didn't open a session where it is and what it holds;
with --variant it prints that variant's markup and CSS, knobs baked.
Success prints one JSON line; an error prints "live: <message>" to stderr,
exits 1 and changes nothing.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import secrets
import sys
import tempfile
import textwrap
import time
from collections.abc import Callable
from dataclasses import dataclass, field

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.file_lock import LockTimeout, locked
from scripts.live_variants import (
    KNOB_VAR_RE,
    MAX_VARIANTS,
    LiveError,
    Variant,
    bake_knobs,
    knob_literals,
    parse_variants,
    scope_css,
    variant_prefix,
)

TEMPLATES_DIR = os.path.join(ROOT, "templates")
SCRATCH_DIR = os.path.join(ROOT, ".live")
# Held from reading a template to writing it back, so chats working at once
# (even on different pages that share a component) never undo each other.
LOCK_PATH = os.path.join(SCRATCH_DIR, "edit.lock")
LOCK_TIMEOUT = 30

ACTIONS = (
    "impeccable",
    "bolder",
    "quieter",
    "distill",
    "polish",
    "typeset",
    "colorize",
    "layout",
    "adapt",
    "animate",
    "delight",
    "overdrive",
)
BASE_STYLE = "<style data-live-base>[data-live-session],[data-live-variant]:not([hidden]){display:contents}</style>"

_ID_RE = re.compile(r"[0-9a-f]{8}")
_MARKER_RE = re.compile(r"^\s*\{# live:([0-9a-f]{8}) (start|end|v(\d+)) #\}\s*$")


@dataclass
class Span:
    """Where one session's markers sit in a template, as 0-based line indexes."""

    id: str
    start: int
    end: int | None = None
    variants: dict[int, int] = field(default_factory=dict)


# --- reading sessions out of a template -------------------------------------


def scan_sessions(lines: list[str]) -> list[Span]:
    """Every session's markers in a template; a span with end None is broken."""
    spans: list[Span] = []
    current: Span | None = None
    for index, line in enumerate(lines):
        marker = _MARKER_RE.match(line)
        if not marker:
            continue
        sid, kind = marker.group(1), marker.group(2)
        if kind == "start":
            if current:
                spans.append(current)
            current = Span(sid, index)
        elif current is None or current.id != sid:
            spans.append(Span(sid, index))
        elif kind == "end":
            current.end = index
            spans.append(current)
            current = None
        else:
            current.variants[int(marker.group(3))] = index
    if current:
        spans.append(current)
    return spans


def _span_last(span: Span, total: int) -> int:
    return span.end if span.end is not None else total - 1


# --- rendering a session block ----------------------------------------------


def _eol_of(line: str) -> str:
    return line[len(line.rstrip("\r\n")) :]


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _indented(lines: list[str], indent: str, eol: str) -> list[str]:
    return [(indent + line if line.strip() else "") + eol for line in lines]


def _render_variant(
    sid: str, n: int, variant: Variant, indent: str, eol: str, frames: set[str]
) -> list[str]:
    attrs = f'data-live-variant="{n}" data-live-name="{html.escape(variant.name)}"'
    if variant.knobs:
        attrs += f" data-live-knobs='{json.dumps(variant.knobs, ensure_ascii=False, separators=(',', ':'))}'"
    if n != 1:
        attrs += " hidden"
    out = [f"{indent}{{# live:{sid} v{n} #}}{eol}", f"{indent}<div {attrs}>{eol}"]
    if variant.css:
        scoped, own_frames = scope_css(variant.css, n)
        clash = frames & own_frames
        if clash:
            raise LiveError(
                f"@keyframes {', '.join(sorted(clash))} is defined by more than one variant"
            )
        frames |= own_frames
        css_lines = scoped.strip().split("\n")
        if len(css_lines) == 1:
            out.append(f"{indent}<style data-live-css>{css_lines[0]}</style>{eol}")
        else:
            out.append(f"{indent}<style data-live-css>{eol}")
            out += _indented(css_lines, indent, eol)
            out.append(f"{indent}</style>{eol}")
    out += _indented(variant.markup, indent, eol)
    out.append(f"{indent}</div>{eol}")
    return out


def _render_variants(
    sid: str, variants: list[Variant], indent: str, eol: str
) -> list[str]:
    frames: set[str] = set()
    out: list[str] = []
    for n, variant in enumerate(variants, start=1):
        out += _render_variant(sid, n, variant, indent, eol, frames)
    return out


def _session_head(
    sid: str, action: str, mode: str, label: str, indent: str, eol: str
) -> list[str]:
    # The label names the session in the extension when a page holds several.
    named = f' data-live-label="{html.escape(label)}"' if label else ""
    return [
        f"{indent}{{# live:{sid} start #}}{eol}",
        f'{indent}<div data-live-session="{sid}" data-live-action="{action}" data-live-mode="{mode}" data-live-round="1"{named}>{eol}',
        f"{indent}{BASE_STYLE}{eol}",
    ]


# --- commands ---------------------------------------------------------------


def _check_id(sid: str) -> None:
    if not _ID_RE.fullmatch(sid):
        raise LiveError(f"session id {sid!r} must be 8 lowercase hex characters")


def wrap_text(
    source: str,
    variants_text: str,
    *,
    session_id: str,
    action: str,
    label: str = "",
    lines: tuple[int, int] | None = None,
    insert_after: int | None = None,
    insert_before: int | None = None,
    open_ids: set[str] | frozenset[str] = frozenset(),
) -> str:
    """Open a session: wrap lines A-B (or insert at an anchor) with the variants."""
    _check_id(session_id)
    if action not in ACTIONS:
        raise LiveError(f"unknown action {action!r}; one of: {', '.join(ACTIONS)}")
    if sum(x is not None for x in (lines, insert_after, insert_before)) != 1:
        raise LiveError("give exactly one of --lines, --insert-after, --insert-before")

    src = source.splitlines(keepends=True)
    total = len(src)
    eol = "\r\n" if "\r\n" in source else "\n"
    spans = scan_sessions(src)
    if session_id in open_ids or any(span.id == session_id for span in spans):
        raise LiveError(f"session {session_id} is already open")
    variants = parse_variants(variants_text)

    def in_range(n: int) -> int:
        if not 1 <= n <= total:
            raise LiveError(f"line {n} is outside the file (1-{total})")
        return n - 1

    if lines is not None:
        first, last = in_range(lines[0]), in_range(lines[1])
        if first > last:
            raise LiveError(f"line range {lines[0]}-{lines[1]} is backwards")
        for span in spans:
            if first <= _span_last(span, total) and last >= span.start:
                raise LiveError(
                    f"lines {lines[0]}-{lines[1]} overlap live session {span.id}"
                )
        head, original, tail = src[:first], src[first : last + 1], src[last + 1 :]
        mode, v0_name, indent = "replace", "Current", _indent_of(original[0])
        end_eol = _eol_of(original[-1])
        if not end_eol:
            original = [*original[:-1], original[-1] + eol]
    else:
        if insert_after is not None:
            anchor = in_range(insert_after)
            cut = anchor + 1
        else:
            assert insert_before is not None
            anchor = cut = in_range(insert_before)
        for span in spans:
            if span.start < cut <= _span_last(span, total):
                raise LiveError(f"line {anchor + 1} is inside live session {span.id}")
        if cut and not _eol_of(src[cut - 1]):
            raise LiveError("the file's last line has no newline; add one first")
        head, original, tail = src[:cut], [], src[cut:]
        mode, v0_name, indent, end_eol = (
            "insert",
            "Without",
            _indent_of(src[anchor]),
            eol,
        )

    block = _session_head(session_id, action, mode, label, indent, eol)
    block += [
        f"{indent}{{# live:{session_id} v0 #}}{eol}",
        f'{indent}<div data-live-variant="0" data-live-name="{v0_name}" hidden>{eol}',
        *original,
        f"{indent}</div>{eol}",
    ]
    block += _render_variants(session_id, variants, indent, eol)
    block += [f"{indent}</div>{eol}", f"{indent}{{# live:{session_id} end #}}{end_eol}"]
    return "".join(head + block + tail)


def _find_open(src: list[str], sid: str) -> Span:
    _check_id(sid)
    for span in scan_sessions(src):
        if span.id == sid:
            if span.end is None or 0 not in span.variants:
                raise LiveError(
                    f"live session {sid} is broken (a marker is missing); fix it by hand"
                )
            return span
    raise LiveError(f"no live session {sid} in this file")


def _section(src: list[str], span: Span, n: int) -> list[str]:
    """The lines of variant n, from its <div> to its </div>, endings kept."""
    if n not in span.variants:
        raise LiveError(f"variant {n} is not in live session {span.id}")
    assert span.end is not None
    later = [index for index in span.variants.values() if index > span.variants[n]]
    stop = min(later) if later else span.end - 1
    return src[span.variants[n] + 1 : stop]


def _split_section(section: list[str]) -> tuple[str, list[str], list[str]]:
    """A variant's lines -> (its <div> line, its <style data-live-css> lines, its markup lines)."""
    body = section[1:-1]
    css: list[str] = []
    if body and body[0].strip().startswith("<style data-live-css>"):
        close = next(
            (k for k, line in enumerate(body) if line.rstrip().endswith("</style>")),
            None,
        )
        if close is None:
            raise LiveError("a variant's <style data-live-css> has no </style>")
        css, body = body[: close + 1], body[close + 1 :]
    return section[0], css, body


def _attr(line: str, name: str) -> str | None:
    match = re.search(rf'{name}="([^"]*)"', line)
    return html.unescape(match.group(1)) if match else None


def _knobs_attr(line: str) -> list[dict]:
    match = re.search(r"data-live-knobs='([^']*)'", line)
    return json.loads(match.group(1)) if match else []


def _plain(lines: list[str]) -> str:
    return "".join(line.rstrip("\r\n") + "\n" for line in lines)


def _css_text(css_lines: list[str], n: int) -> str:
    text = _plain(css_lines).replace("<style data-live-css>", "", 1)
    text = text[: text.rfind("</style>")]
    return textwrap.dedent(text.strip("\n")).strip().replace(variant_prefix(n), "")


def _with_last_eol(lines: list[str], eol: str) -> list[str]:
    if not lines:
        return lines
    return [*lines[:-1], lines[-1].rstrip("\r\n") + eol]


def refine_text(source: str, session_id: str, keep: int, variants_text: str) -> str:
    """Start the next round: variant `keep` becomes variant 1, the new ones follow."""
    src = source.splitlines(keepends=True)
    span = _find_open(src, session_id)
    assert span.end is not None
    if keep < 1 or keep not in span.variants:
        raise LiveError(
            f"variant {keep} can't be kept; choose one of the session's variants from 1"
        )
    new = parse_variants(variants_text)
    if len(new) + 1 > MAX_VARIANTS:
        raise LiveError(
            f"{len(new)} new variants plus the kept one; at most {MAX_VARIANTS} per round"
        )

    open_line, css_lines, markup = _split_section(_section(src, span, keep))
    name = _attr(open_line, "data-live-name") or f"Variant {keep}"
    kept = Variant(
        name=name if name.endswith(" (kept)") else f"{name} (kept)",
        markup=textwrap.dedent(_plain(markup)).rstrip("\n").split("\n"),
        css=_css_text(css_lines, keep),
        knobs=_knobs_attr(open_line) or None,
    )
    eol = _eol_of(src[span.start]) or "\n"
    head = src[span.start : span.variants[1]]
    head[1] = re.sub(
        r'data-live-round="(\d+)"',
        lambda m: f'data-live-round="{int(m.group(1)) + 1}"',
        head[1],
    )
    body = _render_variants(session_id, [kept, *new], _indent_of(src[span.start]), eol)
    return "".join(src[: span.start] + head + body + src[span.end - 1 :])


def discard_text(source: str, session_id: str) -> str:
    """Close a session, restoring variant 0's lines byte for byte."""
    src = source.splitlines(keepends=True)
    span = _find_open(src, session_id)
    assert span.end is not None
    original = _section(src, span, 0)[1:-1]
    restored = _with_last_eol(original, _eol_of(src[span.end]))
    return "".join(src[: span.start] + restored + src[span.end + 1 :])


def accept_text(
    source: str, session_id: str, n: int, knobs: dict | None = None
) -> tuple[str, str]:
    """Close a session keeping variant n with its knobs baked; return the source and its CSS."""
    if n == 0:
        return discard_text(source, session_id), ""
    src = source.splitlines(keepends=True)
    span = _find_open(src, session_id)
    assert span.end is not None
    open_line, css_lines, markup = _split_section(_section(src, span, n))
    literals = knob_literals(_knobs_attr(open_line), knobs or {})
    element = bake_knobs("".join(markup), literals).splitlines(keepends=True)
    css = bake_knobs(_css_text(css_lines, n), literals)
    accepted = _with_last_eol(element, _eol_of(src[span.end]))
    return "".join(src[: span.start] + accepted + src[span.end + 1 :]), css


def finish_text(source: str, session_id: str, variants_text: str) -> str:
    """Close a session with the one element Claude finished by hand.

    The element is final: knob values are written in and its CSS already sits in
    its own home, so the page shows the end result the moment the session goes.
    """
    src = source.splitlines(keepends=True)
    span = _find_open(src, session_id)
    assert span.end is not None
    variants = parse_variants(variants_text)
    if len(variants) != 1:
        raise LiveError(
            f"a finished element file holds exactly one variant, found {len(variants)}"
        )
    final = variants[0]
    if final.knobs:
        raise LiveError(
            "a finished element has no knobs: write their chosen values in (live.py show ID --variant N --knobs …)"
        )
    if final.css:
        raise LiveError(
            "a finished element carries no CSS: put it in its own home first (styling-system.md), then close"
        )
    leftover = KNOB_VAR_RE.search("\n".join(final.markup))
    if leftover:
        raise LiveError(
            f"var(--p-{leftover.group(1)}) is still in the element: write the knob's chosen value in"
        )
    eol = _eol_of(src[span.start]) or "\n"
    element = _indented(final.markup, _indent_of(src[span.start]), eol)
    finished = _with_last_eol(element, _eol_of(src[span.end]))
    return "".join(src[: span.start] + finished + src[span.end + 1 :])


def closed_lines(before: str, after: str, session_id: str) -> tuple[int, int]:
    """The 1-based lines the kept element fills once the session is closed."""
    src = before.splitlines(keepends=True)
    span = _find_open(src, session_id)
    assert span.end is not None
    outside = len(src) - (span.end - span.start + 1)
    kept = len(after.splitlines(keepends=True)) - outside
    return span.start + 1, span.start + kept


def show_session(
    source: str, session_id: str, variant: int | None = None, knobs: dict | None = None
) -> dict:
    """One session as a chat that didn't open it needs it; with `variant`, its markup and CSS."""
    src = source.splitlines(keepends=True)
    span = _find_open(src, session_id)
    assert span.end is not None
    head = src[span.start + 1]
    rows = []
    for n in sorted(span.variants):
        open_line, css_lines, _ = _split_section(_section(src, span, n))
        rows.append(
            {
                "n": n,
                "name": _attr(open_line, "data-live-name") or "",
                "knobs": [knob["id"] for knob in _knobs_attr(open_line)],
                "css": bool(css_lines),
            }
        )
    round_ = _attr(head, "data-live-round") or ""
    shown: dict = {
        "id": session_id,
        "line": span.start + 1,
        "end": span.end + 1,
        "label": _attr(head, "data-live-label") or "",
        "action": _attr(head, "data-live-action"),
        "mode": _attr(head, "data-live-mode"),
        "round": int(round_) if round_.isdigit() else None,
        "variants": rows,
    }
    if variant is not None:
        open_line, css_lines, markup = _split_section(_section(src, span, variant))
        text = textwrap.dedent(_plain(markup))
        if variant == 0:
            shown["markup"], shown["css"] = text, ""
        else:
            literals = knob_literals(_knobs_attr(open_line), knobs or {})
            shown["markup"] = bake_knobs(text, literals)
            shown["css"] = bake_knobs(_css_text(css_lines, variant), literals)
    return shown


def find_sessions(source: str) -> list[dict]:
    """Every session in one template, as status rows without the file."""
    src = source.splitlines(keepends=True)
    rows = []
    for span in scan_sessions(src):
        head = src[span.start + 1] if span.start + 1 < len(src) else ""
        round_ = _attr(head, "data-live-round")
        rows.append(
            {
                "line": span.start + 1,
                "id": span.id,
                "action": _attr(head, "data-live-action"),
                "mode": _attr(head, "data-live-mode"),
                "round": int(round_) if round_ and round_.isdigit() else None,
                "label": _attr(head, "data-live-label") or "",
                "variants": len([n for n in span.variants if n]),
                "broken": span.end is None or 0 not in span.variants,
            }
        )
    return rows


def _read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def status(templates_dir: str = TEMPLATES_DIR, root: str = ROOT) -> list[dict]:
    """Open sessions across every template, in file order."""
    paths = sorted(
        os.path.join(folder, name)
        for folder, _, files in os.walk(templates_dir)
        for name in files
        if name.endswith(".jx")
    )
    rows = []
    for path in paths:
        text = _read(path)
        if "{# live:" in text:
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            rows += [{"file": rel, **row} for row in find_sessions(text)]
    return rows


def new_id(
    open_ids: set[str], token: Callable[[], str] = lambda: secrets.token_hex(4)
) -> str:
    """A fresh session id that no template is using."""
    while (sid := token()) in open_ids:
        pass
    return sid


# --- file I/O ---------------------------------------------------------------


def _write_atomic(path: str, text: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=os.path.dirname(path),
        delete=False,
        suffix=".tmp",
    ) as tmp:
        tmp.write(text)
    # On Windows, OneDrive and the dev server's reloader hold a just-changed file
    # open for a moment, and os.replace fails with "Access is denied" meanwhile.
    for delay in (0.05, 0.1, 0.2, 0.4, 0.8, 1.6, None):
        try:
            os.replace(tmp.name, path)
            return
        except PermissionError:
            if delay is None:
                os.unlink(tmp.name)
                raise LiveError(f"{_rel(path)} stayed locked by another program; try again") from None
            time.sleep(delay)


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def _template_path(given: str) -> str:
    path = os.path.abspath(os.path.join(ROOT, given))
    if not path.startswith(TEMPLATES_DIR + os.sep) or not path.endswith(".jx"):
        raise LiveError(f"{given} is not a .jx file under templates/")
    if not os.path.isfile(path):
        raise LiveError(f"{given} does not exist")
    return path


def _session_file(sid: str) -> str:
    files = {row["file"] for row in status() if row["id"] == sid}
    if not files:
        raise LiveError(
            f"no live session {sid} in templates/ (uv run scripts/live.py status)"
        )
    if len(files) > 1:
        raise LiveError(
            f"session {sid} is open in more than one file: {', '.join(sorted(files))}"
        )
    return os.path.join(ROOT, files.pop())


def _variants_text(sid: str, given: str | None) -> str:
    path = (
        os.path.join(ROOT, given) if given else os.path.join(SCRATCH_DIR, f"{sid}.jx")
    )
    if not os.path.isfile(path):
        raise LiveError(f"variants file {_rel(path)} not found")
    return _read(path)


def _drop_scratch(sid: str) -> None:
    path = os.path.join(SCRATCH_DIR, f"{sid}.jx")
    if os.path.exists(path):
        os.remove(path)


def _parse_lines(raw: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", raw.strip())
    if not match:
        raise LiveError(f"--lines {raw!r} must look like 120-148")
    first = int(match.group(1))
    return first, int(match.group(2) or first)


def _wrap(args: argparse.Namespace) -> dict:
    path = _template_path(args.file)
    lines = _parse_lines(args.lines) if args.lines else None
    updated = wrap_text(
        _read(path),
        _variants_text(args.id, args.variants),
        session_id=args.id,
        action=args.action,
        label=args.label or "",
        lines=lines,
        insert_after=args.insert_after,
        insert_before=args.insert_before,
        open_ids={row["id"] for row in status()},
    )
    _write_atomic(path, updated)
    line = next(row["line"] for row in find_sessions(updated) if row["id"] == args.id)
    return {"file": _rel(path), "line": line, "id": args.id}


def _knobs_arg(raw: str | None) -> dict:
    try:
        knobs = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise LiveError(f"--knobs is not valid JSON ({exc.msg})") from None
    if not isinstance(knobs, dict):
        raise LiveError('--knobs must be a JSON object like {"scale": 1.1}')
    return knobs


def _show(args: argparse.Namespace) -> dict:
    path = _session_file(args.id)
    shown = show_session(_read(path), args.id, args.variant, _knobs_arg(args.knobs))
    return {"file": _rel(path), **shown}


def _close(args: argparse.Namespace) -> dict:
    """refine, accept or discard the session named on the command line."""
    path = _session_file(args.id)
    source = _read(path)
    line = next(row["line"] for row in find_sessions(source) if row["id"] == args.id)
    result: dict = {"file": _rel(path), "line": line}
    if args.command == "refine":
        _write_atomic(
            path,
            refine_text(
                source, args.id, args.keep, _variants_text(args.id, args.variants)
            ),
        )
        return result
    if args.command == "discard":
        _write_atomic(path, discard_text(source, args.id))
        _drop_scratch(args.id)
        return result
    if args.variants:
        updated = finish_text(source, args.id, _variants_text(args.id, args.variants))
    else:
        knobs = _knobs_arg(args.knobs)
        updated, result["css"] = accept_text(source, args.id, args.variant, knobs)
    if args.variant != 0:
        first, last = closed_lines(source, updated, args.id)
        result["lines"] = f"{first}-{last}"
    _write_atomic(path, updated)
    _drop_scratch(args.id)
    return result


def run(args: argparse.Namespace) -> dict:
    """Carry out one parsed command and return its JSON result."""
    if args.command == "accept" and (args.variant is None) == (args.variants is None):
        raise LiveError(
            "accept takes a variant number or --variants PATH (a finished element), not both or neither"
        )
    if args.command == "status":
        return {"sessions": status()}
    if args.command == "show":
        return _show(args)
    try:
        with locked(LOCK_PATH, timeout=LOCK_TIMEOUT):
            if args.command == "new-id":
                return {"id": new_id({row["id"] for row in status()})}
            if args.command == "wrap":
                return _wrap(args)
            return _close(args)
    except LockTimeout:
        raise LiveError(
            "busy: another chat is editing templates through live.py; try again"
        ) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Live variant sessions in templates/**/*.jx."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("new-id", help="print a fresh session id")
    sub.add_parser("status", help="list open sessions")
    wrap = sub.add_parser("wrap", help="open a session around lines of a template")
    wrap.add_argument("--id", required=True)
    wrap.add_argument("--action", required=True, choices=ACTIONS)
    wrap.add_argument(
        "--file", required=True, help="template path, e.g. templates/pages/index.jx"
    )
    where = wrap.add_mutually_exclusive_group(required=True)
    where.add_argument("--lines", help="A-B, the 1-based inclusive range to replace")
    where.add_argument("--insert-after", type=int, metavar="N")
    where.add_argument("--insert-before", type=int, metavar="N")
    wrap.add_argument("--variants", help="variants file (default .live/<id>.jx)")
    wrap.add_argument(
        "--label", help="short name the extension shows, e.g. 'Games background'"
    )
    refine = sub.add_parser("refine", help="start the next round from one variant")
    refine.add_argument("id")
    refine.add_argument("--keep", type=int, required=True)
    refine.add_argument("--variants", help="variants file (default .live/<id>.jx)")
    accept = sub.add_parser("accept", help="keep one variant and close the session")
    accept.add_argument("id")
    accept.add_argument("variant", type=int, nargs="?")
    accept.add_argument(
        "--knobs", help='JSON object of knob values, e.g. {"scale": 1.15}'
    )
    accept.add_argument(
        "--variants",
        help="close with the one finished element in this file instead of variant N",
    )
    show = sub.add_parser(
        "show", help="describe a session; --variant prints its markup"
    )
    show.add_argument("id")
    show.add_argument("--variant", type=int)
    show.add_argument(
        "--knobs", help="knob values to bake into the shown variant, as for accept"
    )
    discard = sub.add_parser(
        "discard", help="restore the original and close the session"
    )
    discard.add_argument("id")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(build_parser().parse_args(argv))
    except LiveError as exc:
        print(f"live: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
