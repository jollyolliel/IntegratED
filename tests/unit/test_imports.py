import json

import pytest

pytestmark = pytest.mark.unit


def test_question_import_preserves_fill_blank_subtext(app, isolated_database, tmp_path, monkeypatch):
    from helpers import content

    source = tmp_path / "questions.json"
    source.write_text(
        json.dumps(
            [
                    {
                        "name": "English Grammar",
                        "description": "Grammar",
                        "icon": "fa-book",
                        "topics": [
                            {
                                "title": "Basics",
                                "icon": "fa-star",
                                "level": 1,
                                "description": "Basics",
                                "overview_markdown": "# Basics",
                                "lessons": [
                                    {
                                        "title": "Fill blank",
                                        "description": "Lesson",
                                        "icon": "fa-book",
                                        "questions": [
                                            {
                                                "content_type": "text_comprehension_fill_blank",
                                                "question_prompt": "Fill",
                                                "question_subtext": "Use the word",
                                                "question_text": "I ___ here",
                                                "answer": "am",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
            ]
        ),
        encoding="utf-8",
    )
    content.import_questions(isolated_database, str(source))

    from models import Question

    question = isolated_database.session.scalars(isolated_database.select(Question)).one()
    assert question.question_subtext == "Use the word"
