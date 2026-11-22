from __future__ import annotations

import re
from io import BytesIO
from typing import TYPE_CHECKING, Any

import markdown
from flask import Response, send_file

if TYPE_CHECKING:
    from pypdf import PdfReader

    from helpers.storage import Bucket
    from models import Worksheet, WorksheetAssignment

from helpers.analytics import capture_event
from helpers.utils import get_pair_display_name

__all__ = ["generate_assignments_pdf", "render_worksheet_html", "worksheet_markdown"]


def _is_pdf_worksheet(worksheet: Worksheet) -> bool:
    """Whether a worksheet is an uploaded PDF (vs. markdown).

    Args:
        worksheet (Worksheet): The worksheet to check.

    Returns:
        bool: True if `file_type == "pdf"`.
    """
    return getattr(worksheet, "file_type", "md") == "pdf"


def _load_worksheet_markdown(worksheet: Worksheet) -> str:
    """Reads raw markdown from either the DB content field or the associated file path.

    Args:
        worksheet (Worksheet): The worksheet to load content for.

    Returns:
        str: Raw markdown, or "" for a PDF worksheet / missing/unsafe file.
    """
    if _is_pdf_worksheet(worksheet):
        return ""
    if worksheet.content:
        return worksheet.content
    if not worksheet.filepath:
        return ""
    from helpers.storage import get_bucket
    storage = get_bucket()
    if not storage.is_safe_path(worksheet.filepath):
        return ""
    if not storage.exists(worksheet.filepath):
        return ""
    return storage.read_text(worksheet.filepath)


def worksheet_markdown(worksheet: Worksheet) -> str:
    """A markdown worksheet as both the page and the printed sheet show it.

    The authored file's `**Name:**` line goes (the pair's names are stamped on instead) and
    `&nbsp;` becomes a plain space.

    Args:
        worksheet (Worksheet): The worksheet.

    Returns:
        str: The markdown to render, "" for a PDF worksheet or a missing file.
    """
    content = _load_worksheet_markdown(worksheet).replace("&nbsp;", " ")
    return re.sub(r"(?im)^\*\*Name:\*\*.*$", "", content)


def render_worksheet_html(worksheet: Worksheet) -> str | None:
    """Converts a worksheet's markdown into HTML. Returns None for PDF worksheets.

    Args:
        worksheet (Worksheet): The worksheet to render.

    Returns:
        str | None: Rendered HTML, or None if the worksheet is a PDF.
    """
    if _is_pdf_worksheet(worksheet):
        return None
    return markdown.markdown(worksheet_markdown(worksheet), extensions=["fenced_code", "tables"])


def _load_pdf_worksheet(ws: Worksheet, storage: Bucket) -> PdfReader | None:
    """Loads an uploaded PDF worksheet's page reader, or None if it can't be read.

    Args:
        ws (Worksheet): The PDF worksheet.
        storage (Bucket): The app's storage.

    Returns:
        pypdf.PdfReader | None: Reader for the worksheet's PDF, or None on failure.
    """
    from pypdf import PdfReader

    if not ws.filepath or not storage.exists(ws.filepath):
        return None
    try:
        worksheet_bytes = storage.read_bytes(ws.filepath)
        reader = PdfReader(BytesIO(worksheet_bytes))
        if not reader.pages:
            return None
        return reader
    except Exception:  # noqa: BLE001 - an uploaded PDF can be malformed in any way pypdf's parser rejects, and the storage backend (local or GCS) can fail its own ways; one unreadable worksheet must not break the whole packet
        return None


def _sheet_pages(ws: Worksheet, storage: Bucket) -> list[Any]:
    """Builds one worksheet's pages (unstamped; the caller stamps each once it is on the writer).

    Markdown sheets are rendered to PDF in memory; uploaded PDFs are used as
    they are; an unreadable PDF becomes a one-page note so the pair still
    gets a sheet saying what is missing.

    Args:
        ws (Worksheet): The assigned worksheet.
        storage (Bucket): The app's storage.

    Returns:
        list[Any]: The `pypdf` page objects, at least one.
    """
    from pypdf import PdfReader

    from helpers.md_to_pdf import markdown_to_pdf_bytes, note_page_bytes

    if _is_pdf_worksheet(ws):
        reader = _load_pdf_worksheet(ws, storage)
        if reader is None:
            note = note_page_bytes(
                ws.title, "This worksheet's PDF file could not be read. Ask your teacher for a fresh copy."
            )
            reader = PdfReader(BytesIO(note))
    else:
        reader = PdfReader(BytesIO(markdown_to_pdf_bytes(worksheet_markdown(ws), ws.title)))

    return list(reader.pages)


def generate_assignments_pdf(
    assignments: list[WorksheetAssignment], download_name: str, double_sided: bool, *, inline: bool = False
) -> Response:
    """Generates a PDF packet from a list of worksheet assignments (the pair's names are stamped onto every page).

    Args:
        assignments (list[WorksheetAssignment]): Assignments to include in the packet.
        download_name (str): Filename offered to the browser.
        double_sided (bool): When True, inserts a blank page after each
            learner's group of pages if that group's page count is odd, so
            each pair's packet starts on a fresh sheet when printed duplex.
        inline (bool): Serve the PDF inline, for the browser's viewer.

    Returns:
        Response: A Flask file response for the merged PDF.
    """
    from pypdf import PdfWriter

    from helpers.md_to_pdf import stamp_page
    from helpers.storage import get_bucket

    assignments.sort(key=lambda x: (x.volunteer_id is None, x.volunteer_id, x.learner_id))

    printable = [a for a in assignments if a.worksheet and a.learner]
    storage = get_bucket()
    writer = PdfWriter()
    previous_learner_id = None
    pages_since_group_start = 0

    for assignment in printable:

        if double_sided:
            learner_id = assignment.learner_id
            if previous_learner_id != learner_id and previous_learner_id is not None:
                if pages_since_group_start % 2:
                    writer.add_blank_page()
                pages_since_group_start = 0
            previous_learner_id = learner_id

        pair_name = get_pair_display_name(assignment.learner, assignment.pair_volunteer)
        for page in _sheet_pages(assignment.worksheet, storage):
            stamp_page(writer.add_page(page), pair_name)
            pages_since_group_start += 1

    output = BytesIO()
    writer.write(output)
    output.seek(0)
    capture_event(
        None,
        "worksheet_packet_generated",
        properties={"assignment_count": len(printable), "download_name": download_name},
    )
    return send_file(
        output,
        mimetype="application/pdf",
        download_name=download_name,
        as_attachment=not inline,
    )
