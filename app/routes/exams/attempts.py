import random
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from psycopg.types.json import Jsonb

from app.routes.auth.security import require_role
from app.routes.exams.grading import auto_grade
from app.routes.quiz.parameterization import materialize_option, materialize_question
from db import get_db
from models import (
    AttemptActivityCreate,
    AttemptActivityRead,
    AttemptAnswerRead,
    AttemptAnswerWrite,
    AttemptGradeRead,
    AttemptLogUpdate,
    AttemptRead,
    AttemptStartRead,
    AttemptPolicyResult,
    QuizAnalyticsRead,
    ManualGradeWrite,
    PublicUserAccount,
    QuestionType,
    Role,
    StudentQuestionRead,
)


attempts_router = APIRouter(tags=["student attempts"])


def _auto_feedback(question: dict, answer: dict | None) -> str | None:
    messages = [question["feedback"]] if question.get("feedback") else []
    selected_ids = {
        str(value) for value in (answer or {}).get("selected_option_ids", [])
    }
    messages.extend(
        option["feedback"]
        for option in question.get("options", [])
        if str(option["id"]) in selected_ids and option.get("feedback")
    )
    return "\n".join(messages) or None


async def _get_owned_attempt(
    conn: psycopg.AsyncConnection,
    attempt_id: UUID,
    student_id: UUID | None,
    *,
    lock: bool = False,
):
    async with conn.cursor() as cur:
        lock_clause = "FOR UPDATE OF ea" if lock else ""
        await cur.execute(
            f"""
            SELECT ea.id, ea.exam_session_id, es.quiz_id, q.title AS quiz_title,
                   ea.started_at, ea.deadline_at, ea.status, ea.question_snapshot,
                   ea.accommodation_snapshot,
                   ea.log_text, ea.score, ea.max_score, ea.graded_at,
                   NOW() < ea.deadline_at AS is_open
            FROM exam_attempts ea
            JOIN exam_sessions es ON es.id = ea.exam_session_id
            JOIN quizzes q ON q.id = es.quiz_id
            WHERE ea.id = %s
              AND (%s::uuid IS NULL OR ea.student_id = %s)
            {lock_clause}
            """,
            (attempt_id, student_id, student_id),
        )
        return await cur.fetchone()


async def _attempt_response(conn: psycopg.AsyncConnection, attempt) -> AttemptRead:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT question_id, selected_option_ids, text_answer, answer_data,
                   points_awarded, grader_feedback, updated_at
            FROM attempt_answers
            WHERE attempt_id = %s
            ORDER BY updated_at
            """,
            (attempt["id"],),
        )
        answers = await cur.fetchall()
    questions = [
        StudentQuestionRead(**question)
        for question in attempt["question_snapshot"]
    ]
    worked_solutions = {
        question["id"]: question.get("worked_solution")
        for question in attempt["question_snapshot"]
    }
    answer_reads = []
    for answer in answers:
        answer["worked_solution"] = (
            worked_solutions.get(str(answer["question_id"]))
            if answer["points_awarded"] is not None
            else None
        )
        answer_reads.append(AttemptAnswerRead(**answer))
    return AttemptRead(
        id=attempt["id"],
        exam_session_id=attempt["exam_session_id"],
        quiz_id=attempt["quiz_id"],
        quiz_title=attempt["quiz_title"],
        student_id=attempt.get("student_id"),
        student_name=attempt.get("student_name"),
        student_email=attempt.get("student_email"),
        attempt_number=attempt.get("attempt_number", 1),
        started_at=attempt["started_at"],
        deadline_at=attempt["deadline_at"],
        status=attempt["status"],
        log_text=attempt["log_text"],
        score=attempt["score"],
        max_score=attempt["max_score"],
        graded_at=attempt["graded_at"],
        grading_complete=attempt["graded_at"] is not None,
        accommodations=attempt["accommodation_snapshot"] or {},
        questions=questions,
        answers=answer_reads,
    )


@attempts_router.post(
    "/api/sessions/{exam_session_id}/attempt",
    response_model=AttemptStartRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_or_resume_attempt(
    exam_session_id: UUID,
    response: Response,
    user: PublicUserAccount = Depends(require_role(Role.student, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT es.id, es.quiz_id, es.start_time, es.end_time, es.max_attempts,
                   q.duration_minutes, q.allow_multiple_attempts,
                   q.shuffle_questions, q.shuffle_options, q.questions_to_serve,
                   NOW() AS current_time,
                   COALESCE((
                       SELECT extra_time_percent
                       FROM student_accommodations
                       WHERE student_id = %s AND quiz_id = q.id
                   ), 0) AS extra_time_percent,
                   COALESCE((
                       SELECT jsonb_build_object(
                           'extra_time_percent', extra_time_percent,
                           'read_aloud', read_aloud,
                           'large_text', large_text
                       )
                       FROM student_accommodations
                       WHERE student_id = %s AND quiz_id = q.id
                   ), '{}'::jsonb) AS accommodation_snapshot,
                   EXISTS (
                       SELECT 1
                       FROM quiz_groups qg
                       JOIN group_members gm ON gm.group_id = qg.group_id
                       WHERE qg.quiz_id = q.id AND gm.user_id = %s
                   ) OR %s = 'administrator' AS is_assigned
            FROM exam_sessions es
            JOIN quizzes q ON q.id = es.quiz_id
            WHERE es.id = %s
            FOR UPDATE OF es
            """,
            (user.id, user.id, user.id, user.role.value, exam_session_id),
        )
        exam = await cur.fetchone()
        if exam is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Exam session not found")
        if not exam["is_assigned"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Exam is not assigned to you")

        await cur.execute(
            """
            SELECT id, exam_session_id, %s AS quiz_id, started_at, deadline_at,
                   status, attempt_number
            FROM exam_attempts
            WHERE exam_session_id = %s AND student_id = %s AND status = 'in_progress'
            ORDER BY attempt_number DESC
            LIMIT 1
            """,
            (exam["quiz_id"], exam_session_id, user.id),
        )
        existing_attempt = await cur.fetchone()
        if existing_attempt is not None:
            response.status_code = status.HTTP_200_OK
            return AttemptStartRead(**existing_attempt, resumed=True)
        if exam["current_time"] < exam["start_time"] or exam["current_time"] >= exam["end_time"]:
            raise HTTPException(status.HTTP_409_CONFLICT, "Exam session is not currently open")

        await cur.execute(
            """
            SELECT COUNT(*)::int AS attempt_count
            FROM exam_attempts
            WHERE exam_session_id = %s AND student_id = %s
            """,
            (exam_session_id, user.id),
        )
        attempt_number = (await cur.fetchone())["attempt_count"] + 1
        allowed_attempts = exam["max_attempts"] if exam["allow_multiple_attempts"] else 1
        if attempt_number > allowed_attempts:
            raise HTTPException(status.HTTP_409_CONFLICT, "Attempt limit reached")

        await cur.execute(
            """
            SELECT qq.id, qq.question_text, qq.question_type, qq.points, qq.position,
                   qq.image_url, qq.accepted_answers, qq.answer_config,
                   qq.interaction_config, qq.media, qq.partial_credit, qq.feedback,
                   qq.parameter_config, qq.worked_solution, qq.tags, qq.difficulty,
                   qq.standard_code, qq.blooms_level, qq.folder_path,
                   qs.id AS section_id, qs.title AS section_title,
                   qs.instructions AS section_instructions,
                   qs.time_limit_minutes AS section_time_limit_minutes,
                   COALESCE(qs.shuffle_questions, FALSE) AS section_shuffle,
                   qs.position AS section_position
            FROM quiz_questions qq
            LEFT JOIN quiz_section_questions qsq ON qsq.question_id = qq.id
            LEFT JOIN quiz_sections qs ON qs.id = qsq.section_id
            WHERE qq.quiz_id = %s
            ORDER BY COALESCE(qs.position, 2147483647), qq.position, qq.created_at, qq.id
            """,
            (exam["quiz_id"],),
        )
        question_rows = await cur.fetchall()
        if not question_rows:
            raise HTTPException(status.HTTP_409_CONFLICT, "Quiz has no questions")
        if exam["questions_to_serve"] is not None:
            question_rows = random.SystemRandom().sample(
                question_rows,
                min(exam["questions_to_serve"], len(question_rows)),
            )
        if any(question["section_id"] is not None for question in question_rows):
            grouped_questions: dict[str, list[dict]] = {}
            section_order: list[str] = []
            for question in question_rows:
                section_key = str(question["section_id"]) if question["section_id"] else ""
                if section_key not in grouped_questions:
                    grouped_questions[section_key] = []
                    section_order.append(section_key)
                grouped_questions[section_key].append(question)
            question_rows = []
            for section_key in section_order:
                section_questions = grouped_questions[section_key]
                if (
                    (section_questions[0]["section_shuffle"] or exam["shuffle_questions"])
                    and section_key
                ):
                    random.SystemRandom().shuffle(section_questions)
                question_rows.extend(section_questions)
        elif exam["shuffle_questions"]:
            random.SystemRandom().shuffle(question_rows)

        snapshot = []
        for question in question_rows:
            try:
                question = materialize_question(question)
            except (ArithmeticError, SyntaxError, ValueError) as error:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Question has an invalid parameter configuration: {error}",
                )
            await cur.execute(
                """
                SELECT id, option_text, is_correct, media, feedback
                FROM question_options
                WHERE question_id = %s
                ORDER BY position, id
                """,
                (question["id"],),
            )
            options = await cur.fetchall()
            parameter_values = question.get("_parameter_values", {})
            options = [
                materialize_option(option, parameter_values)
                for option in options
            ]
            if exam["shuffle_options"]:
                random.SystemRandom().shuffle(options)
            snapshot.append(
                {
                    "id": str(question["id"]),
                    "question_text": question["question_text"],
                    "question_type": question["question_type"],
                    "points": question["points"],
                    "position": question["position"],
                    "tags": question["tags"],
                    "difficulty": question["difficulty"],
                    "standard_code": question["standard_code"],
                    "blooms_level": question["blooms_level"],
                    "folder_path": question["folder_path"],
                    "image_url": question["image_url"],
                    "section_id": str(question["section_id"]) if question["section_id"] else None,
                    "section_title": question["section_title"],
                    "section_instructions": question["section_instructions"],
                    "section_time_limit_minutes": question["section_time_limit_minutes"],
                    "interaction_config": question["interaction_config"],
                    "media": question["media"],
                    "answer_config": question["answer_config"],
                    "parameter_values": question.get("_parameter_values", {}),
                    "accepted_answers": question["accepted_answers"],
                    "correct_option_ids": [
                        str(option["id"]) for option in options if option["is_correct"]
                    ],
                    "partial_credit": question["partial_credit"],
                    "feedback": question["feedback"],
                    "worked_solution": question["worked_solution"],
                    "options": [
                        {
                            "id": str(option["id"]),
                            "option_text": option["option_text"],
                            "media": option["media"],
                            "feedback": option["feedback"],
                        }
                        for option in options
                    ],
                }
            )

        await cur.execute(
            """
            INSERT INTO exam_attempts (
                exam_session_id, student_id, deadline_at, question_snapshot,
                accommodation_snapshot,
                attempt_number
            )
            VALUES (
                %s, %s,
                LEAST(
                    %s,
                    NOW() + make_interval(
                        secs => %s * 60 * (100 + %s)::double precision / 100
                    )
                ),
                %s, %s, %s
            )
            RETURNING id, exam_session_id, %s AS quiz_id, started_at,
                      deadline_at, status, attempt_number
            """,
            (
                exam_session_id,
                user.id,
                exam["end_time"],
                exam["duration_minutes"],
                exam["extra_time_percent"],
                Jsonb(snapshot),
                Jsonb(exam["accommodation_snapshot"]),
                attempt_number,
                exam["quiz_id"],
            ),
        )
        attempt = await cur.fetchone()
    return AttemptStartRead(**attempt, resumed=False)


@attempts_router.get("/api/attempts/mine", response_model=list[AttemptRead])
async def list_my_attempts(
    user: PublicUserAccount = Depends(require_role(Role.student)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT ea.id, ea.exam_session_id, es.quiz_id, q.title AS quiz_title,
                   ea.started_at, ea.deadline_at, ea.status, ea.question_snapshot,
                   ea.log_text, ea.score, ea.max_score, ea.graded_at,
                   ea.accommodation_snapshot
            FROM exam_attempts ea
            JOIN exam_sessions es ON es.id = ea.exam_session_id
            JOIN quizzes q ON q.id = es.quiz_id
            WHERE ea.student_id = %s
            ORDER BY ea.started_at DESC
            """,
            (user.id,),
        )
        attempts = await cur.fetchall()
    result = []
    for attempt in attempts:
        result.append(await _attempt_response(conn, attempt))
    return result


@attempts_router.get("/api/admin/attempts", response_model=list[AttemptRead])
async def list_all_attempts(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: PublicUserAccount = Depends(require_role(Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT ea.id, ea.exam_session_id, es.quiz_id, q.title AS quiz_title,
                   ea.started_at, ea.deadline_at, ea.status, ea.question_snapshot,
                   ea.log_text, ea.score, ea.max_score, ea.graded_at,
                   ea.accommodation_snapshot
            FROM exam_attempts ea
            JOIN exam_sessions es ON es.id = ea.exam_session_id
            JOIN quizzes q ON q.id = es.quiz_id
            ORDER BY ea.started_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        attempts = await cur.fetchall()
    return [await _attempt_response(conn, attempt) for attempt in attempts]


@attempts_router.get(
    "/api/sessions/{exam_session_id}/attempts",
    response_model=list[AttemptRead],
)
async def list_session_attempts(
    exam_session_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT es.id
            FROM exam_sessions es
            JOIN quizzes q ON q.id = es.quiz_id
            WHERE es.id = %s
              AND (q.teacher_id = %s OR %s = 'administrator')
            """,
            (exam_session_id, user.id, user.role.value),
        )
        if await cur.fetchone() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Exam session not found")
        await cur.execute(
            """
            SELECT ea.id, ea.exam_session_id, es.quiz_id, q.title AS quiz_title,
                   ea.student_id, COALESCE(eu.acc_name, u.username) AS student_name,
                   u.email AS student_email, ea.attempt_number,
                   ea.started_at, ea.deadline_at, ea.status, ea.question_snapshot,
                   ea.log_text, ea.score, ea.max_score, ea.graded_at,
                   ea.accommodation_snapshot
            FROM exam_attempts ea
            JOIN exam_sessions es ON es.id = ea.exam_session_id
            JOIN quizzes q ON q.id = es.quiz_id
            JOIN users u ON u.id = ea.student_id
            LEFT JOIN extended_users eu ON eu.id = u.id
            WHERE es.id = %s
            ORDER BY ea.started_at DESC
            LIMIT %s OFFSET %s
            """,
            (exam_session_id, limit, offset),
        )
        attempts = await cur.fetchall()
    return [await _attempt_response(conn, attempt) for attempt in attempts]


@attempts_router.get("/api/attempts/{attempt_id}", response_model=AttemptRead)
async def get_attempt(
    attempt_id: UUID,
    user: PublicUserAccount = Depends(
        require_role(Role.student, Role.teacher, Role.administrator)
    ),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if user.role == Role.teacher and not await _can_manage_attempt(conn, attempt_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    student_id = user.id if user.role == Role.student else None
    attempt = await _get_owned_attempt(conn, attempt_id, student_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    return await _attempt_response(conn, attempt)


@attempts_router.put(
    "/api/attempts/{attempt_id}/answers/{question_id}",
    response_model=AttemptAnswerRead,
)
async def save_attempt_answer(
    attempt_id: UUID,
    question_id: UUID,
    data: AttemptAnswerWrite,
    user: PublicUserAccount = Depends(require_role(Role.student, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    student_id = user.id if user.role == Role.student else None
    attempt = await _get_owned_attempt(conn, attempt_id, student_id, lock=True)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    if attempt["status"] != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "Attempt has already been submitted")
    if not attempt["is_open"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Attempt deadline has passed")

    question = next(
        (
            item
            for item in attempt["question_snapshot"]
            if item["id"] == str(question_id)
        ),
        None,
    )
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question is not part of this attempt")
    question_type = QuestionType(question["question_type"])
    option_ids = data.selected_option_ids
    allowed_option_ids = {UUID(option["id"]) for option in question["options"]}
    if len(option_ids) != len(set(option_ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Option IDs must be unique")

    if question_type in (
        QuestionType.single_choice,
        QuestionType.true_false,
        QuestionType.multiple_choice,
    ):
        max_options = 1 if question_type in (QuestionType.single_choice, QuestionType.true_false) else None
        if (
            (max_options is not None and len(option_ids) > max_options)
            or any(option_id not in allowed_option_ids for option_id in option_ids)
            or data.text_answer is not None
            or data.answer_data
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Select valid options")
    elif option_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This question does not accept options")
    elif question_type == QuestionType.long_answer and data.answer_data:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Long-answer questions accept a text_answer",
        )

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO attempt_answers (
                attempt_id, question_id, selected_option_ids, text_answer, answer_data
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (attempt_id, question_id) DO UPDATE SET
                selected_option_ids = EXCLUDED.selected_option_ids,
                text_answer = EXCLUDED.text_answer,
                answer_data = EXCLUDED.answer_data,
                updated_at = NOW()
            RETURNING question_id, selected_option_ids, text_answer, answer_data, updated_at
            """,
            (attempt_id, question_id, option_ids, data.text_answer, Jsonb(data.answer_data)),
        )
        row = await cur.fetchone()
    return AttemptAnswerRead(**row)


@attempts_router.patch("/api/attempts/{attempt_id}/log", response_model=AttemptRead)
async def update_attempt_log(
    attempt_id: UUID,
    data: AttemptLogUpdate,
    user: PublicUserAccount = Depends(require_role(Role.student, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE exam_attempts
            SET log_text = %s
            WHERE id = %s
              AND (%s::uuid IS NULL OR student_id = %s)
            RETURNING id
            """,
            (
                data.log_text,
                attempt_id,
                user.id if user.role == Role.student else None,
                user.id if user.role == Role.student else None,
            ),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    attempt = await _get_owned_attempt(
        conn,
        attempt_id,
        user.id if user.role == Role.student else None,
    )
    return await _attempt_response(conn, attempt)


async def _can_manage_attempt(
    conn: psycopg.AsyncConnection,
    attempt_id: UUID,
    user: PublicUserAccount,
) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT ea.id
            FROM exam_attempts ea
            JOIN exam_sessions es ON es.id = ea.exam_session_id
            JOIN quizzes q ON q.id = es.quiz_id
            WHERE ea.id = %s
              AND (q.teacher_id = %s OR %s = 'administrator')
            """,
            (attempt_id, user.id, user.role.value),
        )
        return await cur.fetchone() is not None


@attempts_router.post(
    "/api/attempts/{attempt_id}/activity",
    response_model=AttemptActivityRead,
    status_code=status.HTTP_201_CREATED,
)
async def record_attempt_activity(
    attempt_id: UUID,
    data: AttemptActivityCreate,
    user: PublicUserAccount = Depends(require_role(Role.student, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    student_id = user.id if user.role == Role.student else None
    attempt = await _get_owned_attempt(conn, attempt_id, student_id, lock=True)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    if attempt["status"] != "in_progress" or not attempt["is_open"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Attempt is not active")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO attempt_activity_logs (attempt_id, event_type, details)
            VALUES (%s, %s, %s)
            RETURNING id, event_type, details, created_at
            """,
            (attempt_id, data.event_type, Jsonb(data.details)),
        )
        return AttemptActivityRead(**(await cur.fetchone()))


@attempts_router.get(
    "/api/attempts/{attempt_id}/activity",
    response_model=list[AttemptActivityRead],
)
async def list_attempt_activity(
    attempt_id: UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: PublicUserAccount = Depends(require_role(Role.student, Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if user.role == Role.student:
        attempt = await _get_owned_attempt(conn, attempt_id, user.id)
        if attempt is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    elif not await _can_manage_attempt(conn, attempt_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, event_type, details, created_at
            FROM attempt_activity_logs
            WHERE attempt_id = %s
            ORDER BY created_at, id
            LIMIT %s OFFSET %s
            """,
            (attempt_id, limit, offset),
        )
        return [AttemptActivityRead(**row) for row in await cur.fetchall()]


@attempts_router.put(
    "/api/attempts/{attempt_id}/grades/{question_id}",
    response_model=AttemptGradeRead,
)
async def grade_attempt_question(
    attempt_id: UUID,
    question_id: UUID,
    data: ManualGradeWrite,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await _can_manage_attempt(conn, attempt_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    attempt = await _get_owned_attempt(conn, attempt_id, None)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    if attempt["status"] != "submitted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only submitted attempts can be graded")
    question = next(
        (item for item in attempt["question_snapshot"] if item["id"] == str(question_id)),
        None,
    )
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question is not part of this attempt")
    if question["question_type"] not in ("long_answer", "code", "short_answer"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This question type does not support manual grading",
        )
    if data.points_awarded > question["points"]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Awarded points cannot exceed the question's maximum",
        )

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO attempt_answers (
                attempt_id, question_id, points_awarded, grader_feedback,
                graded_by, graded_at
            )
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (attempt_id, question_id) DO UPDATE SET
                points_awarded = EXCLUDED.points_awarded,
                grader_feedback = EXCLUDED.grader_feedback,
                graded_by = EXCLUDED.graded_by,
                graded_at = NOW(),
                updated_at = NOW()
            """,
            (attempt_id, question_id, data.points_awarded, data.feedback, user.id),
        )
        await cur.execute(
            """
            SELECT COALESCE(SUM(points_awarded), 0)::double precision AS score,
                   COUNT(*) FILTER (WHERE points_awarded IS NOT NULL)::int AS graded_count
            FROM attempt_answers
            WHERE attempt_id = %s
            """,
            (attempt_id,),
        )
        grade_totals = await cur.fetchone()
        max_score = sum(float(item["points"]) for item in attempt["question_snapshot"])
        complete = grade_totals["graded_count"] == len(attempt["question_snapshot"])
        await cur.execute(
            """
            UPDATE exam_attempts
            SET score = %s, max_score = %s,
                graded_at = CASE WHEN %s THEN NOW() ELSE NULL END
            WHERE id = %s
            """,
            (
                grade_totals["score"],
                max_score,
                complete,
                attempt_id,
            ),
        )
        await cur.execute(
            """
            SELECT attempt_id, question_id, points_awarded, grader_feedback,
                   graded_by, graded_at
            FROM attempt_answers
            WHERE attempt_id = %s AND question_id = %s
            """,
            (attempt_id, question_id),
        )
        grade = await cur.fetchone()
        grade["max_points"] = question["points"]
    return AttemptGradeRead(**grade)


@attempts_router.post(
    "/api/attempts/{attempt_id}/submit",
    response_model=AttemptRead,
)
async def submit_attempt(
    attempt_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.student, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    student_id = user.id if user.role == Role.student else None
    attempt = await _get_owned_attempt(conn, attempt_id, student_id, lock=True)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    if attempt["status"] != "submitted":
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT question_id, selected_option_ids, text_answer, answer_data
                FROM attempt_answers
                WHERE attempt_id = %s
                """,
                (attempt_id,),
            )
            answers = {str(row["question_id"]): row for row in await cur.fetchall()}
            score = 0.0
            max_score = 0.0
            all_auto_graded = True
            for question in attempt["question_snapshot"]:
                max_score += float(question["points"])
                answer = answers.get(question["id"])
                awarded = auto_grade(question, answer)
                if awarded is None:
                    all_auto_graded = False
                    continue
                score += awarded
                await cur.execute(
                    """
                    INSERT INTO attempt_answers (
                        attempt_id, question_id, points_awarded, grader_feedback, graded_at
                    )
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (attempt_id, question_id) DO UPDATE SET
                        points_awarded = EXCLUDED.points_awarded,
                        grader_feedback = EXCLUDED.grader_feedback,
                        graded_at = NOW(),
                        updated_at = NOW()
                    """,
                    (
                        attempt_id,
                        UUID(question["id"]),
                        awarded,
                        _auto_feedback(question, answer),
                    ),
                )
            await cur.execute(
                """
                UPDATE exam_attempts
                SET status = 'submitted',
                    submitted_at = COALESCE(submitted_at, NOW()),
                    score = %s,
                    max_score = %s,
                    graded_at = CASE WHEN %s THEN NOW() ELSE NULL END
                WHERE id = %s
                """,
                (score, max_score, all_auto_graded, attempt_id),
            )
    attempt = await _get_owned_attempt(
        conn,
        attempt_id,
        student_id,
    )
    return await _attempt_response(conn, attempt)


@attempts_router.get(
    "/api/sessions/{exam_session_id}/my-result",
    response_model=AttemptPolicyResult,
)
async def get_policy_result(
    exam_session_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.student)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT 1
            FROM exam_attempts
            WHERE exam_session_id = %s AND student_id = %s AND status = 'in_progress'
            LIMIT 1
            """,
            (exam_session_id, user.id),
        )
        if await cur.fetchone() is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "An attempt is still in progress")
        await cur.execute(
            """
            SELECT q.scoring_policy, ea.attempt_number, ea.score, ea.max_score,
                   ea.graded_at
            FROM exam_sessions es
            JOIN quizzes q ON q.id = es.quiz_id
            JOIN exam_attempts ea ON ea.exam_session_id = es.id
            WHERE es.id = %s AND ea.student_id = %s AND ea.status = 'submitted'
            ORDER BY ea.attempt_number
            """,
            (exam_session_id, user.id),
        )
        attempts = await cur.fetchall()
    if not attempts:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No submitted attempts found")
    if any(attempt["graded_at"] is None for attempt in attempts):
        raise HTTPException(status.HTTP_409_CONFLICT, "Manual grading is not complete")
    policy = attempts[0]["scoring_policy"]
    percentages = [
        (attempt["score"] / attempt["max_score"] * 100)
        if attempt["max_score"]
        else 0.0
        for attempt in attempts
    ]
    if policy == "best":
        score_percent = max(percentages)
    elif policy == "average":
        score_percent = sum(percentages) / len(percentages)
    else:
        score_percent = percentages[-1]
    return AttemptPolicyResult(
        exam_session_id=exam_session_id,
        attempts_used=len(attempts),
        policy=policy,
        score_percent=score_percent,
    )


@attempts_router.get(
    "/api/sessions/{exam_session_id}/analytics",
    response_model=list[QuizAnalyticsRead],
)
async def get_exam_analytics(
    exam_session_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT ea.id, ea.question_snapshot
            FROM exam_attempts ea
            JOIN exam_sessions es ON es.id = ea.exam_session_id
            JOIN quizzes q ON q.id = es.quiz_id
            WHERE es.id = %s AND ea.status = 'submitted'
              AND (q.teacher_id = %s OR %s = 'administrator')
            """,
            (exam_session_id, user.id, user.role.value),
        )
        attempt_rows = await cur.fetchall()
        if not attempt_rows:
            await cur.execute(
                """
                SELECT es.id
                FROM exam_sessions es
                JOIN quizzes q ON q.id = es.quiz_id
                WHERE es.id = %s
                  AND (q.teacher_id = %s OR %s = 'administrator')
                """,
                (exam_session_id, user.id, user.role.value),
            )
            if await cur.fetchone() is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Exam session not found")
            return []

        per_question: dict[str, dict] = {}
        per_attempt_scores: dict[str, float] = {}
        per_attempt_question_scores: dict[str, dict[str, float]] = {}
        for attempt in attempt_rows:
            attempt_id = attempt["id"]
            snapshot = attempt["question_snapshot"]
            await cur.execute(
                """
                SELECT question_id, selected_option_ids, text_answer, answer_data
                FROM attempt_answers
                WHERE attempt_id = %s
                """,
                (attempt_id,),
            )
            answers = {
                str(row["question_id"]): row
                for row in await cur.fetchall()
            }
            overall = 0.0
            question_scores: dict[str, float] = {}
            for question in snapshot:
                question_id = question["id"]
                result = auto_grade(question, answers.get(question_id))
                if result is None:
                    continue
                overall += result
                question_scores[question_id] = (
                    result / float(question["points"]) if question["points"] else 0.0
                )
                stats = per_question.setdefault(
                    question_id,
                    {
                        "question_id": UUID(question_id),
                        "question_text": question["question_text"],
                        "response_count": 0,
                        "correct_count": 0,
                        "option_counts": {},
                        "attempt_scores": [],
                    },
                )
                answer = answers.get(question_id)
                answered = answer is not None and (
                    answer["selected_option_ids"]
                    or answer["text_answer"] is not None
                    or answer["answer_data"]
                )
                if answered:
                    stats["response_count"] += 1
                    if result >= float(question["points"]):
                        stats["correct_count"] += 1
                for option_id in (answer or {}).get("selected_option_ids", []):
                    key = str(option_id)
                    stats["option_counts"][key] = stats["option_counts"].get(key, 0) + 1
            per_attempt_scores[str(attempt_id)] = overall
            per_attempt_question_scores[str(attempt_id)] = question_scores

    rank_order = sorted(per_attempt_scores, key=per_attempt_scores.get, reverse=True)
    group_size = max(1, int(len(rank_order) * 0.27))
    top_group = set(rank_order[:group_size])
    bottom_group = set(rank_order[-group_size:])
    results = []
    for question_id, stats in per_question.items():
        top_scores = [
            per_attempt_question_scores[attempt_id].get(question_id)
            for attempt_id in top_group
            if question_id in per_attempt_question_scores[attempt_id]
        ]
        bottom_scores = [
            per_attempt_question_scores[attempt_id].get(question_id)
            for attempt_id in bottom_group
            if question_id in per_attempt_question_scores[attempt_id]
        ]
        discrimination = (
            sum(top_scores) / len(top_scores) - sum(bottom_scores) / len(bottom_scores)
            if top_scores and bottom_scores
            else None
        )
        responses = stats["response_count"]
        results.append(
            QuizAnalyticsRead(
                question_id=stats["question_id"],
                question_text=stats["question_text"],
                response_count=responses,
                correct_count=stats["correct_count"],
                difficulty_index=stats["correct_count"] / responses if responses else None,
                discrimination_index=discrimination,
                option_counts=stats["option_counts"],
            )
        )
    return results
