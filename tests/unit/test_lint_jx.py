"""scripts/lint_jx.py: component-tag lint for `.jx` files, on jx's own parser, and the clay-class
ownership rule for the `.html` templates."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lint_jx import lint_jx

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
PAGE = "templates/pages/demo.jx"
# Lines 1-3 of a source that uses the base components.
IMPORTS = (
    '{#import "@components/base/button.jx" as Button #}\n'
    '{#import "@components/base/card.jx" as Card #}\n'
    '{#import "@components/base/icon.jx" as Icon #}\n'
)


def rules_by_line(source: str, path: str = PAGE) -> list[tuple[int, str]]:
    return [(finding.line, finding.rule) for finding in lint_jx(source, path)]


def test_an_unknown_literal_prop_value_is_reported_on_its_line():
    source = IMPORTS + (
        "<div>\n"
        '  <Button variant="acent">Go</Button>\n'
        '  <Icon name="no-such-icon" />\n'
        "</div>\n"
    )

    assert rules_by_line(source) == [(5, "unknown-prop-value"), (6, "unknown-prop-value")]


def test_allowed_and_expression_prop_values_are_not_reported():
    source = IMPORTS + (
        '<Button variant="sky" size="lg">Go</Button>\n'
        "<Button variant={{ v }}>Go</Button>\n"
        '<Card tone="green"><Icon name="chevron-right" size="3.5" /></Card>\n'
        '<Badge variant="anything" />\n'
    )

    assert rules_by_line(source) == []


def rule_message(rule_id: str) -> str:
    import yaml

    rule = yaml.safe_load((ROOT / "lint" / "rules" / f"{rule_id}.yml").read_text(encoding="utf-8"))
    return rule["message"].strip()


def test_a_forbidden_utility_on_a_clay_component_is_reported_with_the_rules_message():
    source = IMPORTS + (
        "<div>\n"
        '  <Button variant="sky" disabled={{ n > 0 }} class="ms-2 p-4">Go</Button>\n'
        '  <Card class="rounded-xl" />\n'
        "</div>\n"
    )

    findings = lint_jx(source, PAGE)

    assert [(finding.line, finding.rule) for finding in findings] == [
        (5, "no-restyle-on-component"),
        (6, "no-restyle-on-component"),
    ]
    assert rule_message("no-restyle-button") in findings[0].message
    assert rule_message("no-restyle-card") in findings[1].message


def test_a_composed_component_may_restyle_the_base_it_builds_on():
    source = IMPORTS + '<Card class="text-center border-[length:var(--clay-border-width)] rounded-xl" />\n'

    assert rules_by_line(source, "templates/components/stat_tile.jx") == []


def test_a_design_override_comment_lets_the_next_tag_restyle_a_base():
    source = IMPORTS + (
        "{# design: override — the hero card is rounder than any card variant #}\n"
        '<Card class="rounded-[32px]" />\n'
        '<Card class="rounded-xl" />\n'
    )

    assert rules_by_line(source) == [(6, "no-restyle-on-component")]


def test_a_design_override_on_the_same_line_counts():
    source = IMPORTS + '<Card class="shadow-none" />{# design: override — flat inside the modal #}\n'

    assert rules_by_line(source) == []


def test_a_design_override_without_a_reason_is_reported_and_frees_nothing():
    source = IMPORTS + '{# design: override #}\n<Card class="rounded-xl" />\n'

    assert rules_by_line(source) == [(4, "override-without-reason"), (5, "no-restyle-on-component")]


def test_free_classes_are_allowed_anywhere():
    source = '<div class="clay-scroll overflow-y-auto"><p class="display-font text-3xl">42</p></div>\n'

    assert rules_by_line(source) == []


def test_a_select_without_its_button_child_is_reported():
    source = (
        '<select name="subject">\n'
        "  <option>Maths</option>\n"
        "</select>\n"
        '<select name="topic" {% if locked %}disabled{% endif %}>\n'
        "  <button><selectedcontent></selectedcontent></button>\n"
        "  <option>Fractions</option>\n"
        "</select>\n"
    )

    assert rules_by_line(source) == [(1, "select-without-button")]


def test_a_listbox_select_needs_no_button_child():
    source = '<select multiple><option>A</option></select>\n<select size="4"><option>A</option></select>\n'

    assert rules_by_line(source) == []


def test_layout_utilities_on_a_clay_component_are_not_reported():
    source = IMPORTS + (
        '<Button variant="accent" class="ms-2 w-full">Go</Button>\n'
        '<Card class="p-4 grid gap-2" />\n'
        "<Button class={{ extra }} />\n"
        '<Icon name="home" class="shrink-0" />\n'
        '<div class="p-4 rounded-xl"></div>\n'
    )

    assert rules_by_line(source) == []


def test_a_clay_class_outside_its_component_is_reported():
    source = IMPORTS + (
        '<div class="clay-card p-4">\n'
        '  <button type="button" class="btn-clay btn-sky">Go</button>\n'
        '  <Card class="p-4 {{ extra }}\n'
        '    clay-card-green" />\n'
        "</div>\n"
    )

    assert rules_by_line(source) == [
        (4, "no-raw-clay-class"),
        (5, "no-raw-clay-class"),
        (6, "quoted-expression"),
        (6, "no-raw-clay-class"),
    ]


def test_another_components_clay_class_is_reported_inside_a_base():
    source = '<button class="btn-clay"><div class="clay-card"></div></button>\n'

    assert rules_by_line(source, "templates/components/base/button.jx") == [(1, "no-raw-clay-class")]


def test_a_base_may_write_its_own_clay_classes():
    source = (
        '<button class="btn-clay btn-sky {{ size_class }}">{{ content }}</button>\n'
        '{# <div class="clay-card"> in a comment #}\n'
    )

    assert rules_by_line(source, "templates/components/base/button.jx") == []


def test_look_alike_classes_comments_and_attrs_render_are_not_reported():
    source = (
        '{# <div class="clay-card"> #}\n'
        '<div class="my-btn-clay clay-card-grid">\n'
        '<a {{ attrs.render(class="btn-clay") }}></a>\n'
    )

    assert rules_by_line(source) == []


def test_a_component_named_script_or_style_is_reported():
    source = (
        '{#import "@components/script.jx" as Script #}\n'
        '{#import "@components/style.jx" as Style #}\n'
        "<Script />\n"
    )

    assert rules_by_line(source) == [
        (1, "reserved-component-name"),
        (2, "reserved-component-name"),
        (3, "reserved-component-name"),
    ]


def test_other_names_like_real_elements_are_allowed():
    source = (
        '{#import "@components/base/input.jx" as Input #}\n'
        '<Input name="q" /><script>let x = 1;</script><style>p { color: red; }</style>\n'
    )

    assert rules_by_line(source) == []


def test_every_template_under_templates_is_clean():
    findings = [
        str(finding)
        for path in sorted((ROOT / "templates").rglob("*.jx"))
        for finding in lint_jx(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix())
    ]

    if findings:
        pytest.fail("jx lint findings:\n" + "\n".join(findings), pytrace=False)


def test_the_component_catalog_has_no_check_errors():
    from jx.tools import check_all

    from helpers.jx_catalog import build_catalog

    errors, _checked = check_all(build_catalog())

    assert [f"{error.file}:{error.line}: {error.message}" for error in errors] == []


def test_a_component_is_known_by_its_import_path_not_its_alias():
    source = (
        '{#import "@components/base/button.jx" as Btn #}\n'
        '{#import "@page_components/teacher/card.jx" as Card #}\n'
        '<Btn variant="acent" class="p-4">Go</Btn>\n'
        '<Card tone="blue" class="rounded-xl" />\n'
    )

    assert rules_by_line(source) == [(3, "unknown-prop-value"), (3, "no-restyle-on-component")]


def test_a_quoted_expression_on_a_component_tag_is_reported():
    # jx reads a quoted attribute on a component as literal text: this class would be the
    # characters "{{ tone }}", never the tone. HTML elements interpolate normally.
    source = IMPORTS + (
        '<Card class="p-4 {{ extra }}" id={{ "c-" ~ n }}>\n'
        '  <div class="p-4 {{ extra }}"></div>\n'
        "</Card>\n"
    )

    assert rules_by_line(source) == [(4, "quoted-expression")]
