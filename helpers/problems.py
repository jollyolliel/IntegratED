"""The error a file validator raises: every problem it found, each naming where it is.

`questions.json` (helpers/content/), the worksheet manifest (helpers/worksheet_manifest.py) and
`seed.toml` (helpers/seed/) are each checked whole before anything is written, so their errors
share one shape: the file, and the list of problems.
"""

__all__ = ["ProblemsError"]


class ProblemsError(ValueError):
    """`source` breaks its format; nothing was written."""

    def __init__(self, source: str, problems: list[str]) -> None:
        self.source = source
        self.problems = problems
        super().__init__(f"{source} has {len(problems)} problem(s):\n  - " + "\n  - ".join(problems))
