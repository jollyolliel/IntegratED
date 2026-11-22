# Backend — start here

Read this before adding or changing a route, a model, a helper, or anything
that decides who may see what.

The app is one Flask monolith: `main.py`'s `create_app()` wires extensions,
blueprints, request hooks and error handlers; routes live in `routes/`,
domain logic in `helpers/`, the schema in `models.py` (people, schools,
attendance, worksheets, money, content, assistant) and `models_learning.py`
(subjects → topics → lessons → questions, learning sessions).

## Which file for which task

| You are… | Read |
|---|---|
| Adding a route or endpoint | [access-control.md](access-control.md), then [shared-services.md](shared-services.md) |
| Changing who can see or do something; anything with roles, schools, invite codes, login | [access-control.md](access-control.md) |
| Changing `models.py` / `models_learning.py`, writing a migration, a query over people or attendance | [data-model.md](data-model.md) |
| Writing a mutation, sending analytics, storing a file, returning JSON vs HTML, dates | [shared-services.md](shared-services.md) |
| Touching startup, error pages, caching, rate limits, or chasing a "starting up" page | [request-lifecycle.md](request-lifecycle.md) |

Feature-specific backends: learning in [../learning/](../learning/README.md),
matching / worksheets / AI assistant in
[../features/](../features/README.md). Python conventions and tests:
[../development/](../development/README.md).

## Where a URL lives

| Prefix | Package | |
|---|---|---|
| `/` (login, register, OAuth) | `routes/auth/` | no prefix — `/login`, `/register`, `/authorize`… |
| `/` (public, settings, donations, `/dev/*`) | `routes/base/` | |
| `/learner` | `routes/learner/` | dashboard, survey, map test, learning path, game pages, worksheets |
| `/api` | `routes/api/` | JSON for the learner's quiz/games/placement test, plus Auto-Match |
| `/teacher` | `routes/teacher/` | dashboard + people, attendance, worksheets, matching settings |
| `/volunteer` | `routes/volunteer.py` | |
| `/school` | `routes/school_admin.py` | |
| `/admin` | `routes/administrator/` | prefix set where the blueprint is registered |
| `/assistant` | `routes/assistant/` | teacher AI assistant |

Each package's `__init__.py` creates the blueprint and imports its modules at
the bottom so their routes register. `grep -n "_bp.route" routes/<pkg>/*.py`
lists a blueprint's routes.
