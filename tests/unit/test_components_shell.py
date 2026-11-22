"""The page shell in templates/components/: nav pieces and the theme."""

from __future__ import annotations

import pytest

from tests.support.app import use_environment
from tests.support.html import parse
from tests.support.jx import imports as _imports

pytestmark = pytest.mark.unit


# ── NavLink ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(("active", "cls"), [(True, "nav-link-active"), (False, "nav-link-inactive")])
def test_bar_nav_link_marks_the_current_page(render_jx, active, cls):
    html = render_jx(_imports("NavLink") + f'<NavLink href="/p" label="People" active={{{{ {active} }}}} />')
    link = parse(html).find("a")

    assert link.classes == [cls]
    assert (link.attrs["href"], link.attrs["data-label"]) == ("/p", "People")
    assert link.all_text == "People"


def test_a_pulsing_bar_link_carries_the_live_dot(render_jx):
    link = parse(render_jx(_imports("NavLink") + '<NavLink href="/l" label="Learn" pulse class="relative" />')).find("a")

    assert "relative" in link.classes
    assert "learn-pulse-dot" in link.find("span").classes


@pytest.mark.parametrize(("active", "marker"), [(True, "bg-sky-100"), (False, "hover:bg-sky-50")])
def test_menu_nav_link_is_a_full_width_row(render_jx, active, marker):
    html = render_jx(_imports("NavLink") + f'<NavLink variant="menu" href="/p" label="People" active={{{{ {active} }}}} />')
    link = parse(html).find("a")

    assert {"block", "px-4", "py-3", marker} <= set(link.classes)
    assert not [c for c in link.classes if c.startswith("nav-link")]


def test_nav_link_raises_on_an_unknown_variant(render_jx):
    with pytest.raises(ValueError, match="NavLink.*variant.*side"):
        render_jx(_imports("NavLink") + '<NavLink variant="side" href="/" label="x" />')


# ── NavButton ────────────────────────────────────────────────────────


@pytest.mark.parametrize("variant", ["register", "login", "logout"])
def test_nav_button_links_in_each_variant(render_jx, variant):
    html = render_jx(_imports("NavButton") + f'<NavButton variant="{variant}" href="/x" data-no-instant>Go</NavButton>')
    link = parse(html).find("a")

    assert link.classes == [f"btn-nav-{variant}"]
    assert "data-no-instant" in link.attrs


def test_an_icon_nav_button_is_a_square_gray_button(render_jx):
    html = render_jx(_imports("NavButton") + '<NavButton icon aria-label="Assistant" data-assist-toggle>i</NavButton>')
    button = parse(html).find("button")

    assert {"btn-nav-login", "btn-nav-icon", "w-9", "h-9"} <= set(button.classes)
    assert button.attrs["type"] == "button"
    assert "data-assist-toggle" in button.attrs


@pytest.mark.parametrize(("active", "current"), [("True", "page"), ("False", None)])
def test_an_icon_nav_button_marks_the_current_page(render_jx, active, current):
    html = render_jx(_imports("NavButton") + f'<NavButton icon href="/settings" active={{{{ {active} }}}}>s</NavButton>')

    assert parse(html).find("a").attrs.get("aria-current") == current


def test_nav_button_raises_on_an_unknown_variant(render_jx):
    with pytest.raises(ValueError, match="NavButton.*variant.*signup"):
        render_jx(_imports("NavButton") + '<NavButton variant="signup" href="/">x</NavButton>')


# ── Main ─────────────────────────────────────────────────────────────

CONTAINED = ["flex-1", "container", "mx-auto", "px-4", "py-6", "md:py-8"]


def test_main_is_the_standard_container_by_default(render_jx):
    main = parse(render_jx(_imports("Main") + "<Main><h1>People</h1></Main>")).find("main")

    assert main.classes == CONTAINED
    assert main.find("h1").all_text == "People"


def test_a_contained_main_caps_its_width_and_takes_attributes(render_jx):
    main = parse(render_jx(_imports("Main") + '<Main width="3xl" id="page-content" class="space-y-4">x</Main>')).find("main")

    assert main.classes == [*CONTAINED, "max-w-3xl", "space-y-4"]
    assert main.attrs["id"] == "page-content"


def test_a_centered_main_centres_one_column_of_the_given_width(render_jx):
    main = parse(render_jx(_imports("Main") + '<Main layout="centered" width="lg"><form></form></Main>')).find("main")

    assert main.classes == ["flex-1", "flex", "items-center", "justify-center", "py-10", "px-4"]
    column = main.children[0]
    assert column.classes == ["w-full", "max-w-lg"]
    assert column.find("form")


def test_main_raises_on_an_unknown_width(render_jx):
    with pytest.raises(ValueError, match="Main.*width.*huge"):
        render_jx(_imports("Main") + '<Main width="huge">x</Main>')


# ── Theme ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("production", [False, True])
def test_theme_loads_posthog_only_in_production(app, monkeypatch, render_jx, db_session, teacher, production):
    use_environment(app, monkeypatch, "production" if production else "development", posthog_api_key="phc_test")
    html = render_jx(_imports("Theme") + "<Theme />", user=teacher)

    assert ("posthog.init" in html) is production
    assert ('"phc_test"' in html) is production
    assert "css/tailwind.css" in html
