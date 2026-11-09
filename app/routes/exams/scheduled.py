import secrets
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from db import get_db
from models import (
    ExamSessionCreate,
    ExamSessionRead,
    ExamSessionUpdate,
    PublicUserAccount,
    Role,
)
from app.routes.auth.security import get_current_user, require_role


exam_sessions_router = APIRouter(prefix="/api/sessions", tags=["exam sessions"])
JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


async def _get_visible_session(
    conn: psycopg.AsyncConnection,
    session_id: UUID,
    user: PublicUserAccount,
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT es.id, es.quiz_id, q.title AS quiz_title, es.join_code,
                   es.start_time, es.end_time, es.max_attempts, es.created_at
            FROM exam_sessions es
            JOIN quizzes q ON q.id = es.quiz_id
            WHERE es.id = %s
              AND (
                  q.teacher_id = %s
                  OR %s = 'administrator'
                  OR EXISTS (
                      SELECT 1
                      FROM quiz_groups qg
                      JOIN group_members gm ON gm.group_id = qg.group_id
                      WHERE qg.quiz_id = q.id AND gm.user_id = %s
                  )
              )
            """,
            (session_id, user.id, user.role.value, user.id),
        )
        return await cur.fetchone()


async def _can_manage_session(
    conn: psycopg.AsyncConnection,
    session_id: UUID,
    user: PublicUserAccount,
) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT es.id
            FROM exam_sessions es
            JOIN quizzes q ON q.id = es.quiz_id
            WHERE es.id = %s
              AND (q.teacher_id = %s OR %s = 'administrator')
            """,
            (session_id, user.id, user.role.value),
        )
        return await cur.fetchone() is not None


@exam_sessions_router.get("", response_model=list[ExamSessionRead])
async def list_sessions(
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        if user.role == Role.administrator:
            await cur.execute(
                """
                SELECT es.id, es.quiz_id, q.title AS quiz_title, es.join_code,
                       es.start_time, es.end_time, es.max_attempts, es.created_at
                FROM exam_sessions es
                JOIN quizzes q ON q.id = es.quiz_id
                ORDER BY es.start_time DESC
                """
            )
        elif user.role == Role.teacher:
            await cur.execute(
                """
                SELECT es.id, es.quiz_id, q.title AS quiz_title, es.join_code,
                       es.start_time, es.end_time, es.max_attempts, es.created_at
                FROM exam_sessions es
                JOIN quizzes q ON q.id = es.quiz_id
                WHERE q.teacher_id = %s
                ORDER BY es.start_time DESC
                """,
                (user.id,),
            )
        else:
            await cur.execute(
                """
                SELECT DISTINCT es.id, es.quiz_id, q.title AS quiz_title, es.join_code,
                       es.start_time, es.end_time, es.max_attempts, es.created_at
                FROM exam_sessions es
                JOIN quizzes q ON q.id = es.quiz_id
                JOIN quiz_groups qg ON qg.quiz_id = q.id
                JOIN group_members gm ON gm.group_id = qg.group_id
                WHERE gm.user_id = %s
                ORDER BY es.start_time DESC
                """,
                (user.id,),
            )
        rows = await cur.fetchall()
    return [ExamSessionRead(**row) for row in rows]


@exam_sessions_router.post(
    "",
    response_model=ExamSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    data: ExamSessionCreate,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if any(
        value.tzinfo is None or value.utcoffset() is None
        for value in (data.start_time, data.end_time)
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Session times must include a timezone",
        )
    if data.end_time <= data.start_time:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "End time must be later than start time",
        )
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id FROM quizzes
            WHERE id = %s AND (teacher_id = %s OR %s = 'administrator')
            """,
            (data.quiz_id, user.id, user.role.value),
        )
        if await cur.fetchone() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")

        for _ in range(5):
            join_code = "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(6))
            await cur.execute(
                """
                INSERT INTO exam_sessions (
                    quiz_id, join_code, start_time, end_time, max_attempts
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (join_code) DO NOTHING
                RETURNING id, quiz_id, join_code, start_time, end_time,
                          max_attempts, created_at
                """,
                (
                    data.quiz_id,
                    join_code,
                    data.start_time,
                    data.end_time,
                    data.max_attempts,
                ),
            )
            row = await cur.fetchone()
            if row is not None:
                break
        else:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Could not generate a unique session code",
            )
    row["quiz_title"] = await _get_quiz_title(conn, data.quiz_id)
    return ExamSessionRead(**row)


async def _get_quiz_title(conn: psycopg.AsyncConnection, quiz_id: UUID) -> str:
    async with conn.cursor() as cur:
        await cur.execute("SELECT title FROM quizzes WHERE id = %s", (quiz_id,))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    return row["title"]


@exam_sessions_router.get("/{session_id}", response_model=ExamSessionRead)
async def get_session(
    session_id: UUID,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    row = await _get_visible_session(conn, session_id, user)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return ExamSessionRead(**row)


@exam_sessions_router.patch("/{session_id}", response_model=ExamSessionRead)
async def update_session(
    session_id: UUID,
    data: ExamSessionUpdate,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one field is required")
    if any(value is None for value in updates.values()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Session fields cannot be null")
    if any(
        value.tzinfo is None or value.utcoffset() is None
        for value in updates.values()
        if hasattr(value, "tzinfo")
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Session times must include a timezone",
        )
    if not await _can_manage_session(conn, session_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT start_time, end_time FROM exam_sessions WHERE id = %s",
            (session_id,),
        )
        current = await cur.fetchone()
        if current is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
        start_time = updates.get("start_time", current["start_time"])
        end_time = updates.get("end_time", current["end_time"])
        if end_time <= start_time:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "End time must be later than start time",
            )
        assignments = ", ".join(f"{field} = %s" for field in updates)
        await cur.execute(
            f"""
            UPDATE exam_sessions
            SET {assignments}
            WHERE id = %s
            RETURNING id, quiz_id, join_code, start_time, end_time,
                      max_attempts, created_at
            """,
            (*updates.values(), session_id),
        )
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    row["quiz_title"] = await _get_quiz_title(conn, row["quiz_id"])
    return ExamSessionRead(**row)


@exam_sessions_router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_session(
    session_id: UUID,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await _can_manage_session(conn, session_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM exam_sessions WHERE id = %s RETURNING id",
            (session_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
