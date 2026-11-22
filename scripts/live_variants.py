"""The variants file `/live` sessions are built from: parsing it, checking its knobs, counting a
variant's top-level elements, scoping its CSS to its own wrapper, and baking chosen knob values in.

Pure text in, text out; `scripts/live.py` does every edit to a template. The formats are in
.claude/skills/live/format.md.
"""

from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass

MAX_VARIANTS = 8
MAX_KNOBS = 4

_VARIANT_HEAD_RE = re.compile(
    r'^[ \t]*\{#\s*variant\s+name="([^"]*)"\s*#\}[ \t]*$', re.MULTILINE
)
_KNOB_ID_RE = re.compile(r"[a-z][a-z0-9-]*")
_STYLE_OPEN_RE = re.compile(r"<style\b[^>]*>", re.IGNORECASE)
_JINJA_OR_COMMENT_RE = re.compile(
    r"\{#.*?#\}|\{\{.*?\}\}|\{%.*?%\}|<!--.*?-->", re.DOTALL
)
_TAG_START_RE = re.compile(r"<(/?)([A-Za-z][\w.:-]*)")
_LEADING_BLANK_LINES_RE = re.compile(r"\A(?:[ \t]*\n)+")
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


class LiveError(ValueError):
    """A request the script refuses; nothing has been written."""


@dataclass
class Variant:
    """One variant as Claude wrote it in the variants file, before scoping."""

    name: str
    markup: list[str]
    css: str = ""
    knobs: list[dict] | None = None


# --- the variants file ------------------------------------------------------


def parse_variants(text: str) -> list[Variant]:
    """Split a variants file into validated variants."""
    pieces = _VARIANT_HEAD_RE.split(text.replace("\r\n", "\n"))
    if pieces[0].strip():
        raise LiveError('text before the first {# variant name="…" #} line')
    pairs = list(zip(pieces[1::2], pieces[2::2], strict=True))
    if not pairs:
        raise LiveError("no variants in the variants file")
    if len(pairs) > MAX_VARIANTS:
        raise LiveError(f"{len(pairs)} variants; at most {MAX_VARIANTS} per round")
    return [_parse_variant(name.strip(), body) for name, body in pairs]


def _parse_variant(name: str, body: str) -> Variant:
    if not name:
        raise LiveError("a variant has an empty name")
    rest = body
    knobs = None
    if rest.lstrip().startswith("{# knobs"):
        rest = rest.lstrip()
        close = rest.find("#}")
        if close == -1:
            raise LiveError(f"variant {name!r}: knobs line has no closing #}}")
        knobs = validate_knobs(rest[len("{# knobs") : close].strip(), name)
        rest = rest[close + 2 :]
    css = ""
    style = _STYLE_OPEN_RE.match(rest.lstrip())
    if style:
        rest = rest.lstrip()
        close = rest.find("</style>", style.end())
        if close == -1:
            raise LiveError(f"variant {name!r}: <style> has no </style>")
        css = textwrap.dedent(rest[style.end() : close].strip("\n")).strip()
        rest = rest[close + len("</style>") :]
    markup = textwrap.dedent(_LEADING_BLANK_LINES_RE.sub("", rest).rstrip()).split("\n")
    count = count_top_level_elements("\n".join(markup))
    if count != 1:
        raise LiveError(
            f"variant {name!r} needs exactly one top-level element, found {count}"
        )
    return Variant(name=name, markup=markup, css=css, knobs=knobs)


def validate_knobs(raw: str, variant_name: str = "?") -> list[dict]:
    """Parse and check a knobs JSON list against the knob contract."""
    where = f"variant {variant_name!r}"
    if "'" in raw:
        raise LiveError(
            f"{where}: knob JSON can't contain ' (it is written in a single-quoted attribute)"
        )
    try:
        knobs = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LiveError(f"{where}: knobs are not valid JSON ({exc.msg})") from None
    if not isinstance(knobs, list):
        raise LiveError(f"{where}: knobs must be a JSON list")
    if len(knobs) > MAX_KNOBS:
        raise LiveError(f"{where}: {len(knobs)} knobs; at most {MAX_KNOBS}")
    seen: set[str] = set()
    for knob in knobs:
        _check_knob(knob, where)
        if knob["id"] in seen:
            raise LiveError(f"{where}: knob id {knob['id']!r} is used twice")
        seen.add(knob["id"])
    return knobs


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_knob(knob: object, where: str) -> None:
    if not isinstance(knob, dict):
        raise LiveError(f"{where}: each knob must be a JSON object")
    kid = knob.get("id")
    if not isinstance(kid, str) or not _KNOB_ID_RE.fullmatch(kid):
        raise LiveError(f"{where}: knob id {kid!r} must match [a-z][a-z0-9-]*")
    if not isinstance(knob.get("label"), str) or not knob["label"]:
        raise LiveError(f"{where}: knob {kid!r} needs a label")
    kind = knob.get("kind")
    if kind == "range":
        for key in ("min", "max", "step", "default"):
            if not _is_number(knob.get(key)):
                raise LiveError(f"{where}: range knob {kid!r} needs a numeric {key}")
        if not knob["min"] <= knob["default"] <= knob["max"]:
            raise LiveError(f"{where}: range knob {kid!r} default is outside min–max")
        if "unit" in knob and not isinstance(knob["unit"], str):
            raise LiveError(f"{where}: range knob {kid!r} unit must be a string")
    elif kind == "steps":
        options = knob.get("options")
        if not isinstance(options, list) or not options:
            raise LiveError(
                f"{where}: steps knob {kid!r} needs a non-empty options list"
            )
        for option in options:
            if not (
                isinstance(option, dict)
                and all(
                    isinstance(option.get(k), str) for k in ("key", "label", "value")
                )
            ):
                raise LiveError(
                    f"{where}: steps knob {kid!r} options need string key, label and value"
                )
        if knob.get("default") not in [option["key"] for option in options]:
            raise LiveError(
                f"{where}: steps knob {kid!r} default must be one of its option keys"
            )
    elif kind == "toggle":
        for key in ("on", "off"):
            if not isinstance(knob.get(key), str):
                raise LiveError(f"{where}: toggle knob {kid!r} needs a string {key!r}")
        if not isinstance(knob.get("default"), bool):
            raise LiveError(
                f"{where}: toggle knob {kid!r} default must be true or false"
            )
    else:
        raise LiveError(
            f"{where}: knob {kid!r} has unknown kind {kind!r} (range, steps or toggle)"
        )


def count_top_level_elements(markup: str) -> int:
    """Count elements at depth 0, ignoring Jinja spans, comments and raw text."""
    text = _JINJA_OR_COMMENT_RE.sub(" ", markup)
    depth = count = i = 0
    while (lt := text.find("<", i)) != -1:
        tag = _TAG_START_RE.match(text, lt)
        if not tag:
            i = lt + 1
            continue
        j, quote = tag.end(), ""
        while j < len(text) and (quote or text[j] != ">"):
            if quote and text[j] == quote:
                quote = ""
            elif not quote and text[j] in "\"'":
                quote = text[j]
            j += 1
        if j == len(text):
            raise LiveError(f"unclosed <{tag.group(2)} tag")
        name, i = tag.group(2), j + 1
        if tag.group(1):
            depth -= 1
            if depth < 0:
                raise LiveError(f"stray </{name}>")
            continue
        if depth == 0:
            count += 1
        if text[j - 1] == "/" or name.lower() in _VOID_TAGS:
            continue
        if name.lower() in ("script", "style"):
            close = text.lower().find(f"</{name.lower()}", i)
            if close == -1:
                raise LiveError(f"<{name}> has no closing tag")
            i = close
        depth += 1
    if depth:
        raise LiveError("markup has an unclosed element")
    return count


# --- CSS scoping ------------------------------------------------------------


def variant_prefix(n: int) -> str:
    return f'[data-live-variant="{n}"] '


def scope_css(css: str, n: int) -> tuple[str, set[str]]:
    """Prefix every rule with the variant selector; return it and the @keyframes names."""
    frames: set[str] = set()
    return _scope_block(_CSS_COMMENT_RE.sub("", css), variant_prefix(n), frames), frames


def _next_css_stop(css: str, i: int) -> int:
    quote = ""
    while i < len(css):
        ch = css[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "{};":
            return i
        i += 1
    return -1


def _matching_brace(css: str, open_at: int) -> int:
    depth, i = 0, open_at
    while (i := _next_css_stop(css, i)) != -1:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise LiveError("CSS has an unclosed {")


def _scope_block(css: str, prefix: str, frames: set[str]) -> str:
    out, i = [], 0
    while i < len(css):
        stop = _next_css_stop(css, i)
        if stop == -1:
            if css[i:].strip():
                raise LiveError(f"CSS outside a rule: {css[i:].strip()!r}")
            out.append(css[i:])
            break
        prelude = css[i:stop]
        if css[stop] == "}":
            raise LiveError("CSS has an unmatched }")
        if css[stop] == ";":
            if not prelude.strip().startswith("@"):
                raise LiveError(f"CSS outside a rule: {prelude.strip()!r}")
            out.append(css[i : stop + 1])
            i = stop + 1
            continue
        close = _matching_brace(css, stop)
        inner = css[stop + 1 : close]
        head = prelude.strip()
        if head.startswith("@"):
            at_name = re.match(r"@([\w-]*)", head)
            name = at_name.group(1).lower() if at_name else ""
            if name in ("media", "supports", "container", "layer"):
                inner = _scope_block(inner, prefix, frames)
            elif name.endswith("keyframes"):
                frames.add(head.split(None, 1)[-1].strip())
            out.append(f"{prelude}{{{inner}}}")
        else:
            out.append(f"{_scope_selectors(prelude, prefix)}{{{inner}}}")
        i = close + 1
    return "".join(out)


def _split_selector_list(prelude: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(prelude):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(prelude[start:i])
            start = i + 1
    parts.append(prelude[start:])
    return parts


def _scope_selectors(prelude: str, prefix: str) -> str:
    out = []
    for part in _split_selector_list(prelude):
        selector = part.strip()
        if not selector.startswith((".", "[")):
            raise LiveError(
                f"selector {selector!r} must start with a class (or [attr]) on or inside the variant's element"
            )
        lead = part[: len(part) - len(part.lstrip())]
        trail = part[len(part.rstrip()) :]
        out.append(f"{lead}{prefix}{selector}{trail}")
    return ",".join(out)


def _number_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def knob_literals(schema: list[dict], sent: dict) -> dict[str, str]:
    """Each declared knob's CSS literal, from the sent value or its default."""
    declared = {knob["id"]: knob for knob in schema}
    for kid in sent:
        if kid not in declared:
            raise LiveError(
                f"unknown knob {kid!r}; this variant declares: {', '.join(declared) or 'none'}"
            )
    literals = {}
    for kid, knob in declared.items():
        value = sent.get(kid, knob["default"])
        if knob["kind"] == "range":
            if not _is_number(value) or not knob["min"] <= value <= knob["max"]:
                raise LiveError(
                    f"knob {kid}: {value!r} is not a number from {knob['min']} to {knob['max']}"
                )
            literals[kid] = _number_text(value) + knob.get("unit", "")
        elif knob["kind"] == "steps":
            options = {option["key"]: option["value"] for option in knob["options"]}
            if value not in options:
                raise LiveError(
                    f"knob {kid}: {value!r} is not one of {', '.join(options)}"
                )
            literals[kid] = options[value]
        else:
            if not isinstance(value, bool):
                raise LiveError(f"knob {kid}: {value!r} is not true or false")
            literals[kid] = knob["on"] if value else knob["off"]
    return literals


KNOB_VAR_RE = re.compile(r"var\(\s*--p-([a-z][a-z0-9-]*)\s*[,)]")


def bake_knobs(text: str, literals: dict[str, str]) -> str:
    """Replace every var(--p-<id>, …) with its knob's literal."""
    out, i = [], 0
    while match := KNOB_VAR_RE.search(text, i):
        kid = match.group(1)
        if kid not in literals:
            raise LiveError(
                f"var(--p-{kid}) is used but no knob {kid!r} is declared on this variant"
            )
        depth, j = 0, match.start() + len("var")
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        else:
            raise LiveError(f"var(--p-{kid} has no closing parenthesis")
        out += [text[i : match.start()], literals[kid]]
        i = j + 1
    out.append(text[i:])
    return "".join(out)
