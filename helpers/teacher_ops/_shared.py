from datetime import date as date_cls
from datetime import datetime
from typing import Any, Protocol

from extensions import db
from models import Teacher

# Upper bound on learners per volunteer. Y2Y sessions are one-on-one time split
# across the week — beyond this the volunteer can't give anyone real attention.
MAX_VOLUNTEER_CAPACITY = 5


class _OwnedByTeacher(Protocol):
    """Structural shape `_owned` needs — matched by `Learner`/`Volunteer`."""
    teacher_id: int | None


def _owned[T: _OwnedByTeacher](model: type[T], row_id: int, teacher: Teacher, what: str) -> T:
    """Fetch a row by id and confirm it belongs to `teacher`.

    Args:
        model (type[T]): SQLAlchemy model class to query.
        row_id (int): Primary key to look up.
        teacher (Teacher): Owning teacher to check against.
        what (str): Human-readable row name, for error messages.

    Returns:
        T: The row, once ownership is confirmed.
    """
    row = db.session.get(model, row_id)
    if row is None:
        raise LookupError(f"No {what} with id {row_id}.")
    if row.teacher_id != teacher.id:
        raise PermissionError(f"That {what} belongs to another teacher.")
    return row


def _coerce_date(value: Any) -> date_cls:
    """'YYYY-MM-DD' | date | datetime -> date. Raises ValueError otherwise.

    Args:
        value (Any): Date-like value to coerce.

    Returns:
        date: The coerced date.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_cls):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (AttributeError, TypeError, ValueError):
        raise ValueError("Enter a valid session date.")


def _coerce_bool(value: Any) -> bool:
    """bool | 'present'/'absent' | 'true'/'false' | '1'/'0' -> bool, so callers never have to pre-convert.

    Args:
        value (Any): Bool-like value to coerce.

    Returns:
        bool: The coerced value.
    """
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "present", "yes"):
        return True
    if text in ("false", "0", "absent", "no"):
        return False
    raise ValueError("is_present must be true or false.")
