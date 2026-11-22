# Python conventions

What `ruff` and `ty` enforce, what the end-of-turn hook enforces, and the
conventions they can't. Run both on every Python change, as CI does:
`uv run ruff check .` and `uv run ty check`.

## Enforced by tooling

- **Banned imports** (ruff `TID251`): `flask_login.current_user` → use
  `helpers/current_user.py`; `flask.render_template` → use
  `helpers/render.py`. Each ban's message says where to go.
- **ty checks every platform** (`python-platform = "all"`), so a
  `# ty: ignore[...]` inside a `sys.platform` branch must be needed on all of
  them, or CI reports it unused even when Windows is clean.
- **Docstrings** (end-of-turn hook): a docstring longer than a third of its
  function, or one that argues *why* ("instead of", "rather than",
  "workaround", "we decided"), is flagged. A docstring says what the function
  does; the reasoning goes in a comment beside the code it explains, or an
  ADR in `docs/adr/` when it is a real decision.

## Types

- Annotate with real model types, not `Any`, whenever the model is known.
  `Any` is the last resort.
- A module that needs a model only for annotations imports it under
  `if TYPE_CHECKING:` with `from __future__ import annotations` at the top,
  and writes the annotation bare. That avoids the circular imports between
  `models.py`, helpers and routes. A runtime use such as `cast("Teacher", x)`
  still quotes the name.
- A function returning a dict with a fixed set of keys returns a
  **`TypedDict`**, so a renamed key is a type error at every caller.
  `dict[str, Any]` is only for genuinely dynamic keys (columns of an
  arbitrary table, a diff of whatever changed). Keys like `from` need the
  functional form: `X = TypedDict("X", {"from": str})`.
- **Trap**: a dict literal satisfies a `TypedDict` only when written at the
  call site. Bound to a variable first, it infers as a plain `dict` — annotate
  the variable (`pairs: list[MatchEntity] = [...]`).
- Model columns: `Mapped[...]` on `db.Column(...)`, nullability stated
  honestly — [../backend/data-model.md](../backend/data-model.md).

## Style the tools don't check

- Write complete code; a stub or `TODO` left behind is called out when the
  work is handed back.
- Comments are sparse and explain the non-obvious; match the density of the
  surrounding file.
- `except Exception` carries a `# noqa: BLE001 - <why any failure is fine
  here>` comment, as in `main.py`.
- Scripts run as `uv run scripts/<name>.py` and carry no shebang.
