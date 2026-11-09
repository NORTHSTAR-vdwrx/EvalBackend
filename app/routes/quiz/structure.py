from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from app.routes.auth.security import require_role
from app.routes.quiz.helpers import can_manage_quiz
from db import get_db
from models import (
    PublicUserAccount,
    QuizSectionRead,
    QuizSectionsUpdate,
    Role,
    StudentAccommodationWrite,
)


structure_router = APIRouter(tags=["quiz structure"])


@structure_router.get(
    "/api/quizzes/{quiz_id}/sections",
    response_model=list[QuizSectionRead],
)
async def list_quiz_sections(
    quiz_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_quiz(conn, quiz_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT s.id, s.quiz_id, s.title, s.position, s.instructions,
                   s.time_limit_minutes, s.shuffle_questions,
                   COALESCE(
                       array_agg(sq.question_id ORDER BY sq.position)
                           FILTER (WHERE sq.question_id IS NOT NULL),
                       ARRAY[]::uuid[]
                   ) AS question_ids
            FROM quiz_sections s
            LEFT JOIN quiz_section_questions sq ON sq.section_id = s.id
            WHERE s.quiz_id = %s
            GROUP BY s.id
            ORDER BY s.position, s.id
            """,
            (quiz_id,),
        )
        return [QuizSectionRead(**row) for row in await cur.fetchall()]


@structure_router.put(
    "/api/quizzes/{quiz_id}/sections",
    response_model=list[QuizSectionRead],
)
async def replace_quiz_sections(
    quiz_id: UUID,
    data: QuizSectionsUpdate,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_quiz(conn, quiz_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    positions = [section.position for section in data.sections]
    question_ids = [
        question_id
        for section in data.sections
        for question_id in section.question_ids
    ]
    if len(positions) != len(set(positions)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Section positions must be unique")
    if len(question_ids) != len(set(question_ids)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A question can be assigned to only one section",
        )
    async with conn.cursor() as cur:
        if question_ids:
            await cur.execute(
                """
                SELECT id FROM quiz_questions
                WHERE quiz_id = %s AND id = ANY(%s)
                """,
                (quiz_id, question_ids),
            )
            if len(await cur.fetchall()) != len(question_ids):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Every section question must belong to this quiz",
                )
        await cur.execute("DELETE FROM quiz_sections WHERE quiz_id = %s", (quiz_id,))
        for section in data.sections:
            await cur.execute(
                """
                INSERT INTO quiz_sections (
                    quiz_id, title, position, instructions, time_limit_minutes,
                    shuffle_questions
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    quiz_id,
                    section.title.strip(),
                    section.position,
                    section.instructions,
                    section.time_limit_minutes,
                    section.shuffle_questions,
                ),
            )
            section_id = (await cur.fetchone())["id"]
            if section.question_ids:
                await cur.executemany(
                    """
                    INSERT INTO quiz_section_questions (section_id, question_id, position)
                    VALUES (%s, %s, %s)
                    """,
                    [
                        (section_id, question_id, index)
                        for index, question_id in enumerate(section.question_ids)
                    ],
                )
    return await list_quiz_sections(quiz_id, user, conn)


@structure_router.put(
    "/api/quizzes/{quiz_id}/accommodations/{student_id}",
    response_model=StudentAccommodationWrite,
)
async def set_student_accommodation(
    quiz_id: UUID,
    student_id: UUID,
    data: StudentAccommodationWrite,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_quiz(conn, quiz_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id FROM users WHERE id = %s AND role = 'student'",
            (student_id,),
        )
        if await cur.fetchone() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
        await cur.execute(
            """
            INSERT INTO student_accommodations (
                student_id, quiz_id, extra_time_percent, read_aloud, large_text,
                updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (student_id, quiz_id) DO UPDATE SET
                extra_time_percent = EXCLUDED.extra_time_percent,
                read_aloud = EXCLUDED.read_aloud,
                large_text = EXCLUDED.large_text,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            """,
            (
                student_id,
                quiz_id,
                data.extra_time_percent,
                data.read_aloud,
                data.large_text,
                user.id,
            ),
        )
    return data


@structure_router.delete(
    "/api/quizzes/{quiz_id}/accommodations/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_student_accommodation(
    quiz_id: UUID,
    student_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_quiz(conn, quiz_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            DELETE FROM student_accommodations
            WHERE student_id = %s AND quiz_id = %s
            RETURNING student_id
            """,
            (student_id, quiz_id),
        )
        if await cur.fetchone() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Accommodation not found")
