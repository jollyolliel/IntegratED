"""FK-graph scoping: what the assistant may read, and for whom.

The invariant under test is that scoping **fails closed** — a model with no
derivable path to a teacher is invisible, and one teacher's rows never appear
in another teacher's query.
"""

from __future__ import annotations

import pytest

from tests.support.factories import (
    make_attendance,
    make_learner,
    make_school,
    make_subject,
    make_teacher,
    make_volunteer,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def scope(app):
    from helpers.ai import scope as scope_module

    with app.app_context():
        yield scope_module


# ── classification ───────────────────────────────────────────────────────────


def test_every_mapped_model_is_classified(scope):
    """No model may fall through the walk unclassified."""

    rules = scope.classify_all()

    assert set(rules) == set(scope.mapped_models())
    assert all(rule.kind for rule in rules.values())


def test_classification_only_uses_known_kinds(scope):
    kinds = {rule.kind for rule in scope.classify_all().values()}

    assert kinds <= {"direct", "hop", "self", "global", "school", "deny"}


@pytest.mark.parametrize("name", sorted(["User", "Administrator", "SchoolAdmin", "Donation", "Article", "SiteContent", "TeamMember", "AssistantConversation", "AssistantMessage", "AssistantChange"]))
def test_policy_denied_models_are_not_readable(scope, name):
    """The POLICY denylist is authoritative over anything the walk derives."""

    assert scope.classify_all()[name].kind == "deny"
    assert name not in scope.readable_models()


def test_learner_and_volunteer_resolve_directly_to_the_teacher(scope):
    rules = scope.classify_all()

    assert rules["Learner"].kind == "direct"
    assert rules["Learner"].column == "teacher_id"
    assert rules["Volunteer"].kind == "direct"


def test_teacher_resolves_to_its_own_row(scope):
    assert scope.classify_all()["Teacher"].kind == "self"


def test_shared_curriculum_is_global(scope):
    rules = scope.classify_all()

    for name in ("Subject", "Topic", "Lesson", "Question", "MapQuestion", "Worksheet"):
        assert rules[name].kind == "global", name


def test_school_is_narrowed_rather_than_global(scope):
    assert scope.classify_all()["School"].kind == "school"


def test_learning_session_reaches_the_teacher_by_one_hop(scope):
    """LearningSession has no teacher_id; it is owned via its learner."""

    rule = scope.classify_all()["LearningSession"]

    assert rule.kind == "hop"
    assert rule.via == "Learner"


def test_the_inheritance_edge_is_never_walked(scope):
    """A subclass PK is also an FK to users.id — following it would make every
    model resolve through a bogus path."""

    for model in (scope.mapped_models()["Learner"], scope.mapped_models()["Volunteer"]):
        targets = [table for _column, table in scope._outbound_fks(model)]
        assert "users" not in targets


def test_rules_are_memoized(scope):
    assert scope.rules() is scope.rules()


# ── name resolution ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("given", ["Attendance", "attendance", "ATTENDANCE", " attendance "])
def test_canonical_name_is_case_insensitive(scope, given):
    assert scope.canonical_name(given) == "Attendance"


def test_canonical_name_passes_through_an_unknown_name(scope):
    assert scope.canonical_name("Nonsense") == "Nonsense"


def test_resolving_an_unknown_entity_is_refused(scope):
    with pytest.raises(PermissionError, match="Unknown entity"):
        scope.resolve("Nonsense")


def test_resolving_a_denied_entity_is_refused(scope):
    with pytest.raises(PermissionError, match="not available"):
        scope.resolve("Donation")


# ── redaction ────────────────────────────────────────────────────────────────


def test_credentials_are_never_visible_on_any_model(scope):
    """password_hash and google_sub must not appear for a single entity."""

    leaked = {
        name: [c for c in scope.visible_columns(model) if c in scope.REDACTED_FIELDS]
        for name, model in scope.mapped_models().items()
    }

    assert not any(leaked.values()), {k: v for k, v in leaked.items() if v}


def test_a_redacted_field_cannot_be_requested_back_in(scope, db_session):
    """`fields` is intersected with the allowlist, not subtracted from it."""

    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)
    Learner = scope.mapped_models()["Learner"]

    row = db_session.execute(
        scope.scoped_query("Learner", teacher)[0]
    ).mappings().one()
    serialized = scope.serialize_row(Learner, row, fields=["id", "password_hash"])

    assert "password_hash" not in serialized
    assert serialized["id"] == learner.id


def test_serialize_row_renders_datetimes_as_iso_strings(scope, db_session):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)
    make_attendance(db_session, teacher, learner)
    Attendance = scope.mapped_models()["Attendance"]

    row = db_session.execute(
        scope.scoped_query("Attendance", teacher)[0]
    ).mappings().one()
    serialized = scope.serialize_row(Attendance, row)

    assert isinstance(serialized["date"], str)
    assert "T" in serialized["date"]


# ── the filter ───────────────────────────────────────────────────────────────


def test_a_teacher_sees_only_their_own_learners(scope, db_session):
    school = make_school(db_session)
    mine = make_teacher(db_session, school)
    theirs = make_teacher(db_session, school)
    my_learner = make_learner(db_session, school, mine)
    make_learner(db_session, school, theirs)

    rows = db_session.execute(scope.scoped_query("Learner", mine)[0]).mappings().all()

    assert [row["id"] for row in rows] == [my_learner.id]


def test_a_hop_scoped_model_is_filtered_through_its_owner(scope, db_session):
    from models import LearningSession

    school = make_school(db_session)
    mine = make_teacher(db_session, school)
    theirs = make_teacher(db_session, school)
    my_learner = make_learner(db_session, school, mine)
    their_learner = make_learner(db_session, school, theirs)
    db_session.add_all([
        LearningSession(learner_id=my_learner.id, session_type="quiz"),
        LearningSession(learner_id=their_learner.id, session_type="quiz"),
    ])
    db_session.commit()

    rows = db_session.execute(
        scope.scoped_query("LearningSession", mine)[0]
    ).mappings().all()

    assert [row["learner_id"] for row in rows] == [my_learner.id]


def test_a_global_entity_has_no_scope_clause(scope, db_session):
    make_subject(db_session)
    teacher = make_teacher(db_session, make_school(db_session))

    assert scope.scope_clause("Subject", teacher) is None


def test_the_teacher_entity_is_narrowed_to_the_caller(scope, db_session):
    school = make_school(db_session)
    mine = make_teacher(db_session, school)
    make_teacher(db_session, school)

    rows = db_session.execute(scope.scoped_query("Teacher", mine)[0]).mappings().all()

    assert [row["id"] for row in rows] == [mine.id]


def test_a_teacher_with_no_school_sees_no_school_rather_than_all(scope, db_session):
    make_school(db_session)
    homeless = make_teacher(db_session, None)

    rows = db_session.execute(scope.scoped_query("School", homeless)[0]).mappings().all()

    assert rows == []


def test_volunteers_are_scoped_to_their_teacher(scope, db_session):
    school = make_school(db_session)
    mine = make_teacher(db_session, school)
    theirs = make_teacher(db_session, school)
    my_volunteer = make_volunteer(db_session, school, mine)
    make_volunteer(db_session, school, theirs)

    rows = db_session.execute(scope.scoped_query("Volunteer", mine)[0]).mappings().all()

    assert [row["id"] for row in rows] == [my_volunteer.id]


# ── description ──────────────────────────────────────────────────────────────


def test_describe_reports_columns_without_redacted_fields(scope):
    described = scope.describe("Learner")

    assert described["entity"] == "Learner"
    assert described["description"]
    names = {column["name"] for column in described["columns"]}
    assert "password_hash" not in names
    assert "id" in names


def test_describe_marks_foreign_keys(scope):
    columns = {c["name"]: c for c in scope.describe("Attendance")["columns"]}

    assert columns["teacher_id"]["references"] == "teachers"


def test_description_falls_back_to_the_model_docstring(scope):
    """A model with no hand-written sentence still describes itself."""

    assert scope.description_for("Question")


def test_log_classification_lists_every_model(scope):
    import logging

    class Recorder(logging.Logger):
        def __init__(self):
            super().__init__("recorder")
            self.messages = []

        def info(self, msg, *args, **kwargs):
            self.messages.append(msg % args if args else msg)

    recorder = Recorder()
    scope.log_classification(recorder)

    assert "Learner" in recorder.messages[0]
