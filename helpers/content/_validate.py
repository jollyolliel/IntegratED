"""Checking `questions.json` against the content contract (docs/learning/content.md) before any write."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise
from typing import Any

from helpers.content._schema import (
    CHOICE_TYPES,
    CONTENT_TYPES,
    PLACEMENT_CONTENT_TYPES,
    PLACEMENT_ENTRY,
    keyed_entries,
)
from helpers.learning._games import GAMES
from helpers.problems import ProblemsError

__all__ = ["ContentError", "validate_content"]

_TOPIC_KEYS = ("title", "icon", "description", "overview_markdown")
_LESSON_KEYS = ("title", "icon", "description")
_PLACEMENT_KEYS = ("subject_name", "level", "content_type", "question_prompt", "question_text", "answer")


class ContentError(ProblemsError):
    """`questions.json` breaks the content contract; nothing was written."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("questions.json", problems)


def _same(a: Any, b: Any) -> bool:
    """The graders' comparison: stripped, case-insensitive text."""
    return str(a).strip().lower() == str(b).strip().lower()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _missing(entry: dict[str, Any], keys: Iterable[str]) -> list[str]:
    return [key for key in keys if key not in entry]


def _check_question(q: Any, path: str, problems: list[str], *, in_group: bool = False) -> list[dict[str, Any]]:
    """Validate one lesson question (or a text_group of them).

    Returns:
        list[dict[str, Any]]: The real questions it stands for, for game checks.
    """
    if not isinstance(q, dict):
        problems.append(f"{path}: must be an object")
        return []
    ct = q.get("content_type")
    if ct == "text_group":
        if in_group:
            problems.append(f"{path}: a text_group cannot contain another text_group")
            return []
        children = q.get("questions")
        if not isinstance(children, list) or not children:
            problems.append(f"{path}: a text_group needs a non-empty 'questions' list")
            return []
        found = []
        for m, child in enumerate(children, 1):
            found += _check_question(child, f"{path}.{m}", problems, in_group=True)
        return found
    if ct not in CONTENT_TYPES:
        problems.append(f"{path}: unknown content_type {ct!r}")
        return []

    if ct == "match":
        pairs = q.get("match_pairs")
        if not isinstance(pairs, list) or not pairs or not all(
            isinstance(p, dict) and p.get("left") and p.get("right") for p in pairs
        ):
            problems.append(f"{path}: a match question needs match_pairs, a list of {{left, right}}")
        return [q]

    if "question_text" not in q:
        problems.append(f"{path}: missing 'question_text'")
    if ct in CHOICE_TYPES:
        options = q.get("options")
        if not isinstance(options, list) or not options:
            problems.append(f"{path}: a {ct} question needs a non-empty 'options' list")
        elif not any(_same(option, q.get("answer")) for option in options):
            problems.append(f"{path}: answer {q.get('answer')!r} is not one of its options")
    elif ct == "text_comprehension_fill_blank":
        if not q.get("fill_blank_options") and not q.get("answer"):
            problems.append(f"{path}: a fill-blank question needs fill_blank_options (accepted answers) or answer")
    elif ct == "text_comprehension_drag_drop":
        if not isinstance(q.get("fill_blank_options"), list) or not q.get("fill_blank_options"):
            problems.append(f"{path}: a drag-drop question needs fill_blank_options, the answers in blank order")
    elif ct == "text_comprehension_word_selection":
        if not q.get("word_selection_correct_words"):
            problems.append(f"{path}: a word-selection question needs word_selection_correct_words")
    elif ct == "open_answer" and not q.get("answer") and not q.get("fill_blank_options"):
        problems.append(f"{path}: an open_answer question needs answer")
    return [q]


def _check_lesson(lesson: Any, topic_path: str, index: int, problems: list[str]) -> None:
    if not isinstance(lesson, dict):
        problems.append(f"{topic_path} > lesson {index}: must be an object")
        return
    path = f"{topic_path} > {lesson.get('title', f'lesson {index}')}"
    for key in _missing(lesson, _LESSON_KEYS):
        problems.append(f"{path}: missing '{key}'")
    if "gamified" in lesson:
        # The old flag for Rocket; importing would silently make the lesson a quiz instead.
        problems.append(f"{path}: 'gamified' is no longer read; set \"game_type\": \"rocket\" instead")
    game_type = lesson.get("game_type")
    if game_type not in GAMES:
        known = ", ".join(sorted(name for name in GAMES if name))
        problems.append(f"{path}: unknown game_type {game_type!r} (known: {known})")
    questions: list[dict[str, Any]] = []
    for n, q in enumerate(lesson.get("questions") or [], 1):
        questions += _check_question(q, f"{path} > question {n}", problems)
    if game_type == "match_up" and not any(q.get("content_type") == "match" for q in questions):
        problems.append(f"{path}: a match_up lesson needs a match question")
    if game_type in GAMES and GAMES[game_type].serves == "choices" and not any(q.get("content_type") in CHOICE_TYPES for q in questions):
        problems.append(f"{path}: a {game_type} lesson needs multiple-choice questions")


def _check_course(entry: dict[str, Any], problems: list[str]) -> None:
    name = entry["name"]
    band = entry.get("placement")
    low = high = None
    if band is not None:
        if not isinstance(band, dict) or not isinstance(band.get("scale"), str) or not _is_int(
            band.get("min_level")
        ) or not _is_int(band.get("max_level")):
            problems.append(f"{name}: 'placement' must be {{\"scale\": name, \"min_level\": int, \"max_level\": int}}")
            band = None
        else:
            low, high = band["min_level"], band["max_level"]
            if low < 1:
                problems.append(f"{name}: placement min_level must be 1 or more")
            if low > high:
                problems.append(f"{name}: placement min_level {low} is above max_level {high}")
            if band["scale"] == name:
                problems.append(f"{name}: a course cannot be on a placement scale of its own name")

    topics = entry.get("topics") or []
    if band is not None and not topics:
        problems.append(f"{name}: has a placement band but no topics")
    for t_index, topic in enumerate(topics, 1):
        if not isinstance(topic, dict):
            problems.append(f"{name} > topic {t_index}: must be an object")
            continue
        title = topic.get("title", f"topic {t_index}")
        path = f"{name} > {title}"
        for key in _missing(topic, _TOPIC_KEYS):
            problems.append(f"{path}: missing '{key}'")
        level = topic.get("level")
        if level is not None and (not _is_int(level) or level < 1):
            problems.append(f"{path}: topic level must be a whole number, 1 or more")
        elif band is not None and low is not None and high is not None:
            if level is None:
                problems.append(f"{path}: a topic in a course with a placement band needs an explicit level")
            elif not low <= level <= high:
                problems.append(f"{path}: topic level {level} is outside the course's band {low}-{high}")
        for l_index, lesson in enumerate(topic.get("lessons") or [], 1):
            _check_lesson(lesson, path, l_index, problems)


def _check_placement_entry(entry: dict[str, Any], levels_by_scale: dict[str, set[int]], problems: list[str]) -> None:
    for n, q in enumerate(entry.get("questions") or [], 1):
        path = f"{PLACEMENT_ENTRY} > question {n}"
        if not isinstance(q, dict):
            problems.append(f"{path}: must be an object")
            continue
        missing = _missing(q, _PLACEMENT_KEYS)
        for key in missing:
            problems.append(f"{path}: missing '{key}'")
        if "subject_name" in missing or "level" in missing:
            continue
        if not _is_int(q["level"]) or q["level"] < 1:
            problems.append(f"{path}: level must be a whole number, 1 or more")
            continue
        levels_by_scale.setdefault(q["subject_name"], set()).add(q["level"])
        ct = q.get("content_type")
        if ct not in PLACEMENT_CONTENT_TYPES:
            problems.append(
                f"{path}: content_type {ct!r} — placement questions must be multiple_choice or open_answer"
            )
        elif ct == "multiple_choice":
            options = q.get("options")
            if not isinstance(options, list) or not options:
                problems.append(f"{path}: a multiple_choice question needs a non-empty 'options' list")
            elif not any(_same(option, q.get("answer")) for option in options):
                problems.append(f"{path}: answer {q.get('answer')!r} is not one of its options")
        if q.get("audio_only"):
            if ct != "multiple_choice":
                problems.append(f"{path}: audio_only only works on multiple_choice questions")
            if not q.get("question_sound"):
                problems.append(f"{path}: audio_only needs question_sound: true, or there is nothing to hear")


def _check_bands(courses: dict[str, dict[str, Any]], levels_by_scale: dict[str, set[int]], problems: list[str]) -> None:
    by_scale: dict[str, list[tuple[str, int, int]]] = {}
    for name, entry in courses.items():
        band = entry.get("placement")
        if isinstance(band, dict) and isinstance(band.get("scale"), str) and _is_int(
            band.get("min_level")
        ) and _is_int(band.get("max_level")):
            by_scale.setdefault(band["scale"], []).append((name, band["min_level"], band["max_level"]))

    for scale, bands in by_scale.items():
        if scale not in levels_by_scale:
            for name, _low, _high in bands:
                problems.append(f"{name}: there are no placement questions for scale '{scale}' in {PLACEMENT_ENTRY}")
            continue
        if scale in courses:
            problems.append(f"'{scale}' is a placement scale with courses on it, so it cannot also be a course")
        top = max(levels_by_scale[scale])
        for name, _low, high in bands:
            if high > top:
                problems.append(f"{name}: placement scale '{scale}' only goes up to level {top}, not {high}")
        ordered = sorted(bands, key=lambda b: (b[1], b[2]))
        for (a, a_low, a_high), (b, b_low, b_high) in pairwise(ordered):
            if b_low <= a_high:
                problems.append(f"{a} and {b}: placement bands {a_low}-{a_high} and {b_low}-{b_high} overlap")
        for level in range(1, top + 1):
            if not any(low <= level <= high for _name, low, high in bands):
                problems.append(f"level {level} of placement scale '{scale}' is in no course's band")


def _check_unique_keys(data: list[Any], problems: list[str]) -> None:
    """Report every natural key the file uses twice; the second copy would silently overwrite the first."""
    seen: set[tuple[Any, ...]] = set()
    for key, where in keyed_entries(data):
        if key in seen:
            problems.append(f"{where}: appears twice; the second would overwrite the first")
        seen.add(key)


def validate_content(data: Any) -> list[str]:
    """Every way `data` breaks the content contract in docs/learning/content.md.

    Args:
        data (Any): The parsed `questions.json`.

    Returns:
        list[str]: Problems, each naming where it is; empty when the file is valid.
    """
    if not isinstance(data, list):
        return ["the file must be a JSON list of subject entries"]
    problems: list[str] = []
    courses: dict[str, dict[str, Any]] = {}
    levels_by_scale: dict[str, set[int]] = {}
    for index, entry in enumerate(data, 1):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"]:
            problems.append(f"entry {index}: missing 'name'")
            continue
        if entry["name"] == PLACEMENT_ENTRY:
            _check_placement_entry(entry, levels_by_scale, problems)
            continue
        if entry["name"] in courses:
            problems.append(f"{entry['name']}: appears twice in the file")
            continue
        courses[entry["name"]] = entry
        _check_course(entry, problems)

    if not problems:
        _check_unique_keys(data, problems)
    for scale, levels in levels_by_scale.items():
        for level in range(1, max(levels) + 1):
            if level not in levels:
                problems.append(f"placement scale '{scale}': no placement questions at level {level}")
    _check_bands(courses, levels_by_scale, problems)
    return problems
