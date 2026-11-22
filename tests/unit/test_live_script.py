"""Unit tests for scripts/live.py — the wrapper surgery behind live variant sessions."""

from __future__ import annotations

import json
import re

import pytest

from scripts.live import (
    LiveError,
    accept_text,
    build_parser,
    closed_lines,
    discard_text,
    find_sessions,
    finish_text,
    new_id,
    refine_text,
    show_session,
    status,
    wrap_text,
)

pytestmark = pytest.mark.unit

SID = "a1b2c3d4"

SOURCE = (
    "<main>\n"
    "  <h1>{{ t('home.title') }}</h1>\n"
    '  <section class="hero">\n'
    "    <p>Hi</p>\n"
    "  </section>\n"
    "  <footer></footer>\n"
    "</main>\n"
)

TWO_VARIANTS = """{# variant name="Louder heading" #}
<section class="hero text-4xl">
  <p>Hi!</p>
</section>
{# variant name="Calmer" #}
<section class="hero">
  <p>hi</p>
</section>
"""


def variant(
    name: str, body: str, *, knobs: list | None = None, css: str | None = None
) -> str:
    out = f'{{# variant name="{name}" #}}\n'
    if knobs is not None:
        out += f"{{# knobs {json.dumps(knobs)} #}}\n"
    if css is not None:
        out += f"<style>{css}</style>\n"
    return out + body + "\n"


def wrap(source: str = SOURCE, variants: str = TWO_VARIANTS, **kw) -> str:
    kw.setdefault("session_id", SID)
    kw.setdefault("action", "bolder")
    if not {"insert_after", "insert_before"} & kw.keys():
        kw.setdefault("lines", (3, 5))
    return wrap_text(source, variants, **kw)


# --- wrap -------------------------------------------------------------------


def test_wrap_replaces_the_range_with_the_session_block():
    assert wrap() == (
        "<main>\n"
        "  <h1>{{ t('home.title') }}</h1>\n"
        "  {# live:a1b2c3d4 start #}\n"
        '  <div data-live-session="a1b2c3d4" data-live-action="bolder" data-live-mode="replace" data-live-round="1">\n'
        "  <style data-live-base>[data-live-session],[data-live-variant]:not([hidden]){display:contents}</style>\n"
        "  {# live:a1b2c3d4 v0 #}\n"
        '  <div data-live-variant="0" data-live-name="Current" hidden>\n'
        '  <section class="hero">\n'
        "    <p>Hi</p>\n"
        "  </section>\n"
        "  </div>\n"
        "  {# live:a1b2c3d4 v1 #}\n"
        '  <div data-live-variant="1" data-live-name="Louder heading">\n'
        '  <section class="hero text-4xl">\n'
        "    <p>Hi!</p>\n"
        "  </section>\n"
        "  </div>\n"
        "  {# live:a1b2c3d4 v2 #}\n"
        '  <div data-live-variant="2" data-live-name="Calmer" hidden>\n'
        '  <section class="hero">\n'
        "    <p>hi</p>\n"
        "  </section>\n"
        "  </div>\n"
        "  </div>\n"
        "  {# live:a1b2c3d4 end #}\n"
        "  <footer></footer>\n"
        "</main>\n"
    )


def test_only_variant_one_is_visible_and_each_carries_its_name():
    three = TWO_VARIANTS + variant(
        "Split layout", '<section class="hero grid"></section>'
    )
    divs = re.findall(
        r'<div data-live-variant="(\d)" data-live-name="([^"]*)"( hidden)?>',
        wrap(variants=three),
    )

    assert divs == [
        ("0", "Current", " hidden"),
        ("1", "Louder heading", ""),
        ("2", "Calmer", " hidden"),
        ("3", "Split layout", " hidden"),
    ]


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_lines_outside_the_range_are_byte_identical(eol):
    source = SOURCE.replace("\n", eol)
    out = wrap(source)

    lines = out.splitlines(keepends=True)
    assert "".join(lines[:2]) == "".join(source.splitlines(keepends=True)[:2])
    assert "".join(lines[-2:]) == "".join(source.splitlines(keepends=True)[-2:])
    assert all(line.endswith(eol) for line in lines)


def test_variant_names_are_html_escaped():
    out = wrap(variants=variant("Bold & <loud>", '<section class="hero"></section>'))

    assert 'data-live-name="Bold &amp; &lt;loud&gt;"' in out


def test_a_label_names_the_session_for_the_extension_and_is_escaped():
    out = wrap(label='Hero & "doors"')

    assert (
        '<div data-live-session="a1b2c3d4" data-live-action="bolder" data-live-mode="replace"'
        ' data-live-round="1" data-live-label="Hero &amp; &quot;doors&quot;">'
    ) in out


def test_the_label_comes_from_the_wrap_command_line():
    argv = f"wrap --id {SID} --action bolder --file x.jx --lines 3-5 --label Hero"
    args = build_parser().parse_args(argv.split())

    assert args.label == "Hero"


def test_refine_keeps_the_label_and_still_bumps_the_round():
    out = refine_text(wrap(label="Hero"), SID, 1, TWO_VARIANTS)

    assert 'data-live-round="2" data-live-label="Hero"' in out


def test_accept_of_a_labelled_session_leaves_no_live_attributes():
    out, _ = accept_text(wrap(label="Hero"), SID, 1, {})

    assert "live" not in out


# --- CSS scoping ------------------------------------------------------------


def css_line(out: str, n: int) -> str:
    match = re.search(
        rf'<div data-live-variant="{n}"[^\n]*\n\s*<style data-live-css>(.*?)</style>',
        out,
        re.DOTALL,
    )
    assert match, out
    return match.group(1)


def two_with_css(css: str) -> str:
    return variant("One", '<section class="hero"></section>') + variant(
        "Two", '<section class="hero"></section>', css=css
    )


def test_css_rules_are_scoped_to_their_variant():
    out = wrap(variants=two_with_css(".a{x:1} .b .c{y:2}"))

    assert (
        css_line(out, 2)
        == '[data-live-variant="2"] .a{x:1} [data-live-variant="2"] .b .c{y:2}'
    )


def test_every_part_of_a_selector_list_is_scoped():
    out = wrap(variants=two_with_css(".a, .b:hover{x:1}"))

    assert (
        css_line(out, 2)
        == '[data-live-variant="2"] .a, [data-live-variant="2"] .b:hover{x:1}'
    )


@pytest.mark.parametrize(
    "rule",
    [
        "@media (min-width: 640px)",
        "@supports (display: grid)",
        "@container card (width > 20rem)",
    ],
)
def test_rules_inside_conditional_at_rules_are_scoped(rule):
    out = wrap(variants=two_with_css(f"{rule}{{.a{{x:1}}}}"))

    assert css_line(out, 2) == f'{rule}{{[data-live-variant="2"] .a{{x:1}}}}'


def test_keyframes_are_left_unscoped():
    css = "@keyframes rise{0%{opacity:0} to{opacity:1}} .a{animation:rise 1s}"
    out = wrap(variants=two_with_css(css))

    assert (
        css_line(out, 2)
        == '@keyframes rise{0%{opacity:0} to{opacity:1}} [data-live-variant="2"] .a{animation:rise 1s}'
    )


def test_multiline_css_is_reindented_with_the_variant():
    out = wrap(variants=two_with_css("\n.a {\n  x: 1;\n}\n"))

    assert (
        '  <style data-live-css>\n  [data-live-variant="2"] .a {\n    x: 1;\n  }\n  </style>\n'
        in out
    )


# --- refusals ---------------------------------------------------------------


def assert_refused(match: str, **kw):
    with pytest.raises(LiveError, match=match):
        wrap(**kw)


@pytest.mark.parametrize(
    "selector", ["section", "#hero", "> .a", "* .a", "section.hero"]
)
def test_selectors_that_cannot_be_unscoped_are_refused(selector):
    assert_refused("selector", variants=two_with_css(f"{selector}{{x:1}}"))


def test_two_variants_defining_the_same_keyframes_are_refused():
    frames = "@keyframes rise{to{opacity:1}}"
    variants = variant("A", '<section class="hero"></section>', css=frames) + variant(
        "B", '<section class="hero"></section>', css=frames
    )

    assert_refused("keyframes", variants=variants)


@pytest.mark.parametrize(
    "body",
    [
        "just words",
        '<section class="a"></section>\n<section class="b"></section>',
        '<p>one</p><p class="x">two</p>',
    ],
)
def test_a_variant_needs_exactly_one_top_level_element(body):
    assert_refused("top-level element", variants=variant("A", body))


def test_no_variants_is_refused():
    assert_refused("no variants", variants="\n")


def test_more_than_eight_variants_is_refused():
    nine = "".join(
        variant(f"V{i}", '<section class="hero"></section>') for i in range(9)
    )

    assert_refused("at most 8", variants=nine)


def test_text_before_the_first_variant_is_refused():
    assert_refused("before the first", variants="<p>stray</p>\n" + TWO_VARIANTS)


RANGE = {
    "id": "scale",
    "kind": "range",
    "label": "Size",
    "min": 0.8,
    "max": 1.3,
    "step": 0.05,
    "default": 1,
}
STEPS = {
    "id": "gap",
    "kind": "steps",
    "label": "Spacing",
    "default": "snug",
    "options": [
        {"key": "airy", "label": "Airy", "value": "2.5rem"},
        {"key": "snug", "label": "Snug", "value": "1.5rem"},
    ],
}
TOGGLE = {
    "id": "accent",
    "kind": "toggle",
    "label": "Accent",
    "default": False,
    "on": "var(--color-accent)",
    "off": "transparent",
}


@pytest.mark.parametrize(
    "knobs",
    [
        [{**RANGE, "id": "Scale"}],
        [{**RANGE, "kind": "dial"}],
        [{k: v for k, v in RANGE.items() if k != "step"}],
        [{**STEPS, "default": "huge"}],
        [{k: v for k, v in TOGGLE.items() if k != "off"}],
        [RANGE, STEPS, TOGGLE, {**RANGE, "id": "b"}, {**RANGE, "id": "c"}],
        [{**RANGE, "label": "Hero's size"}],
        [RANGE, RANGE],
        {"id": "scale"},
    ],
    ids=[
        "bad-id",
        "unknown-kind",
        "range-missing-step",
        "steps-bad-default",
        "toggle-missing-off",
        "five",
        "quote",
        "dupe",
        "not-a-list",
    ],
)
def test_invalid_knobs_are_refused(knobs):
    assert_refused(
        "knob", variants=variant("A", '<section class="hero"></section>', knobs=knobs)
    )


def test_knobs_are_written_onto_the_variant_div():
    out = wrap(
        variants=variant(
            "A", '<section class="hero"></section>', knobs=[RANGE, STEPS, TOGGLE]
        )
    )

    attr = re.search(r"data-live-knobs='([^']*)'", out)
    assert attr and json.loads(attr.group(1)) == [RANGE, STEPS, TOGGLE]


def test_an_id_already_open_is_refused():
    assert_refused("already open", open_ids={SID})


def test_an_id_already_open_in_the_same_file_is_refused():
    with pytest.raises(LiveError, match="already open"):
        wrap(wrap(), lines=(1, 1))


def test_a_range_overlapping_an_open_session_is_refused():
    once = wrap()

    with pytest.raises(LiveError, match="overlap"):
        wrap(once, session_id="bbbbbbbb", lines=(2, 4))


def test_a_malformed_id_or_unknown_action_is_refused():
    assert_refused("id", session_id="XYZ")
    assert_refused("action", action="shout")


def test_a_range_outside_the_file_is_refused():
    assert_refused("line", lines=(6, 12))


def test_refusals_leave_the_source_untouched():
    source = SOURCE
    with pytest.raises(LiveError):
        wrap(source, variants="")
    assert source == SOURCE


# --- insert mode, indentation, element counting -----------------------------


def test_insert_after_adds_the_block_with_an_empty_without_variant():
    out = wrap(insert_after=5)
    lines = out.splitlines()

    assert lines[:5] == SOURCE.splitlines()[:5]
    assert lines[-2:] == SOURCE.splitlines()[-2:]
    assert 'data-live-mode="insert"' in out
    assert (
        '<div data-live-variant="0" data-live-name="Without" hidden>\n  </div>\n' in out
    )


def test_insert_before_puts_the_block_above_the_anchor():
    out = wrap(insert_before=3)
    lines = out.splitlines()

    assert lines[2] == "  {# live:a1b2c3d4 start #}"
    assert lines[-5:] == SOURCE.splitlines()[-5:]


def test_variants_take_the_first_original_lines_indentation_and_keep_their_own():
    variants = variant(
        "Deep",
        '        <section class="hero">\n            <p>x</p>\n        </section>',
    )
    out = wrap(variants=variants)

    assert '  <section class="hero">\n      <p>x</p>\n  </section>\n' in out


def test_a_single_element_inside_a_jinja_block_counts_as_one():
    body = '{% if user %}\n<section class="hero">{{ user.name }} <img src="{{ x }}"> <br/> <Icon name="star" /></section>\n{% endif %}'

    assert "{% if user %}" in wrap(variants=variant("If", body))


def test_jinja_spans_and_comments_do_not_count_as_elements():
    body = '{# <p>not real</p> #}<section class="hero" title="a > b">{{ "<p>" }}<!-- <div> --></section>'

    assert "Icon" not in wrap(variants=variant("Spans", body))


# --- refine -----------------------------------------------------------------


def names(out: str) -> list[tuple[str, str, str]]:
    return re.findall(
        r'<div data-live-variant="(\d)" data-live-name="([^"]*)"(?: data-live-knobs=\'[^\']*\')?( hidden)?>',
        out,
    )


def three_round_one() -> str:
    third = variant(
        "Split",
        '<section class="hero grid"></section>',
        knobs=[RANGE],
        css=".hero{gap:var(--p-scale,1)}",
    )
    return wrap(variants=TWO_VARIANTS + third)


def test_refine_promotes_the_base_to_variant_one_and_bumps_the_round():
    out = refine_text(
        three_round_one(),
        SID,
        3,
        variant("Tighter", '<section class="hero gap-2"></section>'),
    )

    assert names(out) == [
        ("0", "Current", " hidden"),
        ("1", "Split (kept)", ""),
        ("2", "Tighter", " hidden"),
    ]
    assert 'data-live-round="2"' in out


def test_refine_rescopes_the_kept_variants_css_and_keeps_its_knobs():
    out = refine_text(
        three_round_one(),
        SID,
        3,
        variant("Tighter", '<section class="hero gap-2"></section>'),
    )

    knobs = re.search(r"data-live-knobs='([^']*)'", out)
    assert css_line(out, 1) == '[data-live-variant="1"] .hero{gap:var(--p-scale,1)}'
    assert knobs and json.loads(knobs.group(1)) == [RANGE]


def test_refine_leaves_variant_zero_untouched():
    before = three_round_one()
    out = refine_text(before, SID, 2, TWO_VARIANTS)

    v0 = re.compile(r"\{# live:a1b2c3d4 v0 #\}.*?\{# live:a1b2c3d4 v1 #\}", re.DOTALL)
    old, new = v0.search(before), v0.search(out)
    assert old and new and new.group(0) == old.group(0)


def test_refining_a_kept_variant_again_does_not_stack_the_suffix():
    once = refine_text(three_round_one(), SID, 3, TWO_VARIANTS)
    twice = refine_text(once, SID, 1, TWO_VARIANTS)

    assert names(twice)[1] == ("1", "Split (kept)", "")
    assert 'data-live-round="3"' in twice


@pytest.mark.parametrize("keep", [0, 4])
def test_refine_needs_an_existing_non_original_base(keep):
    with pytest.raises(LiveError, match="variant"):
        refine_text(three_round_one(), SID, keep, TWO_VARIANTS)


def test_refine_counts_the_kept_variant_toward_the_limit():
    eight = "".join(
        variant(f"V{i}", '<section class="hero"></section>') for i in range(8)
    )

    with pytest.raises(LiveError, match="at most 8"):
        refine_text(three_round_one(), SID, 1, eight)


def test_refine_of_an_unknown_session_is_refused():
    with pytest.raises(LiveError, match="no live session"):
        refine_text(SOURCE, SID, 1, TWO_VARIANTS)


# --- accept -----------------------------------------------------------------


def test_accept_leaves_only_the_chosen_variants_element():
    out, css = accept_text(wrap(), SID, 2)

    assert out == SOURCE.replace("<p>Hi</p>", "<p>hi</p>")
    assert css == ""


def test_accept_in_insert_mode_adds_the_element_and_removes_nothing():
    out, _ = accept_text(wrap(insert_after=5), SID, 1)

    assert out.splitlines() == [
        *SOURCE.splitlines()[:5],
        '  <section class="hero text-4xl">',
        "    <p>Hi!</p>",
        "  </section>",
        *SOURCE.splitlines()[5:],
    ]


KNOBBED = variant(
    "Knobbed",
    '<section class="hero gap-[var(--p-gap,1.5rem)]" style="font-size:var(--p-scale, 1); background:var(--p-accent,transparent)"></section>',
    knobs=[{**RANGE, "unit": "rem"}, STEPS, TOGGLE],
    css=".hero{padding:var(--p-scale,calc(1 + 2px))}",
)


def accept_knobbed(knobs: dict | None) -> tuple[str, str]:
    return accept_text(wrap(variants=KNOBBED), SID, 1, knobs)


def test_accept_bakes_sent_knob_values_into_markup():
    out, _ = accept_knobbed({"scale": 1.15, "gap": "airy", "accent": True})

    assert (
        '<section class="hero gap-[2.5rem]" style="font-size:1.15rem; background:var(--color-accent)"></section>'
        in out
    )


def test_accept_bakes_knobs_into_the_returned_css_without_the_scope():
    _, css = accept_knobbed({"scale": 1.15})

    assert css == ".hero{padding:1.15rem}"


def test_knobs_not_sent_bake_to_their_defaults():
    out, _ = accept_knobbed(None)

    assert (
        '<section class="hero gap-[1.5rem]" style="font-size:1rem; background:transparent"></section>'
        in out
    )


def test_accept_leaves_no_live_attributes_or_markers():
    out, _ = accept_knobbed({})

    assert "live" not in out


@pytest.mark.parametrize(
    "knobs, match",
    [
        ({"size": 1}, "unknown knob"),
        ({"gap": "huge"}, "gap"),
        ({"scale": "big"}, "scale"),
        ({"accent": "yes"}, "accent"),
        ({"scale": 9}, "scale"),
    ],
)
def test_bad_knob_values_are_refused(knobs, match):
    with pytest.raises(LiveError, match=match):
        accept_knobbed(knobs)


def test_an_undeclared_knob_in_the_markup_is_an_error():
    wrapped = wrap(
        variants=variant(
            "A", '<section class="hero" style="gap:var(--p-ghost,1px)"></section>'
        )
    )

    with pytest.raises(LiveError, match="ghost"):
        accept_text(wrapped, SID, 1)


def test_accepting_variant_zero_is_a_discard():
    wrapped = wrap()

    assert accept_text(wrapped, SID, 0) == (discard_text(wrapped, SID), "")


def test_accepting_a_missing_variant_is_refused():
    with pytest.raises(LiveError, match="variant 5"):
        accept_text(wrap(), SID, 5)


def test_closed_lines_are_where_the_kept_element_now_sits():
    wrapped = wrap()
    out, _ = accept_text(wrapped, SID, 1)

    assert closed_lines(wrapped, out, SID) == (3, 5)
    assert out.splitlines()[2:5] == [
        '  <section class="hero text-4xl">',
        "    <p>Hi!</p>",
        "  </section>",
    ]


# --- finish: close a session with an element Claude finished by hand ---------

APPLIED = variant(
    "Applied", '<section class="hero text-5xl">\n  <p>Hey there</p>\n</section>'
)


def test_finish_replaces_the_session_with_the_given_element():
    out = finish_text(wrap(), SID, APPLIED)

    assert out == SOURCE.replace(
        '<section class="hero">\n    <p>Hi</p>',
        '<section class="hero text-5xl">\n    <p>Hey there</p>',
    )


def test_finish_in_insert_mode_adds_the_element_and_removes_nothing():
    out = finish_text(wrap(insert_after=5), SID, APPLIED)

    assert out.splitlines() == [
        *SOURCE.splitlines()[:5],
        '  <section class="hero text-5xl">',
        "    <p>Hey there</p>",
        "  </section>",
        *SOURCE.splitlines()[5:],
    ]


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_finish_after_a_refine_keeps_every_other_line_and_the_line_endings(eol):
    source = SOURCE.replace("\n", eol)
    refined = refine_text(wrap(source), SID, 2, TWO_VARIANTS)

    out = finish_text(refined, SID, APPLIED)

    assert out == source.replace(
        f'<section class="hero">{eol}    <p>Hi</p>',
        f'<section class="hero text-5xl">{eol}    <p>Hey there</p>',
    )


def test_finish_leaves_other_sessions_open():
    both = wrap(wrap(), session_id="bbbbbbbb", lines=(1, 1))

    out = finish_text(both, SID, APPLIED)

    assert [row["id"] for row in find_sessions(out)] == ["bbbbbbbb"]
    assert '<section class="hero text-5xl">' in out


@pytest.mark.parametrize(
    "variants, match",
    [
        (APPLIED + APPLIED, "exactly one"),
        (variant("A", '<section class="hero"></section>', knobs=[RANGE]), "knobs"),
        (variant("A", '<section class="hero"></section>', css=".hero{gap:0}"), "CSS"),
        (variant("A", '<section style="gap:var(--p-gap,1rem)"></section>'), "gap"),
    ],
    ids=["two-variants", "knobs", "style", "unbaked-knob"],
)
def test_finish_refuses_anything_but_one_final_element(variants, match):
    with pytest.raises(LiveError, match=match):
        finish_text(wrap(), SID, variants)


def test_finish_of_an_unknown_session_is_refused():
    with pytest.raises(LiveError, match="no live session"):
        finish_text(SOURCE, SID, APPLIED)


# --- show: everything a chat that didn't open the session needs --------------


def test_show_describes_the_session_and_its_variants():
    wrapped = wrap(variants=TWO_VARIANTS + KNOBBED, label="Hero")

    assert show_session(wrapped, SID) == {
        "id": SID,
        "line": 3,
        "end": len(wrapped.splitlines()) - 2,
        "label": "Hero",
        "action": "bolder",
        "mode": "replace",
        "round": 1,
        "variants": [
            {"n": 0, "name": "Current", "knobs": [], "css": False},
            {"n": 1, "name": "Louder heading", "knobs": [], "css": False},
            {"n": 2, "name": "Calmer", "knobs": [], "css": False},
            {
                "n": 3,
                "name": "Knobbed",
                "knobs": ["scale", "gap", "accent"],
                "css": True,
            },
        ],
    }


def test_show_with_a_variant_gives_its_markup_dedented():
    shown = show_session(wrap(), SID, variant=1)

    assert shown["markup"] == '<section class="hero text-4xl">\n  <p>Hi!</p>\n</section>\n'
    assert shown["css"] == ""


def test_show_of_the_original_gives_the_lines_that_were_wrapped():
    assert show_session(wrap(), SID, variant=0)["markup"] == (
        '<section class="hero">\n  <p>Hi</p>\n</section>\n'
    )


def test_show_bakes_the_sent_knobs_into_markup_and_unscoped_css():
    shown = show_session(
        wrap(variants=KNOBBED), SID, variant=1, knobs={"scale": 1.15, "gap": "airy"}
    )

    assert 'class="hero gap-[2.5rem]"' in shown["markup"]
    assert "font-size:1.15rem" in shown["markup"]
    assert shown["css"] == ".hero{padding:1.15rem}"


def test_show_of_a_missing_variant_is_refused():
    with pytest.raises(LiveError, match="variant 7"):
        show_session(wrap(), SID, variant=7)


# --- discard, status, new-id ------------------------------------------------


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize(
    "where",
    [
        {"lines": (3, 5)},
        {"lines": (1, 7)},
        {"lines": (7, 7)},
        {"insert_after": 5},
        {"insert_before": 1},
        {"insert_after": 7},
    ],
    ids=[
        "middle",
        "whole-file",
        "last-line",
        "insert-after",
        "insert-before-first",
        "insert-after-last",
    ],
)
@pytest.mark.parametrize(
    "variants", [TWO_VARIANTS, KNOBBED], ids=["plain", "knobs-and-css"]
)
def test_discard_restores_the_source_exactly(eol, where, variants):
    source = SOURCE.replace("\n", eol)

    assert discard_text(wrap(source, variants, **where), SID) == source


def test_discard_restores_a_last_line_without_a_newline():
    source = SOURCE.rstrip("\n")

    assert discard_text(wrap(source, lines=(6, 7)), SID) == source


def test_discard_after_a_refine_still_restores_the_source():
    refined = refine_text(wrap(), SID, 2, TWO_VARIANTS)

    assert discard_text(refined, SID) == SOURCE


def test_discard_leaves_other_sessions_open():
    both = wrap(wrap(), session_id="bbbbbbbb", lines=(1, 1))

    assert discard_text(both, "bbbbbbbb") == wrap()


def test_status_reports_each_session(tmp_path):
    pages = tmp_path / "templates" / "pages"
    pages.mkdir(parents=True)
    (pages / "a.jx").write_text(wrap(), encoding="utf-8")
    (pages / "b.jx").write_text(
        wrap(session_id="0000beef", action="layout", insert_after=1), encoding="utf-8"
    )
    (pages / "c.jx").write_text(SOURCE, encoding="utf-8")

    assert status(str(tmp_path / "templates"), root=str(tmp_path)) == [
        {
            "file": "templates/pages/a.jx",
            "line": 3,
            "id": SID,
            "action": "bolder",
            "mode": "replace",
            "round": 1,
            "label": "",
            "variants": 2,
            "broken": False,
        },
        {
            "file": "templates/pages/b.jx",
            "line": 2,
            "id": "0000beef",
            "action": "layout",
            "mode": "insert",
            "round": 1,
            "label": "",
            "variants": 2,
            "broken": False,
        },
    ]


def test_a_start_marker_without_an_end_is_reported_broken():
    lines = wrap().splitlines(keepends=True)
    broken = "".join(line for line in lines if "live:a1b2c3d4 end" not in line)

    assert find_sessions(broken)[0]["broken"] is True


def test_new_id_skips_ids_that_are_already_open():
    tokens = iter(["a1b2c3d4", "0f0f0f0f"])

    assert new_id({SID}, token=lambda: next(tokens)) == "0f0f0f0f"


def test_new_id_is_eight_lowercase_hex_characters():
    assert re.fullmatch(r"[0-9a-f]{8}", new_id(set()))


# --- writing on Windows: a file briefly locked by OneDrive or the dev server ---


def _flaky_replace(monkeypatch, failures: int) -> list[int]:
    """Make os.replace raise PermissionError `failures` times, then work."""
    import os

    from scripts import live

    real, calls = os.replace, []

    def replace(src, dst):
        calls.append(1)
        if len(calls) <= failures:
            raise PermissionError(5, "Access is denied")
        real(src, dst)

    monkeypatch.setattr(live.os, "replace", replace)
    monkeypatch.setattr(live.time, "sleep", lambda _seconds: None)
    return calls


def test_a_briefly_locked_template_is_written_after_a_retry(tmp_path, monkeypatch):
    from scripts.live import _write_atomic

    target = tmp_path / "page.jx"
    target.write_text("old\n", encoding="utf-8")
    calls = _flaky_replace(monkeypatch, failures=2)

    _write_atomic(str(target), "new\n")

    assert target.read_text(encoding="utf-8") == "new\n"
    assert len(calls) == 3
    assert [p.name for p in tmp_path.iterdir()] == ["page.jx"]


def test_a_template_that_stays_locked_is_refused_and_leaves_no_temp_file(tmp_path, monkeypatch):
    from scripts.live import _write_atomic

    target = tmp_path / "page.jx"
    target.write_text("old\n", encoding="utf-8")
    _flaky_replace(monkeypatch, failures=1000)

    with pytest.raises(LiveError, match="locked"):
        _write_atomic(str(target), "new\n")

    assert target.read_text(encoding="utf-8") == "old\n"
    assert [p.name for p in tmp_path.iterdir()] == ["page.jx"]


def test_a_template_edit_waits_for_another_chats_edit(tmp_path, monkeypatch, capsys):
    from scripts import live
    from scripts.file_lock import locked

    lock = str(tmp_path / "edit.lock")
    monkeypatch.setattr(live, "LOCK_PATH", lock)
    monkeypatch.setattr(live, "LOCK_TIMEOUT", 0.2)
    with locked(lock):
        assert live.main(["discard", SID]) == 1

    assert "busy" in capsys.readouterr().err


# --- the command line ---------------------------------------------------------


def test_accept_takes_a_variant_number_or_a_finished_element_file():
    by_number = build_parser().parse_args(["accept", SID, "2", "--knobs", "{}"])
    by_file = build_parser().parse_args(["accept", SID, "--variants", ".live/x.jx"])

    assert (by_number.variant, by_number.variants) == (2, None)
    assert (by_file.variant, by_file.variants) == (None, ".live/x.jx")


@pytest.mark.parametrize(
    "argv",
    [["accept", SID], ["accept", SID, "2", "--variants", ".live/x.jx"]],
    ids=["neither", "both"],
)
def test_accept_needs_exactly_one_of_a_number_or_a_file(argv, capsys):
    from scripts import live

    assert live.main(argv) == 1
    assert "variant number or --variants" in capsys.readouterr().err


def test_show_parses_a_variant_and_its_knobs():
    args = build_parser().parse_args(
        ["show", SID, "--variant", "1", "--knobs", '{"gap": "airy"}']
    )

    assert (args.id, args.variant, args.knobs) == (SID, 1, '{"gap": "airy"}')
