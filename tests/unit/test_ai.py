import pytest

pytestmark = pytest.mark.unit


def test_ai_tool_registry_contains_unique_names():
    from helpers.ai.registry import _builders

    names = list(_builders())

    assert names
    assert len(names) == len(set(names))


def test_scope_rejects_an_entity_owned_by_another_teacher(app, db_session, school):
    from helpers.ai.tools.domain import _owned_learner
    from tests.support.factories import make_learner, make_teacher

    owner = make_teacher(db_session, school, email="owner@example.com")
    other = make_teacher(db_session, school, email="other@example.com")
    learner = make_learner(db_session, school, owner, username="owned")

    with pytest.raises(PermissionError):
        _owned_learner(other, learner.id)
