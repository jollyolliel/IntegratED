import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.web


def test_english_translation_file_is_valid_and_non_empty():
    path = Path("translations/en.json")
    values = json.loads(path.read_text(encoding="utf-8"))

    assert values
    def non_empty(value):
        if isinstance(value, dict):
            return all(non_empty(child) for child in value.values())
        return isinstance(value, str) and bool(value.strip())

    assert non_empty(values)


@pytest.mark.parametrize(
    "path", [path for path in sorted(Path("translations").glob("*.json")) if path.name != "needs_translation.json"]
)
def test_each_translation_file_has_the_english_key_set(path):
    english = json.loads(Path("translations/en.json").read_text(encoding="utf-8"))
    translated = json.loads(path.read_text(encoding="utf-8"))

    assert set(translated) >= set(english), path.name
