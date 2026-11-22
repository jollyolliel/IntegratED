"""The worksheet library teachers (`/teacher/worksheets`) and volunteers (`/volunteer/resources`)
both browse: subject and level filters, a search box, and load-more batches. One module so the two
pages never drift apart on page size, ordering, search or analytics."""

from collections.abc import Iterable
from typing import Any, NamedTuple

from flask import Response, make_response, request
from sqlalchemy import String, cast, or_

from extensions import db
from helpers.analytics import capture_event
from helpers.render import render_template
from helpers.utils import wants_fragment
from models import Worksheet

# Card grids get 24 (divides by 2/3/4 for grid columns) and load more (docs/ui-design/page-behaviour.md);
# staff tables use a separate 25 (ATTENDANCE_PAGE_SIZE and friends).
WORKSHEETS_LIBRARY_PAGE_SIZE = 24
#: Worksheet levels are levels on the English placement scale, which stays at 10 or fewer
#: (docs/learning/content.md).
WORKSHEET_LEVELS = range(1, 11)
MAX_TAG_LENGTH = 40
MAX_TAGS = 10


class LibraryBatch(NamedTuple):
    worksheets: list[Worksheet]
    total: int
    page: int
    has_more: bool


def library_subjects() -> list[str]:
    """Every subject some worksheet is filed under, for the filter dropdown."""
    return [
        s for s in db.session.scalars(
            db.select(Worksheet.subject).distinct().order_by(Worksheet.subject)
        ) if s
    ]


def library_levels() -> list[int]:
    """Every level some worksheet is filed at, for the level filter."""
    return [
        level for level in db.session.scalars(
            db.select(Worksheet.level).distinct().order_by(Worksheet.level)
        ) if level is not None
    ]


def normalize_tags(tags: Iterable[str]) -> list[str]:
    """`tags` stripped and lowercased, blanks and repeats dropped, in their first order."""
    seen: list[str] = []
    for tag in tags:
        tag = tag.strip().lower()
        if tag and tag not in seen:
            seen.append(tag)
    return seen


def requested_level() -> int | None:
    """The `?level=` filter, or None when absent or not a whole number."""
    return request.args.get("level", type=int)


def requested_page() -> int:
    """Batch 1 for the full page; a load-more fetch's `?page=`, unclamped (past the end is empty)."""
    return max(1, request.args.get("page", 1, type=int)) if wants_fragment() else 1


def library_batch(subject: str, q: str, page: int, level: int | None = None) -> LibraryBatch:
    """Batch `page` of the worksheets under `subject` and at `level` (all when blank) whose title,
    subject, topic or tags contain `q` (case-insensitive; everything when blank), by subject then title."""
    stmt = db.select(Worksheet)
    if subject:
        stmt = stmt.where(Worksheet.subject == subject)
    if level is not None:
        stmt = stmt.where(Worksheet.level == level)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            Worksheet.title.ilike(like), Worksheet.subject.ilike(like), Worksheet.topic.ilike(like),
            cast(Worksheet.tags, String).ilike(like),
        ))
    total = db.session.scalar(db.select(db.func.count()).select_from(stmt.subquery())) or 0
    worksheets = db.session.scalars(
        stmt.order_by(Worksheet.subject.asc(), Worksheet.title.asc())
        .offset((page - 1) * WORKSHEETS_LIBRARY_PAGE_SIZE)
        .limit(WORKSHEETS_LIBRARY_PAGE_SIZE)
    ).all()
    return LibraryBatch(list(worksheets), total, page, page * WORKSHEETS_LIBRARY_PAGE_SIZE < total)


def track_library_view(user_id: int, page_name: str, q: str, batch: LibraryBatch, level: int | None = None,
                       **viewed_props: Any) -> None:
    """`page_viewed` (with `viewed_props`), or `worksheet_library_searched` when `q` is set — once
    per full page, never for a load-more batch. Both carry the level filter as `selected_level`."""
    if batch.page != 1:
        return
    if q:
        capture_event(str(user_id), "worksheet_library_searched", properties={
            "page": page_name, "query_length": len(q), "result_count": batch.total, "selected_level": level,
        })
    else:
        capture_event(str(user_id), "page_viewed", properties={
            "page": page_name, "selected_level": level, **viewed_props,
        })


def library_fragment(template: str, batch: LibraryBatch, **ctx: Any) -> Response:
    """The load-more reply: `template` for `batch` plus the `X-Has-More`/`X-Total-Count` headers."""
    resp = make_response(render_template(template, worksheets=batch.worksheets, **ctx))
    resp.headers["X-Has-More"] = "1" if batch.has_more else "0"
    resp.headers["X-Total-Count"] = str(batch.total)
    return resp
