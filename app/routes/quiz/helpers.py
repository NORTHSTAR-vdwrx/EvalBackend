from uuid import UUID

import psycopg

from models import PublicUserAccount


async def can_manage_quiz(
    conn: psycopg.AsyncConnection,
    quiz_id: UUID,
    user: PublicUserAccount,
) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id FROM quizzes
            WHERE id = %s AND (teacher_id = %s OR %s = 'administrator')
            """,
            (quiz_id, user.id, user.role.value),
        )
        return await cur.fetchone() is not None


async def can_manage_question(
    conn: psycopg.AsyncConnection,
    question_id: UUID,
    user: PublicUserAccount,
) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT qq.id
            FROM quiz_questions qq
            JOIN quizzes q ON q.id = qq.quiz_id
            WHERE qq.id = %s
              AND (q.teacher_id = %s OR %s = 'administrator')
            """,
            (question_id, user.id, user.role.value),
        )
        return await cur.fetchone() is not None
