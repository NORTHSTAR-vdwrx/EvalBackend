# NORTHSTAR Eval: API Schema (draft v1)

Backend: Python + FastAPI. Database: PostgreSQL (see `schema.sql`).
All URLs start with `/api`. Authenticated requests use the HTTP-only `session` cookie.
Send JSON request bodies with `Content-Type: application/json`. Use UUIDs for all
`{id}` path values.

## Implemented endpoints

| Method | URL | Access | Purpose |
|---|---|---|---|
| POST | `/api/auth/create` | anyone | Create a student account |
| POST | `/api/auth/login` | anyone | Log in with email and password |
| POST | `/api/auth/logout` | anyone | End the current session |
| GET | `/api/auth/me` | signed in | Get the current account |
| GET, PUT, PATCH | `/api/extended-users/me` | signed in | Read, create/replace, or edit the current extended profile |
| GET | `/api/extended-users?limit={n}&offset={n}` | administrator | List all extended user profiles |
| GET, PUT, PATCH, DELETE | `/api/extended-users/{user_id}` | administrator | Read or manage any user's extended profile |
| GET, POST | `/api/admin/users` | administrator | List users or create an account with an assigned role |
| GET, PATCH, DELETE | `/api/admin/users/{user_id}` | administrator | Read or manage any account |
| GET | `/api/institutes` | anyone | List institutes |
| GET | `/api/institutes/{id}` | anyone | Get one institute |
| POST, PATCH, DELETE | `/api/institutes[/{id}]` | administrator | Manage institutes |
| GET | `/api/groups?created_by_me={true\|false}` | signed in | List groups visible in the user's institute or groups they created |
| GET | `/api/groups/students?search={term}&limit={n}` | teacher | Search students with profiles in the teacher's institute |
| POST | `/api/groups` | teacher / administrator | Create an institute-scoped group |
| GET, PATCH, DELETE | `/api/groups/{id}` | visible group / group owner / administrator | Read or manage a group |
| GET | `/api/groups/{id}/members` | group owner/member / administrator | List group members |
| POST | `/api/groups/{id}/members` | group owner | Add a student |
| POST | `/api/groups/{id}/join` | student | Join a public group in the same institute |
| DELETE | `/api/groups/{id}/members/me` | signed in | Leave a group |
| DELETE | `/api/groups/{id}/members/{user_id}` | group owner | Remove a student |
| GET | `/api/quizzes` | signed in | List accessible quizzes |
| POST | `/api/quizzes` | teacher / administrator | Create a quiz |
| GET, PATCH, DELETE | `/api/quizzes/{id}` | accessible quiz / owner | Read or manage a quiz |
| PUT | `/api/quizzes/{id}/groups` | quiz owner | Replace the quiz's assigned groups |
| GET, PUT | `/api/quizzes/{id}/sections` | quiz owner / administrator | Read or replace quiz sections and question order |
| PUT, DELETE | `/api/quizzes/{id}/accommodations/{student_id}` | quiz owner / administrator | Set or remove student accommodations |
| GET | `/api/quizzes/{id}/questions` | quiz owner / administrator | List questions, including answer keys |
| POST | `/api/quizzes/{id}/questions` | quiz owner / administrator | Add a question |
| PUT, DELETE | `/api/questions/{id}` | question owner / administrator | Replace or delete a question |
| GET | `/api/questions/{id}/versions` | question owner / administrator | List saved prior versions |
| GET, PUT | `/api/questions/{id}/rubric` | question owner / administrator | Read or replace a question's manual-grading rubric |
| POST | `/api/questions/{id}/regrade` | question owner / administrator | Re-score submitted attempts using the current answer key |
| GET, POST | `/api/question-banks` | teacher / administrator | List accessible banks or create one |
| DELETE | `/api/question-banks/{id}` | bank owner / administrator | Delete a bank and its items |
| GET, POST | `/api/question-banks/{id}/questions` | bank reader / owner | Search/list or add reusable bank questions |
| PUT, DELETE | `/api/question-bank-items/{id}` | bank owner / administrator | Version, update, or delete a bank item |
| GET | `/api/question-bank-items/{id}/versions` | bank reader / owner | List bank-item versions |
| POST | `/api/quizzes/{id}/question-pools` | quiz owner / administrator | Pull random questions from a bank by tags/difficulty |
| GET | `/api/quizzes/{id}/questions/export?format=csv\|json\|qti` | quiz owner / administrator | Export questions |
| POST | `/api/quizzes/{id}/questions/import` | quiz owner / administrator | Import CSV/JSON/QTI questions |
| GET | `/api/sessions` | signed in | List accessible scheduled exams |
| POST | `/api/sessions` | teacher / administrator | Schedule an exam |
| GET, PATCH, DELETE | `/api/sessions/{id}` | accessible session / owner | Read or manage a session |
| POST | `/api/sessions/{id}/attempt` | assigned student / administrator | Start an attempt or resume an active attempt |
| GET | `/api/sessions/{id}/my-result` | student | Get the configured latest/best/average result |
| GET | `/api/sessions/{id}/analytics` | quiz owner / administrator | Get auto-gradable item and distractor analysis |
| GET | `/api/students/me/performance?days=365` | student | Chart personal score, subject, skill, standard, and question-type performance |
| GET | `/api/attempts/mine` | student | List the student's attempts |
| GET | `/api/admin/attempts?limit={n}&offset={n}` | administrator | List every student's attempts |
| GET | `/api/sessions/{id}/attempts?limit={n}&offset={n}` | quiz owner / administrator | List attempts for a scheduled exam, including student identity and attempt number |
| GET | `/api/attempts/{id}` | attempt owner / quiz owner / administrator | Reload an attempt and saved answers |
| PUT | `/api/attempts/{id}/answers/{question_id}` | attempt owner / administrator | Save/replace one answer |
| PATCH | `/api/attempts/{id}/log` | attempt owner / administrator | Save the attempt's formatted text log |
| POST, GET | `/api/attempts/{id}/activity` | attempt owner / quiz owner / administrator | Record or review activity flags |
| PUT | `/api/attempts/{id}/grades/{question_id}` | quiz owner / administrator | Manually grade an essay, code, or short answer |
| POST | `/api/attempts/{id}/submit` | attempt owner / administrator | Submit and close the attempt |

Teachers can combine the session-attempt list with the memberships of the quiz's
assigned groups to see every student, including students who have not started.
Session-attempt entries include `student_id`, `student_name`, `student_email`,
and `attempt_number`. Submitted responses can be reviewed and manually graded
with the question rubric; rubric criterion scores are included in the grader
feedback alongside the total awarded points.

`GET /api/groups?created_by_me=true` lists groups created by the signed-in user.
Group responses include `created_at`, `creating_teacher`, `created_by_username`,
and `member_count`. Institutes can only be created, updated, or deleted by
administrators. Teachers create groups in their profile institute; administrators
must send `institute_id` when creating a group. Public groups are discoverable
only by users whose profile belongs to that same institute. Administrators can
create accounts with any role and read or manage any account, profile, group,
quiz, question, scheduled exam, and attempt, including listing all attempts.
Starting an attempt remains a student-only operation so attempts are recorded
against the actual student's identity. Administrators cannot remove or delete
their own administrator account.

Teachers can search students in their own institute with
`GET /api/groups/students?search={term}&limit=30`. Search terms must contain at
least two characters and match the student's display name, username, email, or
institute member number. Results never include students from other institutes.

Run `python init_db.py` to initialize the database from `schema.sql`. This script
drops and recreates the schema, so it deletes all existing records.

## Request and response details

### Login

`POST /api/auth/login` takes an email address (case-insensitive) and password.
The response contains the public user; a seven-day HTTP-only `session` cookie is
set for subsequent requests.

```json
{ "email": "student@example.edu", "password": "your-password" }
```

### Extended user profile

`GET /api/extended-users/me` returns 404 until a profile exists.
`PUT /api/extended-users/me` creates or replaces the signed-in user's profile;
`PATCH` updates only the fields supplied. `institute_id` must exist. New accounts
should create this profile after choosing an institute.

```json
{
  "acc_name": "A Student",
  "institute_id": "4e2f6cc0-42dd-4b79-97ae-2f22579cfe4c",
  "institute_member_number": "S-1042",
  "phone": "+1-555-0100",
  "timezone": "America/New_York"
}
```

### Administrator account management

`GET /api/admin/users?limit=100&offset=0` lists all user accounts, including
`id` and `user_id` (the same UUID), display `name`, `username`, email, role,
creation time, and available extended-profile/institute details. The profile
fields are `null` until an extended profile is created. `GET
/api/admin/users/{user_id}` returns the same fields for one account. To create
an account, send a username, email, password, and role (`student`, `teacher`,
or `administrator`) to `POST /api/admin/users`:

```json
{
  "username": "newteacher",
  "email": "teacher@example.edu",
  "password": "a-long-password",
  "role": "teacher"
}
```

`PATCH /api/admin/users/{user_id}` accepts one or more of `username`, `email`,
and `role`. `DELETE /api/admin/users/{user_id}` deletes that account and its
cascading sessions, profile, and group memberships.

Authenticated user objects now expose both `id` and `user_id` with the same UUID,
so clients can display a clearly named user ID on their signed-in pages without
breaking existing clients using `id`. This repository contains API routes but no
frontend home-page files; the client should render `user_id` from login or
`GET /api/auth/me`.

### Institutes

`GET /api/institutes` returns the institute list. Administrators use
`POST /api/institutes` with `{ "institute_name": "Northstar University" }`.
`PATCH /api/institutes/{id}` takes the same field; `DELETE` has no body. A
referenced institute cannot be deleted.

### Groups

Teachers create a group in their profile institute; administrators choose one
explicitly. `is_public` makes the group visible/joinable to users in that
institute only.

```json
{
  "group_name": "Biology 101",
  "is_public": true,
  "institute_id": "4e2f6cc0-42dd-4b79-97ae-2f22579cfe4c"
}
```

For teachers, `institute_id` is omitted/ignored and taken from their profile.
Group updates accept `group_name` and/or `is_public`. Owners or administrators
can add a same-institute student with `{ "user_id": "<student-uuid>" }`; students
can join a public same-institute group with `POST /api/groups/{id}/join`.
`DELETE /api/groups/{id}/members/me` leaves a group.

### Quizzes and questions

Create a quiz with `{ "title": "Biology 101", "duration_minutes": 45 }`.
`PATCH /api/quizzes/{id}` accepts either field. Assign groups by replacing the
list with `PUT /api/quizzes/{id}/groups`:

```json
{ "group_ids": ["4e2f6cc0-42dd-4b79-97ae-2f22579cfe4c"] }
```

Create questions using `POST /api/quizzes/{id}/questions`. Supported
`question_type` values are `single_choice`, `multiple_choice`, `true_false`,
`short_answer`, `numeric`, `fill_blank`, `matching`, `ordering`, `hotspot`,
`drag_drop`, `code`, and `long_answer`. Questions support points, question and
option media URLs (image/audio/video/diagram), per-option feedback, general
feedback, a worked solution, partial-credit rules, tags, difficulty (1-5),
curriculum standard code, Bloom's level, and a folder path. Media is referenced
by URL; the API does not upload files.

Single-correct MCQ (`single_choice`) requires at least two options and exactly
one `is_correct: true`:

```json
{
  "question_text": "Which is a mammal?",
  "question_type": "single_choice",
  "options": [
    { "option_text": "Whale", "is_correct": true },
    { "option_text": "Trout", "is_correct": false }
  ],
  "image_url": "https://cdn.example.edu/questions/whale.png"
}
```

Multiple-correct MCQ (`multiple_choice`) requires at least two options and at
least one correct option. `true_false` requires two options and one correct
option. `short_answer` and `fill_blank` accept text and use `accepted_answers`
for automatic case/whitespace-configurable matching. `numeric` uses
`answer_config.correct_value`, optional `tolerance`, and optional `unit`.
`matching`, `ordering`, `hotspot`, and `drag_drop` use a client-defined
`interaction_config` and server-side `answer_config`; hotspot coordinates are
checked within a configured tolerance. `long_answer` supports a rubric and
manual grading. `code` submissions are stored and manually graded; this API
does not execute submitted code.

Question text and option text can include parameters. Define finite numeric
ranges and steps in `parameter_config`; the server chooses and snapshots a
variant for each attempt. Numeric parameterized items use a restricted
arithmetic `answer_config.correct_value_expression` (variable names, numbers,
`+`, `-`, `*`, `/`, `//`, `%`, `**`, and unary signs; exponent magnitude is
limited). No Python code is evaluated.

```json
{
  "question_text": "Name two states of water.",
  "question_type": "multiple_choice",
  "options": [
    { "option_text": "Liquid", "is_correct": true },
    { "option_text": "Gas", "is_correct": true },
    { "option_text": "Metal", "is_correct": false }
  ]
}
```

```json
{
  "question_text": "The chemical symbol for water is ___.",
  "question_type": "fill_blank",
  "accepted_answers": ["H2O", "h₂o"]
}
```

For numeric, media, feedback, or parameterized items, the relevant fields look
like this:

```json
{
  "question_text": "What is {a} + {b}?",
  "question_type": "numeric",
  "answer_config": {
    "correct_value_expression": "a + b",
    "tolerance": 0
  },
  "parameter_config": {
    "a": { "minimum": 1, "maximum": 10, "step": 1 },
    "b": { "minimum": 1, "maximum": 10, "step": 1 }
  },
  "media": [
    { "media_type": "diagram", "url": "https://cdn.example.edu/triangle.svg", "alt_text": "A triangle" }
  ],
  "partial_credit": { "all_or_nothing": false, "per_correct_option": 0.5 }
}
```

`PUT /api/questions/{id}` replaces the full question including its option list;
`DELETE` removes it. Staff question responses include correctness and accepted
answers; never use those responses in a student view. The student attempt
response includes interaction settings and question/option media but omits
answer keys, correctness, feedback, and worked solutions until grading.

### Question banks and quiz structure

Teachers can create institute-shared banks (read-only to other teachers in the
same institute); only the bank owner or an administrator can edit them.
Administrators can create institute or private banks. Bank question bodies use
the same fields as `QuestionWrite`. `GET
/api/question-banks/{id}/questions` supports `search`, `tag`, `difficulty`,
`standard_code`, `blooms_level`, and `folder_path` filters. Updates retain a
version history. `POST /api/quizzes/{id}/question-pools` accepts
`{ "bank_id": "...", "count": 5, "tags": ["algebra"], "difficulty": 2 }` and
copies a random matching set into the quiz.

Quiz-level delivery settings on create/update include `instructions`,
`shuffle_questions`, `shuffle_options`, `questions_to_serve`,
`allow_multiple_attempts`, and `scoring_policy` (`latest`, `best`, or
`average`). On `PATCH`, set `instructions` or `questions_to_serve` to `null` to
clear that optional setting. Sections are replaced with
`PUT /api/quizzes/{id}/sections` using
`{ "sections": [{ "title": "Part A", "position": 0, "time_limit_minutes": 10,
"shuffle_questions": true, "question_ids": ["..."] }] }`. Section instructions,
time limits, order, and randomization are included in the student snapshot;
per-section countdown enforcement and branching/dependency logic are not yet
implemented. Accommodations set extra time (0-200%), read-aloud, and larger-text
flags per student; the response carries these settings for the client to apply.

CSV import/export uses a header row and JSON-encoded cells for structured
fields. JSON import accepts either a question array or an object containing a
`questions` array; each entry uses the `QuestionWrite` fields. JSON export
returns a question array in that same format, excluding database IDs and
version timestamps so it can be imported into another quiz. QTI import/export
supports a QTI 1.2 question-item set plus a
Northstar extension that preserves all question fields on round-trip; generic
QTI import maps choice and text-entry items to supported question types.
Imports are limited to 500 items per request. Word, Google Forms, and
copy/paste parsing are not implemented.

Import requests use `{ "format": "json", "content": "[...]" }` for a JSON
array, or `{ "format": "json", "content": "{\"questions\": [...]}" }` for
the object form. CSV and QTI requests use the same endpoint and content field.

### Scheduled exams and student attempts

Schedule an exam with ISO-8601 timestamps that include a timezone:

```json
{
  "quiz_id": "4e2f6cc0-42dd-4b79-97ae-2f22579cfe4c",
  "start_time": "2026-11-10T09:00:00Z",
  "end_time": "2026-11-10T10:00:00Z",
  "max_attempts": 1
}
```

Students who belong to a group assigned to the quiz can start it while the
scheduled exam is open. Administrators may also start an attempt for testing; that attempt is recorded
under the administrator's own account, not as a student impersonation.
`POST /api/sessions/{id}/attempt` resumes an active attempt. Once submitted,
another attempt is allowed only when the quiz enables multiple attempts and the
scheduled session's `max_attempts` has not been reached. The deadline is the
earlier of the exam end and the quiz duration extended by an accommodation. The
attempt snapshots its question, options, answer key, media, and randomized
variant so later quiz edits do not change an in-progress attempt.

Call `GET /api/attempts/{id}` on page load/reload to restore the attempt, its
student-safe question data, and saved answers. After each answer change, send
the corresponding `PUT` request (debounced by the client if desired); repeating
the same request replaces that question's previous answer. This provides
server-backed autosave and reload recovery, not server-initiated browser hot
reload. Choice answers send selected option IDs; fill-in and long answers send
text:

```json
{ "selected_option_ids": ["f87df73d-16a1-44b5-819c-37e37f805663"] }
```

```json
{ "text_answer": "H2O" }
```

Structured interactions send `answer_data`, for example
`{ "answer_data": { "value": ["left", "right"] } }`. Empty selections or
`text_answer: null` clear a draft answer. Student attempt responses never
include `is_correct`, `accepted_answers`, or answer configurations. The
`PATCH .../log` body is `{ "log_text": "Formatted text..." }` (or `null` to
clear it). Submitting closes the attempt and auto-grades choices, text, numeric,
and supported structured answers. Essays and code require a teacher grade via
`PUT /api/attempts/{attempt_id}/grades/{question_id}`. `GET
/api/sessions/{id}/my-result` applies the configured latest/best/average policy
after all manual grades are complete. Rubric criteria are configured with
`PUT /api/questions/{id}/rubric`.

### Student performance analytics

`GET /api/students/me/performance?days=365` returns chart-ready performance
data for the signed-in student only. `days` is optional (default `365`, range
`1`-`3650`). The response includes:

- `summary`: submitted, fully graded, and pending-grading attempt counts;
  average, highest, latest, and points-weighted score percentages; and average
  completion duration.
- `score_trend`: one point per fully graded attempt with quiz, attempt number,
  submission time, score, percentage, and duration. Sort/render by
  `submitted_at`.
- `score_distribution`: counts in score-percent buckets, suitable for a bar
  chart.
- `quiz_performance`: average, highest, and latest score by quiz.
- `subject_performance`, `skill_performance`, `standard_performance`,
  `blooms_level_performance`, `question_type_performance`, and
  `difficulty_performance`: grouped earned/possible points, accuracy
  percentage, question-attempt count, and number of attempts represented.

Subject grouping uses the first `folder_path` segment, then a standard-code
prefix, then the quiz section title. Skill grouping uses question tags, falling
back to the standard code, section title, or question type when tags are absent.
Only fully graded submissions contribute to scores and grouped accuracy;
submitted attempts awaiting manual grading appear in the pending count. Older
attempt snapshots may not contain authoring metadata, so where possible the API
uses the current question metadata for those attempts. These are descriptive
learning indicators based on authored question tags and standards, not a
validated diagnosis of student ability.

Activity endpoints store reported focus, paste, copy, fullscreen, and heartbeat
events as review flags; these are client-reported events, not proof of
misconduct. Item analytics include auto-gradable difficulty, discrimination,
and option selection counts. AI grading/generation, code execution, IP/access
restrictions, browser lockdown or reliable paste/tab detection, LMS sync, and
gradebook export are not implemented. Live co-editing, editor previews,
undo/redo, and accessibility presentation require frontend support.

## Legacy design draft (not implemented)

The remaining sections below are historical planning notes. Their routes and
payloads do not describe the implemented API; use the endpoint contracts above.

- **Auth:** after login, the client sends `Authorization: Bearer <token>` on every request.
- **Roles:** `administrator`, `educator` or `student`. Each endpoint below says who may call it.
- **Success:** `200` (OK), `201` (created).
- **Server authority:** the client displays questions/options and collects selections only. The server performs authorization, eligibility, timing, answer validation, checkpoint persistence, result visibility checks, and grading. Never send correct-answer data in a student-facing response or grade answers in the client.
- **Errors** always look like this:

```json
{ "error": "Short human-readable message", "code": 499 }
```

| Code | Meaning |
|---|---|
| 400 | Bad or missing input |
| 401 | Not logged in / bad token |
| 403 | Logged in but wrong role, or not allowed |
| 404 | Not found |
| 409 | Conflict (duplicate email, attempt limit reached) |


---

## 1. Auth (MVP, Week 1)

| Method | URL | Who | Purpose |
|---|---|---|---|
| POST | `/api/auth/register` | anyone | Create an account |
| POST | `/api/auth/login` | anyone | Get a token |
| GET | `/api/auth/me` | any logged in | Current user info |

**POST /api/auth/register**
```json
// request
{ "name": "Aditya", "email": "a@x.com", "password": "<PasswordHash>", "role": "student" }
// response 201
{ "id": 4, "name": "Aditya", "role": "student" }
```

**POST /api/auth/login**
```json
// request
{ "email": "a@x.com", "password": "<PasswordHash>" }
// response 200
{ "token": "eyJ...", "user": { "id": 4, "name": "Aditya", "role": "student" } }
```

---

## 2. Quiz editor (MVP, Week 1) - educator only

| Method | URL | Purpose |
|---|---|---|
| POST | `/api/quizzes` | Create quiz |
| GET | `/api/quizzes` | List my quizzes |
| GET | `/api/quizzes/<id>` | One quiz with its questions and options (includes answers) |
| PUT | `/api/quizzes/<id>` | Edit title, duration, status, etc. |
| DELETE | `/api/quizzes/<id>` | Delete quiz |
| POST | `/api/quizzes/<id>/questions` | Add a question with options |
| PUT | `/api/questions/<id>` | Edit a question |
| DELETE | `/api/questions/<id>` | Delete a question |

**POST /api/quizzes**
```json
{ "title": "Python Basics", "instructions": "No calculators", "duration_minutes": 30,
  "questions_to_serve": null, "shuffle_questions": true, "shuffle_options": true }
```

**POST /api/quizzes/5/questions**
```json
{
  "text": "Which keyword defines a function in Python?",
  "topic": "Functions",
  "marks": 1,
  "allow_multiple": false,
  "options": [
    { "text": "def" },
    { "text": "func" },
    { "text": "function" },
    { "text": "define" }
  ]
}
```

---

## 3. Sessions (MVP, Week 1-2)

| Method | URL | Who | Purpose |
|---|---|---|---|
| POST | `/api/sessions` | educator | Create a session for a quiz |
| GET | `/api/sessions` | both | Educator: my sessions. Student: sessions I can join |
| POST | `/api/sessions/join` | student | Join with a code |
| POST | `/api/sessions/<id>/leave` | student | Leave a session |
| POST | `/api/sessions/<id>/students` | educator | Register students (list of ids or emails) |
| GET | `/api/sessions/<id>/status` | educator | Who has not started / in progress / submitted |

**POST /api/sessions**
```json
{ "quiz_id": 5, "start_time": "2026-10-25T10:00:00", "end_time": "2026-10-25T11:00:00", "max_attempts": 1 }
// response 201
{ "id": 9, "join_code": "K7P2QX" }
```

**POST /api/sessions/join**
```json
{ "join_code": "K7P2QX" }
```

---

## 4. Taking a quiz (MVP, Week 2) - student only

| Method | URL | Purpose |
|---|---|---|
| POST | `/api/sessions/<id>/start` | Start an attempt; server builds this student's random question set |
| GET | `/api/attempts/<id>` | Resume after a refresh (same questions, saved answers) |
| PUT | `/api/attempts/<id>/exam_checkpoint` | Save or replace the answer for one question |
| POST | `/api/attempts/<id>/submit` | Final submit; server grades the whole attempt |
| GET | `/api/attempts/mine` | Previous tests page |
| GET | `/api/attempts/<id>/result` | Score (only if the educator allows it) |

**POST /api/sessions/9/start** returns this student's questions and options, but no correct-answer data:
```json
{
  "attempt_id": 31,
  "ends_at": "2026-10-25T10:30:00",
  "questions": [
    { "id": 12, "text": "Which keyword defines a function?", "marks": 1,
      "allow_multiple": false,
      "options": [ { "id": 45, "text": "def" }, { "id": 47, "text": "func" } ] }
  ]
}
```
Student-facing responses must not contain correct-option IDs, `is_correct` flags, answer keys, or other data that reveals the correct options.

**PUT /api/attempts/31/exam_checkpoint** saves one question's current selection (safe to retry):
```json
{ "question_id": 12, "option_ids": [45] }
```

Each call saves a row in the `exam_checkpoint` table for the `(attempt_id, question_id)` pair. The row contains the attempt ID, question ID, selected option IDs, and save timestamp. A later checkpoint for the same question replaces its earlier selection, so retries or answer changes do not create duplicate rows. For example:
```json
{
  "attempt_id": 31,
  "question_id": 12,
  "option_ids": [45],
  "saved_at": "2026-10-25T10:12:00"
}
```

The server validates every checkpoint: the attempt belongs to the logged-in student, is still `in_progress`, has not run out of time, the question belongs to the attempt, and the selected options belong to that question and satisfy its selection rules. If time has run out, the server auto-submits the attempt and rejects the checkpoint. The client must not decide whether a checkpoint is valid or whether its answer is correct. An `exam_checkpoint` stores selections only; it does not expose or calculate correctness.

**POST /api/attempts/31/submit** finalizes the whole attempt. The server grades saved checkpoints against the answer key on the server; the client never receives the answer key or performs grading. A repeated submission must not grade or finalize the same attempt a second time.
```json
// response 200
{ "status": "submitted", "message": "Your answers were recorded." }
```
Return a score only when the educator allows it. Do not return correct options or answer keys in the submit response; result visibility is checked by the server.

---

## 5. Week 3: security, analytics, reports

| Method | URL | Who | Purpose |
|---|---|---|---|
| POST | `/api/attempts/<id>/events` | student | Log tab switch or focus loss |
| GET | `/api/sessions/<id>/events` | educator | Live feed of suspicious events (polled every few seconds) |
| GET | `/api/sessions/<id>/analytics` | educator | Class analytics |
| GET | `/api/attempts/<id>/report` | both | Detailed report for one attempt |
| GET | `/api/sessions/<id>/export` | educator | CSV / PDF download |

**POST /api/attempts/31/events**
```json
{ "event_type": "tab_hidden", "details": "Tab hidden for 8s" }
```

**GET /api/sessions/9/analytics**
```json
{
  "average_score": 67.5, "highest": 95, "lowest": 30, "pass_percentage": 72,
  "completion_rate": 0.9,
  "topic_average": { "Loops": 65, "Functions": 85 },
  "question_accuracy": [ { "question_id": 12, "percent_correct": 80 } ]
}
```

---

## Suggested implementation order

Build each stage end-to-end, including its database changes and tests, before moving to the next:

1. **Backend foundation:** app configuration, database connection/schema, request validation, and consistent error responses. Add a health endpoint as a quick check that the app and database are available.
2. **Identity and access control:** registration, login, current-user lookup, authentication, and reusable role/ownership checks. Protect educator and student routes before adding their features.
3. **Quiz authoring:** educator quiz and question CRUD, including options and correct-answer storage. Verify that correct-answer data is only returned to authorized educators.
4. **Exam sessions:** create sessions, list/join sessions, register students, and enforce session dates and attempt limits.
5. **Student attempt lifecycle:** start an attempt and create its fixed question set; return questions/options without correct-answer data; resume the attempt; save or replace each answer in `exam_checkpoint`. Enforce ownership, question membership, selection rules, and time limits on the server.
6. **Submission and grading:** finalize an attempt once, grade its saved checkpoints on the server, and store the outcome. Test incomplete, repeated, and timed-out submissions.
7. **Student results and history:** previous attempts and result retrieval, with server-side checks for result visibility. Do not expose correct options unless a deliberate educator-controlled review feature is added.
8. **Post-MVP features:** events, analytics, reports, and exports, built on top of persisted attempts and grades.

The first substantial feature to implement is identity and access control after the backend foundation: every later feature depends on knowing who is making a request and what they are allowed to do.
