from io import BytesIO
from typing import TYPE_CHECKING, cast

import pytest
from pypdf import PdfReader

if TYPE_CHECKING:
    from collections.abc import Iterable

pytestmark = pytest.mark.integration


def _payload(response) -> bytes:
    # response.response is always a bytes iterable here (a PDF body), not the
    # str-iterable half of Werkzeug's general union type; .get_data() can't be
    # used instead — these responses are direct_passthrough.
    return b"".join(cast("Iterable[bytes]", response.response))


def _assign(db_session, teacher, learner, worksheet, **overrides):
    from models import WorksheetAssignment

    assignment = WorksheetAssignment(
        teacher_id=teacher.id, learner_id=learner.id, worksheet_id=worksheet.id, **overrides
    )
    db_session.add(assignment)
    db_session.commit()
    return assignment


def _md_worksheet(db_session, content="# Hello"):
    from models import Worksheet

    worksheet = Worksheet(title="Test", subject="English", content=content, file_type="md")
    db_session.add(worksheet)
    db_session.flush()
    return worksheet


def _blank_pdf(pages=2, size=(595, 842)) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=size[0], height=size[1])
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _pdf_worksheet(db_session, monkeypatch, pdf_bytes):
    from helpers import documents
    from models import Worksheet
    from tests.support.storage import use_fake_storage

    storage = use_fake_storage(monkeypatch, targets=(documents,))
    path = storage.add_worksheet("sheet.pdf", pdf_bytes)
    worksheet = Worksheet(title="Sheet", subject="English", filepath=path, file_type="pdf")
    db_session.add(worksheet)
    db_session.flush()
    return worksheet


def test_markdown_worksheet_is_rendered_without_author_line(app, db_session):
    from helpers.documents import render_worksheet_html
    from tests.support.factories import make_worksheet

    worksheet = make_worksheet(
        db_session,
        content="# Title\n\n**Name:** hidden\n\n| A | B |\n| - | - |\n| 1 | 2 |",
    )

    with app.app_context():
        html = render_worksheet_html(worksheet)

    assert html is not None
    assert "<h1>Title</h1>" in html
    assert "hidden" not in html
    assert "<table>" in html


def test_assignment_packet_generates_a_valid_pdf_response(app, db_session, school, teacher, learner):
    from helpers.documents import generate_assignments_pdf

    assignment = _assign(db_session, teacher, learner, _md_worksheet(db_session))

    with app.test_request_context("/"):
        response = generate_assignments_pdf([assignment], "packet.pdf", double_sided=False)
        payload = _payload(response)

    assert response.mimetype == "application/pdf"
    assert payload.startswith(b"%PDF")
    assert len(PdfReader(BytesIO(payload)).pages) >= 1


def test_markdown_sheet_shows_its_content_and_the_pair_stamp_on_page_one(
    app, db_session, school, teacher, learner
):
    from helpers.documents import generate_assignments_pdf

    content = (
        "# Greetings\n\nSay *hello*.\n\n- one\n- two\n\n1. first\n\n"
        "> **For the volunteer:** mime it.\n\n"
        "| A | B |\n| - | - |\n| 1 | 2 |\n\n---\n\n```\ncode here\n```\n"
    )
    assignment = _assign(db_session, teacher, learner, _md_worksheet(db_session, content))

    with app.test_request_context("/"):
        payload = _payload(generate_assignments_pdf([assignment], "packet.pdf", double_sided=False))

    text = PdfReader(BytesIO(payload)).pages[0].extract_text()
    assert "Greetings" in text
    # Laid out, not dumped as raw markdown (the plain-text fallback would keep these).
    assert "# Greetings" not in text
    assert "**" not in text
    assert "```" not in text
    assert "mime it" in text
    assert "code here" in text
    assert (learner.name or learner.username) in text


def test_the_printed_sheet_drops_the_author_line_like_the_page_does(app, db_session, school, teacher, learner):
    from helpers.documents import generate_assignments_pdf

    worksheet = _md_worksheet(db_session, "# Colours\n\n**Name:** Ms Example\n\nRed&nbsp;and blue")
    assignment = _assign(db_session, teacher, learner, worksheet)

    with app.test_request_context():
        payload = _payload(generate_assignments_pdf([assignment], "packet.pdf", double_sided=False))
    text = PdfReader(BytesIO(payload)).pages[0].extract_text()

    assert "Ms Example" not in text
    assert "&nbsp;" not in text and "Red and blue" in text


def test_greek_text_in_names_and_body_is_printed(app, db_session, school, teacher, learner):
    from helpers.documents import generate_assignments_pdf

    learner.name = "Μαρία"
    db_session.commit()
    assignment = _assign(
        db_session, teacher, learner, _md_worksheet(db_session, "# Καλημέρα café “quoted” — dash")
    )

    with app.test_request_context("/"):
        payload = _payload(generate_assignments_pdf([assignment], "packet.pdf", double_sided=False))

    text = PdfReader(BytesIO(payload)).pages[0].extract_text()
    assert "Μαρία" in text
    assert "Καλημέρα" in text
    assert "café" in text
    assert "?" not in text


def test_every_page_of_a_packet_item_is_stamped(app, db_session, school, teacher, learner):
    from helpers.documents import generate_assignments_pdf

    body = "\n\n".join(f"Line {i} ......................." for i in range(150))
    assignment = _assign(db_session, teacher, learner, _md_worksheet(db_session, body))

    with app.test_request_context("/"):
        payload = _payload(generate_assignments_pdf([assignment], "packet.pdf", double_sided=False))

    pages = PdfReader(BytesIO(payload)).pages
    assert len(pages) > 1
    for page in pages:
        assert (learner.name or learner.username) in page.extract_text()


def test_uploaded_pdf_keeps_every_page_and_stamps_each_one(
    app, db_session, monkeypatch, school, teacher, learner
):
    from helpers.documents import generate_assignments_pdf

    worksheet = _pdf_worksheet(db_session, monkeypatch, _blank_pdf(pages=3, size=(612, 792)))
    assignment = _assign(db_session, teacher, learner, worksheet)

    with app.test_request_context("/"):
        payload = _payload(generate_assignments_pdf([assignment], "packet.pdf", double_sided=False))

    pages = PdfReader(BytesIO(payload)).pages
    assert len(pages) == 3
    assert (learner.name or learner.username) in pages[0].extract_text()
    assert all((learner.name or learner.username) in p.extract_text() for p in pages)
    assert (float(pages[0].mediabox.width), float(pages[0].mediabox.height)) == (612.0, 792.0)


def test_an_unreadable_uploaded_pdf_becomes_a_stamped_note_page_not_an_error(
    app, db_session, monkeypatch, school, teacher, learner
):
    from helpers.documents import generate_assignments_pdf

    worksheet = _pdf_worksheet(db_session, monkeypatch, b"not a pdf at all")
    assignment = _assign(db_session, teacher, learner, worksheet)

    with app.test_request_context("/"):
        payload = _payload(generate_assignments_pdf([assignment], "packet.pdf", double_sided=False))

    pages = PdfReader(BytesIO(payload)).pages
    assert len(pages) == 1
    text = pages[0].extract_text()
    assert "Sheet" in text
    assert (learner.name or learner.username) in text


def test_double_sided_inserts_a_blank_page_after_an_odd_length_learner_group(
    app, db_session, school, teacher, learner
):
    """Each learner's pages must start on a fresh sheet when the packet is
    printed duplex, so a group with an odd page count is padded to even
    before the next learner's pages begin."""
    from helpers.documents import generate_assignments_pdf
    from tests.support.factories import make_learner

    other_learner = make_learner(db_session, school, teacher)
    worksheet = _md_worksheet(db_session)
    first = _assign(db_session, teacher, learner, worksheet)
    second = _assign(db_session, teacher, other_learner, worksheet)

    with app.test_request_context("/"):
        payload = _payload(generate_assignments_pdf([first, second], "packet.pdf", double_sided=True))

    # 1 page for `first` + 1 padding blank page (odd group) + 1 page for `second`.
    assert len(PdfReader(BytesIO(payload)).pages) == 3


def test_single_sided_does_not_pad_between_learner_groups(app, db_session, school, teacher, learner):
    from helpers.documents import generate_assignments_pdf
    from tests.support.factories import make_learner

    other_learner = make_learner(db_session, school, teacher)
    worksheet = _md_worksheet(db_session)
    first = _assign(db_session, teacher, learner, worksheet)
    second = _assign(db_session, teacher, other_learner, worksheet)

    with app.test_request_context("/"):
        payload = _payload(generate_assignments_pdf([first, second], "packet.pdf", double_sided=False))

    assert len(PdfReader(BytesIO(payload)).pages) == 2


def test_a_mix_of_matched_and_unmatched_learners_does_not_crash_the_sort(
    app, db_session, school, teacher, learner, volunteer
):
    from helpers.documents import generate_assignments_pdf

    # volunteer_id is nullable: one assignment carries None, the other an int.
    matched_learner = learner
    matched_learner.volunteer_id = volunteer.id
    unmatched_learner = _make_unmatched_learner(db_session, school, teacher)
    worksheet = _md_worksheet(db_session)
    matched_assignment = _assign(db_session, teacher, matched_learner, worksheet, volunteer_id=volunteer.id)
    unmatched_assignment = _assign(db_session, teacher, unmatched_learner, worksheet, volunteer_id=None)

    with app.test_request_context("/"):
        response = generate_assignments_pdf([unmatched_assignment, matched_assignment], "packet.pdf", double_sided=False)
        _payload(response)

    assert response.mimetype == "application/pdf"


def _make_unmatched_learner(db_session, school, teacher):
    from tests.support.factories import make_learner

    return make_learner(db_session, school, teacher)
