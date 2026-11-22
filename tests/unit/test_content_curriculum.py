"""The full proprietary curriculum, kept in the bucket's `content/` folder, not in git.

Set `CURRICULUM_DIR` to a local copy to run these (docs/learning/content.md): `questions.json` and
`worksheets/` (manifest, markdown sheets and the PDFs). Without it they skip, because the repo
ships only a small dev sample. These read the real files (test_content_import.py tests the importer on small
made-up ones). The map they hold the content to is
`.claude/docs/specs/07-english-curriculum.md`; the contract is
docs/learning/content.md.
"""

import json
import os
import re
from collections import Counter
from pathlib import Path

import pytest

from helpers.content import (
    CHOICE_TYPES,
    CONTENT_TYPES,
    PLACEMENT_ENTRY,
    validate_content,
)

ROOT = Path(__file__).resolve().parents[2]
_CURRICULUM = os.environ.get("CURRICULUM_DIR")
CONTENT = Path(_CURRICULUM) if _CURRICULUM else ROOT / "seed" / "files" / "content"
WORKSHEETS = CONTENT / "worksheets"

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(not _CURRICULUM, reason="set CURRICULUM_DIR to the full content copy from the bucket"),
]

SCALE = "English"
COURSES = {
    "English: First Steps": (1, 2),
    "English: Reading Start": (3, 5),
    "English: Everyday": (6, 7),
    "English: Sentences & Grammar": (8, 10),
}
RETIRED = {"English Grammar", "Phonics for Reading — Second Level"}
PLACEMENT_MINIMUM = {1: 12, 2: 8}  # every higher level: 6
GAMES = {"rocket", "word_storm", "match_up", "garden_grow", "potion_workshop"}
CHOICE_GAMES = GAMES - {"match_up"}
TYPES = {
    "multiple_choice", "text_comprehension_fill_blank", "text_comprehension_drag_drop",
    "text_comprehension_word_selection", "text_comprehension_multiple_choice",
    "text_comprehension_read_word", "vocabulary_audio", "open_answer", "match", "text_group",
}

# ── what must never be assumed about a learner ───────────────────────────────

COUNTRIES = (
    "Afghanistan|Albania|Algeria|Angola|Argentina|Armenia|Australia|Austria|Azerbaijan|Bangladesh|"
    "Belarus|Belgium|Benin|Bolivia|Bosnia|Brazil|Bulgaria|Burkina Faso|Burundi|Cambodia|Cameroon|"
    "Canada|Chad|Chile|China|Colombia|Congo|Croatia|Cuba|Cyprus|Czechia|Denmark|Djibouti|"
    "Dominican Republic|Ecuador|Egypt|El Salvador|Eritrea|Estonia|Ethiopia|Finland|France|Gabon|"
    "Gambia|Georgia|Germany|Ghana|Greece|Guatemala|Guinea|Haiti|Honduras|Hungary|India|Indonesia|"
    "Iran|Iraq|Ireland|Israel|Italy|Ivory Coast|Jamaica|Japan|Jordan|Kazakhstan|Kenya|Korea|Kosovo|"
    "Kurdistan|Kuwait|Kyrgyzstan|Laos|Latvia|Lebanon|Liberia|Libya|Lithuania|Madagascar|Malawi|"
    "Malaysia|Mali|Mauritania|Mexico|Moldova|Mongolia|Morocco|Mozambique|Myanmar|Nepal|Netherlands|"
    "Nicaragua|Niger|Nigeria|North Macedonia|Norway|Oman|Pakistan|Palestine|Panama|Paraguay|Peru|"
    "Philippines|Poland|Portugal|Qatar|Romania|Russia|Rwanda|Saudi Arabia|Senegal|Serbia|"
    "Sierra Leone|Somalia|South Africa|South Sudan|Spain|Sri Lanka|Sudan|Sweden|Switzerland|Syria|"
    "Tajikistan|Tanzania|Thailand|Togo|Tunisia|Turkey|Turkmenistan|Uganda|Ukraine|"
    "United Arab Emirates|United Kingdom|United States|Uzbekistan|Venezuela|Vietnam|Yemen|Zambia|"
    "Zimbabwe|England|Scotland|Wales|America|Africa|Asia|Europe"
)
BANNED = [
    re.compile(rf"\bfrom\s+(?:the\s+)?(?:{COUNTRIES})\b", re.IGNORECASE),
    re.compile(r"\bwhere\s+(?:are|do)\s+you\s+(?:come\s+)?from\b", re.IGNORECASE),
    re.compile(r"\byour\s+(?:home\s+)?country\b", re.IGNORECASE),
    re.compile(r"\bhome\s+country\b", re.IGNORECASE),
    re.compile(r"\bhome\b", re.IGNORECASE),
    re.compile(r"\byour\s+(?:family|mother|father|mum|mom|dad|parents?|brothers?|sisters?)\b", re.IGNORECASE),
    re.compile(r"\brefugees?\b", re.IGNORECASE),
    re.compile(r"\bwars?\b", re.IGNORECASE),
    re.compile(r"\bnationality\b", re.IGNORECASE),
]

# Emoji and pictographs: a text-to-speech voice reads each one aloud by name.
EMOJI = re.compile("[←-⇿⌀-⏿①-➿⬀-⯿\U0001f000-\U0001faff️]")


def _data():
    return json.loads((CONTENT / "questions.json").read_text(encoding="utf-8"))


def _manifest():
    return json.loads((WORKSHEETS / "manifest.json").read_text(encoding="utf-8"))


def _courses():
    return [entry for entry in _data() if entry["name"] != PLACEMENT_ENTRY]


def _placement():
    return next(entry for entry in _data() if entry["name"] == PLACEMENT_ENTRY)["questions"]


def _flat(questions):
    """Lesson questions with text_groups unwrapped; each child carries the group's context."""
    for q in questions:
        if q.get("content_type") == "text_group":
            for child in q["questions"]:
                yield {"context_text": q.get("context_text"), "context_image": q.get("context_image"), **child}
        else:
            yield q


def _lessons():
    for course in _courses():
        for topic in course["topics"]:
            for lesson in topic["lessons"]:
                yield course, topic, lesson


def _where(course, topic, lesson=None):
    return " > ".join(x for x in (course["name"], topic["title"], lesson and lesson["title"]) if x)


def _texts():
    """Every piece of content text, with where it is."""
    for course in _courses():
        yield course["name"], course["name"] + " " + course["description"]
        for topic in course["topics"]:
            yield _where(course, topic), " ".join((topic["title"], topic["description"], topic["overview_markdown"]))
            for lesson in topic["lessons"]:
                where = _where(course, topic, lesson)
                yield where, " ".join(
                    (lesson["title"], lesson["description"], lesson.get("overview_markdown") or "")
                )
                for q in lesson["questions"]:
                    yield where, json.dumps(q, ensure_ascii=False)
    for n, q in enumerate(_placement(), 1):
        yield f"placement question {n}", json.dumps(q, ensure_ascii=False)
    for entry in _manifest():
        yield f"manifest {entry['file']}", entry["title"] + " " + " ".join(entry["tags"])
    for path in sorted(WORKSHEETS.glob("*.md")):
        yield path.name, path.read_text(encoding="utf-8")


def _bare_icon(icon):
    """Templates render `fas fa-{{ icon }}`, so an icon is a bare Font Awesome name."""
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", icon or "")) and not icon.startswith("fa-")


def _topics_by_course():
    return {course["name"]: {topic["title"]: topic for topic in course["topics"]} for course in _courses()}


# ── the file and the scale ───────────────────────────────────────────────────


def test_the_file_passes_the_importers_validation():
    assert validate_content(_data()) == []


def test_four_english_courses_split_one_scale_and_the_old_subjects_are_gone():
    bands = {
        c["name"]: (c["placement"]["scale"], c["placement"]["min_level"], c["placement"]["max_level"])
        for c in _courses()
    }
    assert bands == {name: (SCALE, low, high) for name, (low, high) in COURSES.items()}
    assert not RETIRED & {entry["name"] for entry in _data()}
    assert all("English" in name and len(name) <= 50 for name in bands)


def test_every_placement_level_has_its_minimum_and_a_spare():
    counts = Counter(q["level"] for q in _placement() if q["subject_name"] == SCALE)
    assert {q["subject_name"] for q in _placement()} == {SCALE}
    assert sorted(counts) == list(range(1, 11))
    for level, count in counts.items():
        assert count >= PLACEMENT_MINIMUM.get(level, 6) + 2, f"level {level} has {count}"


def test_placement_questions_are_choice_or_open_and_unique():
    keys = [(q["level"], q["question_text"]) for q in _placement()]
    assert len(keys) == len(set(keys))
    assert {q["content_type"] for q in _placement()} <= {"multiple_choice", "open_answer"}


def test_a_placement_question_that_says_listen_is_audio_only():
    for q in _placement():
        if q["question_prompt"].lower().startswith("listen"):
            assert q.get("audio_only") is True, q["question_text"]
            assert q.get("question_sound") is True, q["question_text"]


def test_the_lowest_placement_levels_need_no_reading():
    """Levels 1 and 2 are heard, and answered by tapping a picture or a single letter."""
    for q in _placement():
        if q["level"] > 2:
            continue
        assert q["content_type"] == "multiple_choice", q["question_text"]
        assert q.get("question_sound") is True, q["question_text"]
        assert q.get("audio_only") is True, q["question_text"]  # a learner who can't read hears it, sees no words
        for option in q["options"]:
            assert EMOJI.search(option) or re.fullmatch(r"[A-Za-z0-9]", option), (q["question_text"], option)


# ── shape of courses, topics and lessons ─────────────────────────────────────


def test_topic_levels_climb_through_the_band_and_every_level_has_a_topic():
    for course in _courses():
        low, high = COURSES[course["name"]]
        levels = [topic["level"] for topic in course["topics"]]
        assert levels == sorted(levels), course["name"]
        assert set(levels) == set(range(low, high + 1)), course["name"]


def test_every_topic_teaches_and_has_three_or_more_lessons():
    for course in _courses():
        assert len(course["topics"]) >= 5, course["name"]
        for topic in course["topics"]:
            assert len(topic["lessons"]) >= 3, _where(course, topic)
            assert len(topic["overview_markdown"]) >= 150, _where(course, topic)
            assert _bare_icon(topic["icon"]), topic["icon"]


def test_every_lesson_teaches_before_it_asks():
    for course, topic, lesson in _lessons():
        where = _where(course, topic, lesson)
        assert len(lesson.get("overview_markdown") or "") >= 60, where
        assert len(list(_flat(lesson["questions"]))) >= 3 or lesson["game_type"] == "match_up", where
        assert _bare_icon(lesson["icon"]), where


def test_natural_keys_are_unique_so_nothing_merges_on_import():
    for course in _courses():
        assert len({t["title"] for t in course["topics"]}) == len(course["topics"]), course["name"]
        for topic in course["topics"]:
            assert len({lesson["title"] for lesson in topic["lessons"]}) == len(topic["lessons"])
    for course, topic, lesson in _lessons():
        questions = list(_flat(lesson["questions"]))
        texts = [q["question_text"] for q in questions if q["content_type"] != "match"]
        prompts = [q.get("question_prompt", "Match") for q in questions if q["content_type"] == "match"]
        assert len(texts) == len(set(texts)), _where(course, topic, lesson)
        assert len(prompts) == len(set(prompts)), _where(course, topic, lesson)


def test_every_course_uses_the_quiz_every_game_and_every_question_type():
    for course in _courses():
        lessons = [lesson for topic in course["topics"] for lesson in topic["lessons"]]
        assert {lesson["game_type"] for lesson in lessons} == GAMES | {None}, course["name"]
        types = {q["content_type"] for lesson in lessons for q in lesson["questions"]}
        types |= {q["content_type"] for lesson in lessons for q in _flat(lesson["questions"])}
        assert types >= TYPES, (course["name"], TYPES - types)
    assert TYPES - {"text_group"} <= CONTENT_TYPES


def test_games_get_the_questions_they_can_show():
    for course, topic, lesson in _lessons():
        where = _where(course, topic, lesson)
        questions = list(_flat(lesson["questions"]))
        game = lesson["game_type"]
        if game == "match_up":
            assert len(questions) == 1 and questions[0]["content_type"] == "match", where
            pairs = questions[0]["match_pairs"]
            assert 4 <= len(pairs) <= 8, where
            assert len({p["left"] for p in pairs}) == len({p["right"] for p in pairs}) == len(pairs), where
        elif game in CHOICE_GAMES:
            assert all(q["content_type"] in CHOICE_TYPES for q in questions), where
            assert len(questions) >= 4, where
            for q in questions:
                for option in q["options"]:
                    assert len(option.split()) <= 3 and len(option) <= 24, (where, option)
            if game == "potion_workshop":
                assert len(questions) in (4, 6), where


def test_each_question_type_carries_what_its_screen_needs():
    for course, topic, lesson in _lessons():
        where = _where(course, topic, lesson)
        for q in _flat(lesson["questions"]):
            ct, text = q["content_type"], q.get("question_text", "")
            if ct in CHOICE_TYPES:
                assert 2 <= len(q["options"]) <= 4 and len(set(q["options"])) == len(q["options"]), (where, text)
            if ct == "text_comprehension_fill_blank":
                assert text.count("{input}") == 1, (where, text)
            if ct == "text_comprehension_drag_drop":
                assert text.count("{input}") == len(q["fill_blank_options"]), (where, text)
                assert set(q["fill_blank_options"]) <= set(q["word_bank"]), (where, text)
                assert len(q["word_bank"]) > len(set(q["fill_blank_options"])), (where, "needs a decoy")
            if ct == "text_comprehension_word_selection":
                context = re.findall(r"[\w'-]+", (q.get("context_text") or "").lower())
                assert context, (where, "word selection needs a context_text to tap in")
                assert all(w.lower() in context for w in q["word_selection_correct_words"]), (where, text)
            if ct == "text_comprehension_read_word":
                assert q.get("options") == ["I read it"], (where, text)
            if ct == "vocabulary_audio":
                assert len(q["word_bank"]) >= 3, (where, text)
            if ct == "text_comprehension_multiple_choice":
                assert q.get("context_text"), (where, "a comprehension question needs its passage")
            if ct != "match":
                assert "{input}" not in text or ct in {"text_comprehension_fill_blank", "text_comprehension_drag_drop"}


def test_sounded_text_is_plain_words_for_the_voice():
    sounded = [(f"placement L{q['level']}", q) for q in _placement() if q.get("question_sound")]
    sounded += [(_where(c, t, lesson), q) for c, t, lesson in _lessons() for q in _flat(lesson["questions"])]
    for where, q in sounded:
        if q.get("question_sound"):
            assert not EMOJI.search(q["question_text"]), (where, q["question_text"])
            assert not re.search(r"[/_{}]", q["question_text"]), (where, q["question_text"])
        if q.get("option_sound"):
            assert all(not EMOJI.search(option) for option in q["options"]), (where, q["options"])


def test_low_level_lessons_can_be_heard():
    """First Steps and the first Reading Start level are for learners who may not read yet."""
    for course, topic, lesson in _lessons():
        if topic["level"] > 3:
            continue
        for q in _flat(lesson["questions"]):
            if q["content_type"] in ("multiple_choice", "open_answer") and topic["level"] <= 2:
                assert q.get("question_sound") is True, (_where(course, topic, lesson), q["question_text"])


def test_referenced_images_exist():
    for course, topic, lesson in _lessons():
        for q in lesson["questions"]:
            image = q.get("context_image")
            if image:
                assert image.startswith("/static/") and (ROOT / image.lstrip("/")).is_file(), image


def test_nothing_assumes_a_learners_past():
    for where, text in _texts():
        for pattern in BANNED:
            match = pattern.search(text)
            assert not match, f"{where}: {match.group(0)!r}"


# ── worksheets ───────────────────────────────────────────────────────────────


def test_manifest_entries_have_exactly_the_agreed_shape():
    topics = _topics_by_course()
    for entry in _manifest():
        assert list(entry) == ["file", "title", "subject", "topic", "level", "tags"], entry
        assert (WORKSHEETS / entry["file"]).is_file(), entry["file"]
        assert entry["subject"] in topics, entry
        assert entry["topic"] in topics[entry["subject"]], entry
        low, high = COURSES[entry["subject"]]
        assert isinstance(entry["level"], int) and low <= entry["level"] <= high, entry
        assert entry["tags"] and all(re.fullmatch(r"[a-z][a-z-]*", tag) for tag in entry["tags"]), entry
        assert entry["title"].strip(), entry


def test_every_worksheet_file_is_listed_once():
    files = [entry["file"] for entry in _manifest()]
    assert len(files) == len(set(files))
    on_disk = {p.name for p in WORKSHEETS.iterdir() if p.suffix.lower() in (".pdf", ".md")}
    assert on_disk == set(files)
    sight_words = ["the", "and", "here", "for", "see", "come", "make", "not", "can", "find",
                   "they", "what", "was", "but", "with", "been", "had", "from", "then", "does"]
    assert {f"{n:02d}_{w}.pdf" for n, w in enumerate(sight_words, 1)} <= on_disk


def test_every_topic_has_a_worksheet_and_its_own_markdown_one():
    listed = {(e["subject"], e["topic"]) for e in _manifest()}
    markdown = {(e["subject"], e["topic"]) for e in _manifest() if e["file"].endswith(".md")}
    for course, titles in _topics_by_course().items():
        for title in titles:
            assert (course, title) in listed, (course, title)
            assert (course, title) in markdown, (course, title)


def test_markdown_worksheets_open_with_a_title_and_a_teaching_box():
    for path in sorted(WORKSHEETS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# "), path.name
        assert "\n> **For the volunteer" in text, path.name
        assert not EMOJI.search(text), f"{path.name}: the PDF font has no emoji or arrows"
        assert len(text.splitlines()) <= 90, f"{path.name}: keep a printed worksheet short"
