"""The shape of `questions.json`: its content types, and the natural keys the importer matches by.

One walk over the file (`keyed_entries`) names every keyed entry, so the duplicate check
(`_validate.py`) and the prune (`_prune.py`) agree on what a key is; the upsert looks rows up by the
same keys (`question_key`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CHOICE_TYPES",
    "CONTENT_TYPES",
    "PLACEMENT_CONTENT_TYPES",
    "PLACEMENT_ENTRY",
    "FileKeys",
    "file_keys",
    "keyed_entries",
    "lesson_questions",
    "load_content",
    "question_key",
]

#: The top-level entry whose questions are placement questions, not a course.
PLACEMENT_ENTRY = "Map Test"

#: Choice types: the learner picks one of `options`; graded by exact match on `answer`.
CHOICE_TYPES = frozenset({
    "multiple_choice",
    "text_comprehension_multiple_choice",
    "text_comprehension_picture",
    "text_comprehension_image_selection",
})
#: Every question `content_type` the quiz, the games and their grader
#: (`grade` in helpers/learning/_validators.py) know. `text_group` is an
#: import-only wrapper and is not stored.
CONTENT_TYPES = CHOICE_TYPES | {
    "text_comprehension_fill_blank",
    "text_comprehension_drag_drop",
    "text_comprehension_word_selection",
    "text_comprehension_read_word",
    "vocabulary_audio",
    "open_answer",
    "match",
}
#: What the placement page can show (routes/api/map_test.py sends options for these only).
PLACEMENT_CONTENT_TYPES = frozenset({"multiple_choice", "open_answer"})


def load_content(path: str) -> list[Any]:
    """The parsed content file.

    Args:
        path (str): The `questions.json` to read, normally in the staged content folder.

    Returns:
        list[Any]: The JSON list of subject entries.
    """
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def question_key(q: Any) -> tuple[str, str]:
    """A question's key within its lesson (a match by its prompt, any other by its text), from a dict or row."""
    get = q.get if isinstance(q, dict) else lambda key, default=None: getattr(q, key, default)
    if get("content_type") == "match":
        return ("match", get("question_prompt", "Match") or "Match")
    return ("text", get("question_text", "") or "")


def lesson_questions(lesson: dict[str, Any]) -> Iterator[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Each real question of a lesson with the `text_group` it sits in (None outside one), in order."""
    for q in lesson.get("questions", []):
        if q.get("content_type") == "text_group":
            for child in q.get("questions", []):
                yield child, q
        else:
            yield q, None


def keyed_entries(data: list[Any]) -> Iterator[tuple[tuple[Any, ...], str]]:
    """Every topic, lesson, question and placement question in a validated-shape file, as
    `(natural key, where it is)`. The key's first item names its kind."""
    for entry in data:
        if entry["name"] == PLACEMENT_ENTRY:
            for q in entry.get("questions", []):
                yield (("map", q["subject_name"], q["level"], q["question_text"]),
                       f"Map Test: '{q['question_text']}' ({q['subject_name']} level {q['level']})")
            continue
        subject = entry["name"]
        for topic in entry.get("topics", []):
            yield ("topic", subject, topic["title"]), f"{subject} > {topic['title']}"
            for lesson in topic.get("lessons", []):
                where = f"{subject} > {topic['title']} > {lesson['title']}"
                yield ("lesson", subject, topic["title"], lesson["title"]), where
                for q, _group in lesson_questions(lesson):
                    kind, key = question_key(q)
                    label = f"match question '{key}'" if kind == "match" else f"question '{key}'"
                    yield ("question", subject, topic["title"], lesson["title"], kind, key), f"{where}: {label}"


@dataclass
class FileKeys:
    """The natural keys of everything in the file, by kind (each without its kind tag)."""

    subjects: set[str] = field(default_factory=set)
    topics: set[tuple[str, str]] = field(default_factory=set)
    lessons: set[tuple[str, str, str]] = field(default_factory=set)
    questions: set[tuple[str, str, str, str, str]] = field(default_factory=set)
    map_questions: set[tuple[str, int, str]] = field(default_factory=set)


def file_keys(data: list[Any]) -> FileKeys:
    """`keyed_entries` gathered by kind, plus every subject name (courses and placement scales)."""
    keys = FileKeys()
    by_kind: dict[str, set[Any]] = {
        "topic": keys.topics, "lesson": keys.lessons, "question": keys.questions, "map": keys.map_questions,
    }
    for key, _where in keyed_entries(data):
        by_kind[key[0]].add(key[1:])
    keys.subjects = {entry["name"] for entry in data if entry["name"] != PLACEMENT_ENTRY}
    keys.subjects |= {scale for scale, _level, _text in keys.map_questions}
    return keys
