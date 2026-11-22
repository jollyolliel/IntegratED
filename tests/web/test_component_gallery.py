"""The dev-only component gallery: /dev/components (spec 02 seam 6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.app import use_environment
from tests.support.html import parse

pytestmark = pytest.mark.web

COMPONENTS = Path(__file__).resolve().parents[2] / "templates" / "components"
SHELLS = ["game", "legal", "library", "announcement", "assistant"]


def _tag(path: Path) -> str:
    return "".join(part.capitalize() for part in path.stem.split("_"))


def test_the_gallery_renders_in_dev(client):
    response = client.get("/dev/components")

    assert response.status_code == 200
    assert parse(response.get_data(as_text=True)).find("html").attrs["dir"] == "ltr"


def test_the_quiz_hint_preview_renders_in_dev(client):
    assert client.get("/dev/quiz-hint").status_code == 200


@pytest.mark.parametrize(
    "url", ["/dev/components", "/dev/quiz-hint", *[f"/dev/components/shell/{shell}" for shell in SHELLS]]
)
def test_the_gallery_is_not_found_when_deployed(app, client, monkeypatch, url):
    use_environment(app, monkeypatch, "production")

    assert client.get(url).status_code == 404


def test_the_gallery_switches_to_rtl_with_a_lang_query(client):
    html = parse(client.get("/dev/components?lang=ar").get_data(as_text=True)).find("html")

    assert (html.attrs["lang"], html.attrs["dir"]) == ("ar", "rtl")


@pytest.mark.parametrize("shell", SHELLS)
def test_each_page_shell_demo_renders(client, shell):
    assert client.get(f"/dev/components/shell/{shell}").status_code == 200


def test_an_unknown_shell_demo_is_not_found(client):
    assert client.get("/dev/components/shell/nope").status_code == 404


def test_the_gallery_shows_every_shared_component(client):
    root = parse(client.get("/dev/components").get_data(as_text=True))
    shown = {element.attrs["data-component"] for element in root.find_all() if "data-component" in element.attrs}

    assert sorted({_tag(path) for path in COMPONENTS.rglob("*.jx")} - shown) == []


def test_the_gallery_groups_each_component_under_its_layer(client):
    from helpers.clay_primitives import COMPONENTS as SPECS

    root = parse(client.get("/dev/components").get_data(as_text=True))
    groups = {
        group.attrs["data-layer"]: {el.attrs["data-component"] for el in group.find_all() if "data-component" in el.attrs}
        for group in root.find_all()
        if "data-layer" in group.attrs
    }

    assert {name: spec.layer for name, spec in SPECS.items() if name not in groups.get(spec.layer, set())} == {}
