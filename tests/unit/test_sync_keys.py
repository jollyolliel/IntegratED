"""scripts/sync_keys.py --audit must see t() keys in `.jx` templates as well as `.html` ones."""

import pytest

from scripts.sync_keys import scan_template_keys

pytestmark = pytest.mark.unit


def test_scan_template_keys_reads_jx_and_html(tmp_path):
    (tmp_path / "old.html").write_text("<p>{{ t('html.key') }}</p>", encoding="utf-8")
    (tmp_path / "page.jx").write_text(
        "{#def #}\n<Button label={{ t('jx.prop') }} />\n<h1>{{ t(\"jx.text\") }}</h1>\n",
        encoding="utf-8",
    )
    (tmp_path / "notes.txt").write_text("{{ t('ignored.key') }}", encoding="utf-8")

    assert scan_template_keys(str(tmp_path)) == {"html.key", "jx.prop", "jx.text"}


def test_scan_template_keys_ignores_t_outside_jinja(tmp_path):
    (tmp_path / "page.jx").write_text("<p>t('plain.text')</p>", encoding="utf-8")

    assert scan_template_keys(str(tmp_path)) == set()
