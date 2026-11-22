"""Per-deploy values shown on public pages (contact email, source link) come from settings, never from the templates."""

from __future__ import annotations

import dataclasses

import pytest

pytestmark = pytest.mark.web


@pytest.fixture
def configure(app, monkeypatch):
    def apply(**changes):
        monkeypatch.setitem(app.config, "SETTINGS", dataclasses.replace(app.config["SETTINGS"], **changes))

    return apply


@pytest.mark.parametrize("path", ["/terms", "/privacy"])
def test_the_legal_pages_show_the_configured_contact_email(client, configure, path):
    configure(contact_email="hello@example.test")

    html = client.get(path).get_data(as_text=True)

    assert 'href="mailto:hello@example.test"' in html
    assert "integrated@acs.gr" not in html


@pytest.mark.parametrize("path", ["/terms", "/privacy"])
def test_the_legal_pages_leave_out_the_contact_section_when_no_email_is_set(client, configure, path):
    configure(contact_email="")

    html = client.get(path).get_data(as_text=True)

    assert "mailto:" not in html
    assert "Contact Us" not in html


def test_the_footer_links_the_build_to_the_configured_repository(client, configure, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abcdef1234567890")
    configure(github_repo_url="https://github.com/example/repo")

    html = client.get("/terms").get_data(as_text=True)

    assert 'href="https://github.com/example/repo/commit/abcdef1234567890"' in html


def test_the_footer_shows_the_version_without_a_link_when_no_repository_is_set(client, configure, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abcdef1234567890")
    configure(github_repo_url="")

    html = client.get("/terms").get_data(as_text=True)

    assert "vabcdef1" in html
    assert "/commit/" not in html
