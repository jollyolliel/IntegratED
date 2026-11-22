# Access control — roles, gates and scoping

Who may see and change what. The data includes refugee minors, so a route
that leaks one teacher's roster to another is the worst bug this app can
ship. Read before adding any route.

## The five roles

All accounts are `User` rows, specialised by joined-table inheritance into
`Learner`, `Volunteer`, `Teacher`, `SchoolAdmin` and `Administrator`
(`user_type` is the discriminator). Learners, school admins and
administrators sign in with a username and password; volunteers and teachers
with Google only — they hold no username or password, so the password form
never finds them.

- **Learner** — belongs to one teacher, optionally matched to one volunteer.
- **Volunteer** — may hold several learners up to their capacity.
- **Teacher** — owns a roster of learners and volunteers.
- **SchoolAdmin** — one school's people, donations and settings.
- **Administrator** — everything, across schools.

## How a request is gated

| Area | Gate |
|---|---|
| `/teacher`, `/volunteer`, `/learner`, `/school`, `/assistant` | the blueprint's `before_request` requires login and the right `user_type` (403 otherwise) — every route in it is covered |
| `/admin` | **no blueprint hook**: every route carries `@login_required` and `@admin_required` itself |
| `/api` | learner routes sit in the nested `learner_api` blueprint, whose `before_request` signs in, checks the learner role and the onboarding gate; the rest carry `@login_required` and check `current_user.user_type` in their body (teacher for matching) |
| auth, public | open |

Onboarding gates sit on top, both on `Learner.onboarding_step`: the learner
blueprint's `before_request` (`routes/learner/__init__.py`) sends a learner to
the survey, then to `/map-intro`, until both are done, onboarding's own pages
(`ONBOARDING_ENDPOINTS`) excepted. The learner `/api` blueprint applies the same
gate as JSON (`routes/api/__init__.py`), answering 403 `onboarding_incomplete`;
the placement test's own calls (`PLACEMENT_ENDPOINTS`) need only the survey.

`tests/web/test_authorization.py` checks every registered URL against a
**hand-written** policy keyed by URL prefix and asserts anonymous users and
every other role are refused. A new route under an existing prefix is checked
automatically; a new public route, or one whose roles differ from its prefix
(the teacher-only `/api/matching/*`), needs an entry there.

## Scoping: the row, not just the role

Passing the role gate only says *what kind* of user this is. Every route that
takes an id must also prove the row belongs to them:

- **Teacher → their own roster, not their school.** People belong to a
  teacher through `teacher_id`; two teachers at one school can't see each
  other's learners. Check `row.teacher_id == teacher.id` (abort 403/404), or
  go through `helpers/teacher_ops`, whose `_owned()` refuses anything not on
  the teacher's roster.
  - An attendance row's `teacher_id` is who *logged* it.
  - A worksheet assignment is reached through its learner's `teacher_id`.
- **SchoolAdmin → their school.** Query with
  `filter_by(id=…, school_id=current_user.school.id)` and 404 otherwise. They
  manage learners and volunteers, not teachers or matches.
- **Administrator → unscoped**, including a raw database console and
  impersonation.
- **Worksheets are a shared library** across all schools by design; an upload
  is visible to every teacher.
- **The AI assistant** derives its own read scope from the foreign-key graph
  and fails closed — [../features/ai-assistant.md](../features/ai-assistant.md).

## Joining the programme

- **Invite codes** are one per **school** (6 characters), stored on the
  school row and created the first time a teacher loads their dashboard. They
  never expire or rotate on their own; only a teacher's Regenerate replaces
  the code, invalidating the old one for every teacher at that school.
- A learner registers with a code and arrives with no teacher; the next
  teacher at that school to load their dashboard claims them.
- A volunteer registers with a code through Google; they are attached to a
  teacher at that school.
- Google sign-in picks the role from the email domain against each school's
  `volunteer_domain` / `teacher_domain`.
- Usernames are unique only within each table, and login tries Learner,
  Administrator, SchoolAdmin, Teacher, Volunteer in that order. **Any code
  that creates or renames a username-based account checks `username_taken()`**
  (`helpers/auth_utils.py`, all five tables), or the account can never sign in.
- Password strength is enforced at registration and in settings; passwords
  set by staff for a learner skip it.
- Whitespace around a username or password is never part of it: every place
  one is set or entered passes it through `clean_credential()`, and a typed
  password is checked with `password_matches()`, which also accepts the exact
  text for a password saved before trimming (issue #176).
- A new username or password may not contain any space (`has_whitespace()`,
  checked by register, settings, and the staff and teacher reset forms). Login
  stays lenient so a password saved with a space before this rule still signs in.

## Sessions and impersonation

Values kept in the browser session, set in different places:

| Key | Set by | Holds |
|---|---|---|
| `ui_lang` | `/set-language` | interface language |
| `pending_invite_code` | volunteer sign-up | code carried through the Google round-trip |
| `impersonating_admin_id` | `/admin/impersonate/<id>` | the admin to return to |

An administrator can impersonate any non-admin (POST); the header shows a
banner and a way back while `impersonating_admin_id` is set. A successful
sign-in of any kind clears it (`auth_utils.sign_in`, the one place every flow
signs a user in); a failed one leaves it, so the admin can still return. Analytics during
impersonation are attributed to the impersonated user.

## Request forgery

There are **no CSRF tokens** in this app. Two layers stand in: the session
cookie is set `SameSite=Lax` (`main.py`), and `refuse_cross_site_writes`
answers 403 to any POST/PUT/PATCH/DELETE whose `Origin` (or, failing that,
`Referer`) names another host, or is `Origin: null` (`is_cross_site_write` in
`helpers/utils.py`). A write with neither header passes — that is a
non-browser client such as the Stripe webhook. Both hold only while every
state-changing route is a **POST**: new routes never change state on GET (a
few existing ones — logout, the dashboard's roster claim and first invite code
— are known debt, not a pattern). Redirect targets taken from the request
(`next=`, the referrer) go through `safe_local_path` / `same_site_referrer_path`.

## Rate limits

Default 300/min per address; blueprints set their own (most 120/min, `/api`
60/min, `/assistant` and auth POSTs 20/min, login/register/invite checks
10/min). Storage is per-process memory. Tests switch limiting off; the
`rate_limits_on` fixture turns it back on.

## Dev sign-in

`/dev/login-as?type=<user_type>&next=/path` signs in as a ready-made user of
that role (created on first use, onboarding complete). It only answers on a
development server from localhost.

`&survey=0|1` and `&map_test=0|1|deferred` set the learner's (survey: also
volunteer's) onboarding state before sign-in, on an existing user too — use
them to test first-run flows. `map_test=0|deferred` also clears placement
levels.

`next` is the **full URL path, blueprint prefix included** — it is a plain
redirect, not a route name. Role pages live under their role's prefix
(table above): the learner map is `/learner/map`, not `/map`; a teacher's
roster is under `/teacher/…`. A bare `/map` 404s. Omit `next` to land on the
role's dashboard, and find a page's real path with
`grep -rn "route(" routes/<role>/`.

To try the Google sign-in and registration rules themselves (domain matching,
invite codes, the `gmail.com` teacher) as any address, use the Google button:
on a development server from localhost, `/login/google` opens
`/dev/google-sign-in` instead of Google. The email typed there goes through the
same account logic as Google's `/authorize` callback, keeping the session's
pending invite code, so it needs no Google credentials. The *New teacher* and
*New volunteer* buttons there make a fresh account in one click: an email on
the first school's teacher or volunteer domain (a `gmail.com` teacher if no
school has one), plus a name; the volunteer preset stashes that school's invite
code first. When Google credentials are set, a *Sign in with real Google* button
(`/login/google?real=1`) runs the real OAuth round trip; `/authorize` 404s without
credentials. Same guard as `/dev/login-as` (`is_local_dev_request`).

## New route checklist

1. It sits under the right prefix, or carries the gate decorators / in-body
   role check its blueprint needs.
2. Every id in the URL or form is resolved through an ownership check.
3. Changes state → POST, AJAX-ready ([../ui-design/page-behaviour.md](../ui-design/page-behaviour.md)).
4. The authorization matrix passes; add a policy entry if the route is public
   or an exception to its prefix.
5. It captures a PostHog event if it is a meaningful user action
   ([shared-services.md](shared-services.md)).
