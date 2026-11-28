"""The `preview` block in a PR description: which persona lands on which page. The body is
written by whoever opened the PR, so every line is validated before it becomes a link."""

import pytest

from helpers.preview.links import (
    decode_links,
    encode_links,
    parse_block,
    render_comment,
)

pytestmark = pytest.mark.unit

BODY = """\
## What changed
Matching is faster.

```preview
learner-midpath /learner/quiz
teacher         /teacher/matching?tab=auto&x=%20
```
"""


def test_valid_lines_become_links():
    links, rejected = parse_block(BODY)
    assert links == [("learner-midpath", "/learner/quiz"), ("teacher", "/teacher/matching?tab=auto&x=%20")]
    assert rejected == []


def test_windows_line_endings_and_blank_lines_are_fine():
    links, rejected = parse_block("```preview\r\n\r\nteacher /teacher/\r\n```\r\n")
    assert links == [("teacher", "/teacher/")]
    assert rejected == []


@pytest.mark.parametrize("body", ["", None, "no block here", "```python\nteacher /teacher/\n```"])
def test_a_description_without_a_block_has_no_links(body):
    assert parse_block(body) == ([], [])


@pytest.mark.parametrize(
    "line",
    [
        "stranger /teacher/",
        "TEACHER /teacher/",
        "teacher teacher/matching",
        "teacher //evil.example",
        "teacher https://evil.example",
        "teacher /a b",
        "teacher /a)[click](https://evil.example",
        "teacher /<script>",
        "teacher /a\\b",
        "teacher",
    ],
)
def test_a_bad_line_is_rejected_and_listed(line):
    links, rejected = parse_block(f"```preview\n{line}\n```")
    assert links == []
    assert len(rejected) == 1


def test_the_number_of_lines_is_capped():
    body = "```preview\n" + "teacher /teacher/\n" * 200 + "```"
    links, rejected = parse_block(body)
    assert len(links) + len(rejected) <= 21


def test_links_survive_the_trip_through_an_env_var():
    links = [("teacher", "/teacher/matching?a=1&b=2")]
    encoded = encode_links(links)
    assert "," not in encoded and " " not in encoded
    assert decode_links(encoded) == links


@pytest.mark.parametrize("value", ["", "not base64!!", "////"])
def test_a_broken_env_var_decodes_to_no_links(value):
    assert decode_links(value) == []


def test_decoding_validates_again():
    assert decode_links(encode_links([("teacher", "//evil.example")])) == []


def test_the_comment_links_each_page_through_the_sign_in_route():
    comment = render_comment("https://pr-7.example.run.app", [("teacher", "/teacher/matching?a=1&b=2")], [], "abc1234def", "7")
    assert comment.startswith("<!-- integrated-preview -->")
    assert "https://pr-7.example.run.app/_preview/enter?as=teacher&next=%2Fteacher%2Fmatching%3Fa%3D1%26b%3D2" in comment
    assert "https://pr-7.example.run.app/_preview/" in comment
    assert "abc1234" in comment


def test_the_comment_without_links_still_links_the_hub():
    comment = render_comment("https://x.run.app", [], [], "abc1234", "7")
    assert "https://x.run.app/_preview/" in comment
    assert "/_preview/enter" not in comment


def test_a_rejected_line_cannot_inject_markdown_or_mentions():
    _, rejected = parse_block("```preview\n`@everyone` [x](https://evil.example) <img>\n```")
    comment = render_comment("https://x.run.app", [], rejected, "abc", "1")
    quoted = next(line for line in comment.splitlines() if "@everyone" in line)
    assert quoted.count("`") == 2 and quoted.index("`") < quoted.index("@everyone")
    assert quoted.rindex("`") > quoted.index("<img>")
