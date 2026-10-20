# NORTHSTAR Eval: API Schema (draft v1)

Backend: Python + Flask. Database: MySQL (see `schema.sql`).
All requests and responses are JSON. All URLs start with `/api`.

## Conventions

- **Auth:** after login, the client sends `Authorization: Bearer <token>` on every request.
- **Roles:** `educator` or `student`. Each endpoint below says who may call it.
- **Success:** `200` (OK), `201` (created).
- **Errors** always look like this:

```json
{ "error": "Short human-readable message" }
```

| Code | Meaning |
|---|---|
| 400 | Bad or missing input |
| 401 | Not logged in / bad token |
| 403 | Logged in but wrong role, or not allowed |
| 404 | Not found |
| 409 | Conflict (duplicate email, attempt limit reached) |

**Golden rule:** no student-facing response may ever contain `is_correct`.

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
{ "name": "Aditya", "email": "a@x.com", "password": "secret123", "role": "student" }
// response 201
{ "id": 4, "name": "Aditya", "role": "student" }
```

**POST /api/auth/login**
```json
// request
{ "email": "a@x.com", "password": "secret123" }
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
    { "text": "def", "is_correct": true },
    { "text": "func", "is_correct": false },
    { "text": "function", "is_correct": false },
    { "text": "define", "is_correct": false }
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
| PUT | `/api/attempts/<id>/answers` | Autosave one answer |
| POST | `/api/attempts/<id>/submit` | Final submit and grade |
| GET | `/api/attempts/mine` | Previous tests page |
| GET | `/api/attempts/<id>/result` | Score (only if the educator allows it) |

**POST /api/sessions/9/start** returns the questions, with no answers:
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

**PUT /api/attempts/31/answers** (safe to call repeatedly)
```json
{ "question_id": 12, "option_ids": [45] }
```

Server checks on every answer call:
1. The attempt belongs to the logged-in student.
2. The attempt is still `in_progress`.
3. The time has not run out (otherwise auto-submit and return `403`).

**POST /api/attempts/31/submit** response:
```json
{ "status": "submitted", "message": "Your answers were recorded." }
```
(Return the score only when the educator allows it.)

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

## Build order for Pranav

1. `GET /api/health` (check the server runs)
2. Register, login, `me`
3. Role-check decorator
4. Quiz and question CRUD
5. Sessions: create, join
6. Start attempt, autosave answer, submit and grade
7. Previous tests
8. Week 3 endpoints

## Questions to settle with the team

- Token type: JWT via `flask-jwt-extended` is the simplest choice.
- Does Sreyam want any extra fields in the responses (for example, the student's name on the session status list)?
- Will results be shown immediately after submit? This decides what `/submit` returns.
