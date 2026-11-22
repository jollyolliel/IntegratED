# Staff features — start here

The tools teachers, school admins and administrators use around the learning
itself. Read the file for the feature you're touching.

| Feature | Read | Code |
|---|---|---|
| Volunteer–learner matching: Auto-Match, priorities, capacity, match scores | [matching.md](matching.md) | `helpers/matching.py`, `routes/api/matching.py`, `routes/teacher/matching.py`, `helpers/teacher_ops/_matching.py` |
| Worksheets: library, assigning, printing, the assigned tracker, recommendations | [worksheets.md](worksheets.md) | `routes/teacher/worksheets.py`, `routes/teacher/worksheet_assignments.py`, `helpers/worksheet_library.py`, `helpers/documents.py`, `helpers/learning/_snapshot.py` |
| Teacher AI assistant | [ai-assistant.md](ai-assistant.md) | `helpers/ai/`, `routes/assistant/`, `templates/components/assistant_panel.jx` |

Smaller features need no file of their own:

- **Attendance** — teachers log one register per day for their roster
  (`routes/teacher/attendance.py` → `helpers/teacher_ops/_attendance.py`).
  The record model and the hours rule: [../backend/data-model.md](../backend/data-model.md).
  The register's UI traps: [../ui-design/page-stylesheets.md](../ui-design/page-stylesheets.md) (`admin.css`).
- **Donations** — Stripe Checkout from `/donations`, recorded by the signed
  webhook (`routes/base/_donations.py`); see the data-model note on how a
  donation finds its school.
- **CMS** — administrators edit site text, team members and articles
  (`routes/administrator/cms.py`); this content is authored, not translated.
- **"What's new" popups** — [../ui-design/page-behaviour.md](../ui-design/page-behaviour.md).
