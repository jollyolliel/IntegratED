"""Public school images: a school's photo and logo are files under `static/`."""

from __future__ import annotations

import pytest

from tests.support.factories import make_school

pytestmark = pytest.mark.web


def test_a_school_photo_is_served_from_static(client, db_session):
    make_school(db_session, name="Static School", image_path="img/acs-athens.jpg")

    html = client.get("/schools").get_data(as_text=True)

    assert 'src="/static/img/acs-athens.jpg' in html


def test_there_is_no_bucket_image_route_for_schools(client):
    assert client.get("/media/images/acs-athens.jpg").status_code == 404
