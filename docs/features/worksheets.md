# Worksheets

Printable practice sheets — markdown or PDF — that a teacher hands to a
learner for their sessions with a volunteer.

## The library

One shared library for every school: the sheets listed in the bucket's
`content/worksheets/manifest.json` (PDFs read from the bucket's `worksheets/`:
`instance/bucket/` in dev, filled from `seed/files/` when empty, the GCS bucket
in production), plus teacher uploads, which every teacher can see. Teachers and volunteers browse it through
`<WorksheetLibrary>` (`helpers/worksheet_library.py`): search (title,
subject, topic or tag) and the subject and level filters run on the server,
results arrive in batches with "Load more"
([../ui-design/page-behaviour.md](../ui-design/page-behaviour.md)). Files are
read and written only through the storage object
([../backend/shared-services.md](../backend/shared-services.md)).

A worksheet may have a `level` (a level on the English placement scale,
1–10, ADR 0016) and `tags` (short lowercase labels). The card shows both;
the upload form sets them, optional.

## The manifest

The content folder's `worksheets/manifest.json` describes the sheets (production's lives in the bucket's `content/worksheets/`; the dev sample in `seed/files/content/worksheets/`):

```json
[{"file": "01_the.pdf", "title": "The", "subject": "English: Reading Start",
  "topic": "Sight words", "level": 2, "tags": ["sight-words", "reading"]}]
```

`file` is a bare filename: a `.pdf` in the bucket's `worksheets/`, or a `.md` beside the manifest; `title` and
`subject` are required; `topic`, `level` and `tags` are optional. Tags are
stored stripped, lowercased and without repeats.

`sync_worksheet_manifest` (`helpers/worksheet_manifest.py`) upserts one row
per entry, inserting new rows and updating changed fields. It runs from
`flask release`, from `flask sync-worksheets`, and at dev startup, each time
against the staged content folder (`helpers/content_source.py`).

- **Identity is `filepath = storage.key_for(file)`** for both types: the key
  a bucket upload uses, so a PDF row already there is updated in place. A markdown row
  stores the shipped file's text in `content` and keeps that key only as its
  identity; no blob exists for it. Renaming `file` therefore makes a new row.
- A new PDF row needs the file in the bucket's `worksheets/`; until it is
  uploaded the entry is skipped with a warning. A markdown entry whose file
  isn't beside the manifest is skipped the same way.
- It never deletes a row: assignments point at worksheets. A missing manifest
  changes nothing; a malformed one fails the whole sync and writes nothing.

## Assigning and printing

- **Assign** (`/teacher/worksheets/<id>`, to one matched pair) creates a
  `WorksheetAssignment` row; the route never returns a PDF itself. "Assign &
  print" (`then=print`) assigns, then opens that assignment's PDF in a new tab
  while the teacher stays on the worksheet; "Assign only" stays there too. The
  panel lists who already has the sheet: a repeat is allowed, but visible.
- **Print** opens the PDF in the browser's viewer (inline, not a download):
  one assignment or several as one packet, both through
  `/teacher/worksheet-assignments/print?ids=…` (at most 100, every id one of
  the teacher's learners' or the whole request is refused). A "print all
  outstanding" button only appears while the pile fits in one packet.
- **Packet builder** (`/teacher/worksheets/assign`) assigns a set of
  worksheets to several pairs and returns the merged PDF as a download in the
  same request, because reviewing the printed packet is the point.

The learner sees outstanding assignments on their dashboard and marks them
done; the teacher can also complete or reopen one, or several at once; the
volunteer sees their learner's assignments read-only. Access to an assignment
goes through its learner's teacher.

## The tracker

The Worksheets area has two tabs: **Assigned** (`/teacher/worksheets/assigned`,
`routes/teacher/worksheet_assignments.py`) and **Library**. Assigned holds every
sheet the teacher's learners have had:

- summary tiles and a per-pair table over *all* of them, whatever the filters:
  each pair's outstanding count, oldest outstanding sheet and last completion,
  with "Print N" for its whole outstanding stack. A matched pair with nothing
  outstanding is flagged and sorted first: it has nothing for its next session.
  A sheet outstanding 14 days or more counts as waiting a while.
- a paged table (25 a page) filtered by status, learner, subject, title and an
  assigned-within preset; tick rows to print them as one packet or mark them
  complete. The learner page's worksheet card is a preview linking here.

## Recommendations

Staff pages suggest worksheets for each learner's current subject and topic
(`get_recommended_worksheets` in `helpers/learning/_snapshot.py`): subject
match first, then a worksheet at the learner's level (their scale level on a
banded course, from the pair snapshot), then topic word overlap, ties by
title. The score depends on nothing but `(subject, topic, level, limit,
pool)`, so a result can be reused for every learner at the same point. Keep it that way: scoring anything
learner-specific means that key must grow, or one learner's suggestions leak
onto everyone sharing a subject and topic.

## PDFs

Printing never touches a browser or an HTML layout engine. Uploaded PDFs are
used as they are; markdown sheets are drawn straight to PDF by fpdf2
(`helpers/md_to_pdf.py`) in the bundled DejaVu Sans (`helpers/fonts/`: Latin,
Greek and Cyrillic; no CJK, and no italic, which prints upright). Every page
of every worksheet then gets the pair's names stamped in its top-right corner,
merged on with pypdf. The stamp alone is shaped (Arabic joins, right-to-left)
and falls back to Noto Sans Arabic and Ethiopic, so those names print; sheet
body text is not shaped.
