from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from db import get_db
from models import (
    PublicUserAccount,
    QuizCreate,
    QuizGroupsUpdate,
    QuizRead,
    QuizUpdate,
    Role,
)
from app.routes.auth.security import get_current_user, require_role
from app.routes.quiz.helpers import can_manage_quiz


quizzes_router = APIRouter(prefix="/api/quizzes", tags=["quizzes"])


async def _quiz_query(conn: psycopg.AsyncConnection, quiz_id: UUID, user: PublicUserAccount):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT q.id, q.teacher_id, q.title, q.duration_minutes,
                   q.instructions, q.shuffle_questions, q.shuffle_options,
                   q.questions_to_serve, q.allow_multiple_attempts, q.scoring_policy,
                   q.created_at,
                   q.updated_at,
                   COALESCE(
                       array_agg(qg.group_id) FILTER (WHERE qg.group_id IS NOT NULL),
                       ARRAY[]::uuid[]
                   ) AS group_ids
            FROM quizzes q
            LEFT JOIN quiz_groups qg ON qg.quiz_id = q.id
            WHERE q.id = %s
              AND (
                  q.teacher_id = %s
                  OR %s = 'administrator'
                  OR EXISTS (
                      SELECT 1
                      FROM quiz_groups visible_qg
                      JOIN group_members gm ON gm.group_id = visible_qg.group_id
                      WHERE visible_qg.quiz_id = q.id AND gm.user_id = %s
                  )
              )
            GROUP BY q.id
            """,
            (quiz_id, user.id, user.role.value, user.id),
        )
        return await cur.fetchone()


@quizzes_router.get("", response_model=list[QuizRead])
async def list_quizzes(
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        if user.role == Role.administrator:
            await cur.execute(
                """
                SELECT q.id, q.teacher_id, q.title, q.duration_minutes,
                       q.instructions, q.shuffle_questions, q.shuffle_options,
                       q.questions_to_serve, q.allow_multiple_attempts, q.scoring_policy,
                       q.created_at,
                       q.updated_at,
                       COALESCE(
                           array_agg(qg.group_id) FILTER (WHERE qg.group_id IS NOT NULL),
                           ARRAY[]::uuid[]
                       ) AS group_ids
                FROM quizzes q
                LEFT JOIN quiz_groups qg ON qg.quiz_id = q.id
                GROUP BY q.id
                ORDER BY q.created_at DESC
                """
            )
        elif user.role == Role.teacher:
            await cur.execute(
                """
                SELECT q.id, q.teacher_id, q.title, q.duration_minutes,
                       q.instructions, q.shuffle_questions, q.shuffle_options,
                       q.questions_to_serve, q.allow_multiple_attempts, q.scoring_policy,
                       q.created_at,
                       q.updated_at,
                       COALESCE(
                           array_agg(qg.group_id) FILTER (WHERE qg.group_id IS NOT NULL),
                           ARRAY[]::uuid[]
                       ) AS group_ids
                FROM quizzes q
                LEFT JOIN quiz_groups qg ON qg.quiz_id = q.id
                WHERE q.teacher_id = %s
                GROUP BY q.id
                ORDER BY q.created_at DESC
                """,
                (user.id,),
            )
        else:
            await cur.execute(
                """
                SELECT q.id, q.teacher_id, q.title, q.duration_minutes,
                       q.instructions, q.shuffle_questions, q.shuffle_options,
                       q.questions_to_serve, q.allow_multiple_attempts, q.scoring_policy,
                       q.created_at,
                       q.updated_at,
                       COALESCE(
                           array_agg(DISTINCT qg.group_id)
                               FILTER (WHERE qg.group_id IS NOT NULL),
                           ARRAY[]::uuid[]
                       ) AS group_ids
                FROM quizzes q
                JOIN quiz_groups qg ON qg.quiz_id = q.id
                JOIN group_members gm ON gm.group_id = qg.group_id
                WHERE gm.user_id = %s
                GROUP BY q.id
                ORDER BY q.created_at DESC
                """,
                (user.id,),
            )
        rows = await cur.fetchall()
    return [QuizRead(**row) for row in rows]


@quizzes_router.post("", response_model=QuizRead, status_code=status.HTTP_201_CREATED)
async def create_quiz(
    data: QuizCreate,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    title = data.title.strip()
    if not title:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Quiz title cannot be empty")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO quizzes (
                teacher_id, title, duration_minutes, instructions, shuffle_questions,
                shuffle_options, questions_to_serve, allow_multiple_attempts, scoring_policy
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, teacher_id, title, duration_minutes, instructions,
                      shuffle_questions, shuffle_options, questions_to_serve,
                      allow_multiple_attempts, scoring_policy, created_at, updated_at
            """,
            (
                user.id,
                title,
                data.duration_minutes,
                data.instructions,
                data.shuffle_questions,
                data.shuffle_options,
                data.questions_to_serve,
                data.allow_multiple_attempts,
                data.scoring_policy,
            ),
        )
        row = await cur.fetchone()
    row["group_ids"] = []
    return QuizRead(**row)


@quizzes_router.get("/{quiz_id}", response_model=QuizRead)
async def get_quiz(
    quiz_id: UUID,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    row = await _quiz_query(conn, quiz_id, user)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    return QuizRead(**row)


@quizzes_router.patch("/{quiz_id}", response_model=QuizRead)
async def update_quiz(
    quiz_id: UUID,
    data: QuizUpdate,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one field is required")
    if any(
        value is None
        for field, value in updates.items()
        if field not in ("instructions", "questions_to_serve")
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Required quiz fields cannot be null")
    if "title" in updates:
        updates["title"] = updates["title"].strip()
        if not updates["title"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Quiz title cannot be empty")
    if not await can_manage_quiz(conn, quiz_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")

    assignments = ", ".join(f"{field} = %s" for field in updates)
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            UPDATE quizzes
            SET {assignments}, updated_at = NOW()
            WHERE id = %s
            """,
            (*updates.values(), quiz_id),
        )
    detail = await _quiz_query(conn, quiz_id, user)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    return QuizRead(**detail)


@quizzes_router.put("/{quiz_id}/groups", response_model=QuizRead)
async def set_quiz_groups(
    quiz_id: UUID,
    data: QuizGroupsUpdate,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_quiz(conn, quiz_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    group_ids = data.group_ids
    if len(group_ids) != len(set(group_ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Group IDs must be unique")

    async with conn.cursor() as cur:
        if group_ids:
            if user.role == Role.administrator:
                await cur.execute(
                    "SELECT id FROM user_groups WHERE id = ANY(%s)",
                    (group_ids,),
                )
            else:
                await cur.execute(
                    """
                    SELECT id FROM user_groups
                    WHERE id = ANY(%s) AND creating_teacher = %s
                    """,
                    (group_ids, user.id),
                )
            valid_groups = await cur.fetchall()
            if len(valid_groups) != len(group_ids):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Every group must exist and be managed by the quiz owner",
                )
        await cur.execute("DELETE FROM quiz_groups WHERE quiz_id = %s", (quiz_id,))
        if group_ids:
            await cur.executemany(
                "INSERT INTO quiz_groups (quiz_id, group_id) VALUES (%s, %s)",
                [(quiz_id, group_id) for group_id in group_ids],
            )

    row = await _quiz_query(conn, quiz_id, user)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    return QuizRead(**row)


@quizzes_router.delete("/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quiz(
    quiz_id: UUID,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_quiz(conn, quiz_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM quizzes WHERE id = %s RETURNING id", (quiz_id,))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
