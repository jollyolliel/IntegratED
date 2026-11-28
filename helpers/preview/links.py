"""The `preview` block in a PR description, and the PR comment built from it.

````md
```preview
learner-midpath /learner/learn/subjects
teacher         /teacher/people
```
````

One `persona path` per line. The description is written by whoever opened the PR, so both parts
are matched against an allow-list before they become a link, and the app validates them again.
Standard library only: `preview.yml` runs this on the Actions runner.

As a script it reads `PR_BODY` and `PR_NUMBER` from the environment:
  python -m helpers.preview.links encode                 the links, for the PREVIEW_LINKS env var
  python -m helpers.preview.links comment <url> <sha>    the PR comment's markdown
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import sys
from urllib.parse import urlencode

from helpers.preview.personas import PERSONAS_BY_SLUG

__all__ = ["COMMENT_MARKER", "decode_links", "encode_links", "enter_path", "parse_block", "render_comment"]

#: Identifies the one comment `preview.yml` edits on every push.
COMMENT_MARKER = "<!-- integrated-preview -->"
MAX_LINES = 20

_BLOCK = re.compile(r"^```preview[ \t]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
_PATH = re.compile(r"/(?!/)[A-Za-z0-9/_.\-?=&%]{0,300}")

type Link = tuple[str, str]


def _parse_lines(lines: list[str]) -> tuple[list[Link], list[str]]:
    links: list[Link] = []
    rejected: list[str] = []
    wanted = [line.strip() for line in lines if line.strip()]
    for line in wanted[:MAX_LINES]:
        parts = line.split()
        if len(parts) == 2 and parts[0] in PERSONAS_BY_SLUG and _PATH.fullmatch(parts[1]):
            links.append((parts[0], parts[1]))
        else:
            rejected.append(line)
    if len(wanted) > MAX_LINES:
        rejected.append(f"...and {len(wanted) - MAX_LINES} more lines; only {MAX_LINES} are read")
    return links, rejected


def parse_block(body: str | None) -> tuple[list[Link], list[str]]:
    """The links in a description's first `preview` block.

    Args:
        body (str | None): The PR description.

    Returns:
        tuple[list[Link], list[str]]: `(persona, path)` links, and the lines that were refused.
    """
    match = _BLOCK.search((body or "").replace("\r\n", "\n"))
    return _parse_lines(match.group(1).split("\n")) if match else ([], [])


def encode_links(links: list[Link]) -> str:
    """Links as one env-var-safe token: no commas, spaces or quotes for gcloud to split on."""
    text = "\n".join(f"{persona} {path}" for persona, path in links)
    return base64.urlsafe_b64encode(text.encode()).decode()


def decode_links(value: str) -> list[Link]:
    """The links in `PREVIEW_LINKS`, validated again; anything unreadable is no links."""
    try:
        text = base64.urlsafe_b64decode(value.encode()).decode()
    except (binascii.Error, UnicodeError, ValueError):
        return []
    return _parse_lines(text.split("\n"))[0]


def enter_path(persona: str, path: str) -> str:
    """The link that signs in as `persona` and lands on `path`."""
    return f"/_preview/enter?{urlencode({'as': persona, 'next': path})}"


def _quoted(line: str) -> str:
    """A refused line inside a code span, where it can neither link nor mention anyone."""
    return "`" + line.replace("`", "'")[:120] + "`"


def render_comment(url: str, links: list[Link], rejected: list[str], sha: str, pr: str) -> str:
    """The sticky PR comment.

    Args:
        url (str): The preview service's URL.
        links (list[Link]): Valid `(persona, path)` lines.
        rejected (list[str]): Refused lines, listed so the author can fix them.
        sha (str): The commit deployed.
        pr (str): The PR number.

    Returns:
        str: Markdown starting with `COMMENT_MARKER`.
    """
    url = url.rstrip("/")
    intro = (
        f"**[Open the persona hub]({url}/_preview/)** - commit `{sha[:7]}`, fake data, "
        "sign in with a Google account that has preview access."
    )
    footer = (
        f"<sub>Personas: {', '.join(PERSONAS_BY_SLUG)}. "
        "The data resets on every push and after the preview has been idle.</sub>"
    )
    lines = [COMMENT_MARKER, f"### Preview for PR #{pr}", "", intro, ""]
    if links:
        lines += [f"- [{persona}: `{path}`]({url}{enter_path(persona, path)})" for persona, path in links]
    else:
        lines.append("Add a `preview` block to the description to link the pages this PR changes.")
    if rejected:
        lines += ["", "Ignored lines (expected `persona /path`):", ""]
        lines += [f"- {_quoted(line)}" for line in rejected]
    lines += ["", footer]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """See the module docstring."""
    links, rejected = parse_block(os.environ.get("PR_BODY", ""))
    if argv[:1] == ["encode"]:
        print(encode_links(links))
    elif argv[:1] == ["comment"] and len(argv) == 3:
        sys.stdout.write(render_comment(argv[1], links, rejected, argv[2], os.environ.get("PR_NUMBER", "")))
    else:
        print("usage: python -m helpers.preview.links encode | comment <url> <sha>", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
