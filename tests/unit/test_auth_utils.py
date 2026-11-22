import pytest

from helpers.auth_utils import limit_to_type

pytestmark = pytest.mark.unit


def test_limit_to_type_allows_matching_authenticated_user(app, teacher):
    from flask_login import login_user

    with app.test_request_context("/"):
        login_user(teacher)

        assert limit_to_type("teacher") is None


def test_limit_to_type_rejects_a_different_role(app, learner):
    from flask_login import login_user
    from werkzeug.exceptions import Forbidden

    with app.test_request_context("/"):
        login_user(learner)

        with pytest.raises(Forbidden):
            limit_to_type("teacher")


# ── usernames are one namespace across every role that signs in with one ─────


@pytest.mark.parametrize("role", ["learner", "administrator", "school_admin"])
def test_a_username_held_by_any_role_is_taken(db_session, role):
    from helpers.auth_utils import username_taken
    from tests.support import factories

    school = factories.make_school(db_session)
    make = {
        "learner": lambda: factories.make_learner(db_session, school, username="shared"),
        "administrator": lambda: factories.make_admin(db_session, username="shared"),
        "school_admin": lambda: factories.make_school_admin(db_session, school, username="shared"),
    }[role]
    holder = make()

    assert username_taken("shared")
    assert not username_taken("shared", exclude_id=holder.id)
    assert not username_taken("free")


@pytest.mark.parametrize("value", ["a b", " ab", "ab ", "a\tb", "a\nb", "a\u00a0b", "a\u3000b"])
def test_has_whitespace_spots_every_kind_of_space(value):
    from helpers.auth_utils import has_whitespace

    assert has_whitespace(value)


@pytest.mark.parametrize("value", ["", "ab", "Password1!", "a_b-c.d"])
def test_has_whitespace_is_false_without_spaces(value):
    from helpers.auth_utils import has_whitespace

    assert not has_whitespace(value)
