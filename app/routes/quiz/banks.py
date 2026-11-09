from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg.types.json import Jsonb

from app.routes.auth.security import require_role
from app.routes.quiz.helpers import can_manage_quiz
from app.routes.quiz.question_storage import store_quiz_question
from db import get_db
from models import (
    BankQuestionCreate,
    QuestionBankCreate,
    QuestionBankItemRead,
    QuestionBankRead,
    QuestionBankVersionRead,
    QuestionPoolPull,
    PublicUserAccount,
    Role,
)


banks_router = APIRouter(tags=["question banks"])


async def _bank_access(
    conn: psycopg.AsyncConnection,
    bank_id: UUID,
    user: PublicUserAccount,
    *,
    manage: bool = False,
) -> bool:
    condition = "qb.owner_id = %s OR %s = 'administrator'"
    params: list[object] = [bank_id, user.id, user.role.value]
    if not manage:
        condition = (
            f"({condition}) OR qb.institute_id = "
            "(SELECT institute_id FROM extended_users WHERE id = %s)"
        )
        params.append(user.id)
    async with conn.cursor() as cur:
        await cur.execute(
            f"SELECT qb.id FROM question_banks qb WHERE qb.id = %s AND ({condition})",
            tuple(params),
        )
        return await cur.fetchone() is not None


@banks_router.get("/api/question-banks", response_model=list[QuestionBankRead])
async def list_question_banks(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT qb.id, qb.owner_id, qb.institute_id, qb.name, qb.description,
                   qb.created_at, qb.updated_at
            FROM question_banks qb
            WHERE qb.owner_id = %s
               OR qb.institute_id = (
                   SELECT institute_id FROM extended_users WHERE id = %s
               )
               OR %s = 'administrator'
            ORDER BY qb.name, qb.created_at
            LIMIT %s OFFSET %s
            """,
            (user.id, user.id, user.role.value, limit, offset),
        )
        return [QuestionBankRead(**row) for row in await cur.fetchall()]


@banks_router.post(
    "/api/question-banks",
    response_model=QuestionBankRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_question_bank(
    data: QuestionBankCreate,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bank name cannot be empty")
    institute_id = data.institute_id
    async with conn.cursor() as cur:
        if user.role == Role.teacher:
            await cur.execute(
                "SELECT institute_id FROM extended_users WHERE id = %s",
                (user.id,),
            )
            profile = await cur.fetchone()
            if profile is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Create an extended profile before sharing a question bank",
                )
            if institute_id is not None and institute_id != profile["institute_id"]:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "Teachers can only share banks within their institute",
                )
            institute_id = profile["institute_id"]
        elif institute_id is not None:
            await cur.execute("SELECT id FROM institutes WHERE id = %s", (institute_id,))
            if await cur.fetchone() is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Institute not found")

        await cur.execute(
            """
            INSERT INTO question_banks (owner_id, institute_id, name, description)
            VALUES (%s, %s, %s, %s)
            RETURNING id, owner_id, institute_id, name, description, created_at, updated_at
            """,
            (user.id, institute_id, name, data.description),
        )
        return QuestionBankRead(**(await cur.fetchone()))


@banks_router.delete(
    "/api/question-banks/{bank_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_question_bank(
    bank_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await _bank_access(conn, bank_id, user, manage=True):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question bank not found")
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM question_banks WHERE id = %s", (bank_id,))


@banks_router.get(
    "/api/question-banks/{bank_id}/questions",
    response_model=list[QuestionBankItemRead],
)
async def list_bank_questions(
    bank_id: UUID,
    search: str | None = Query(default=None, min_length=2, max_length=100),
    tag: str | None = Query(default=None, min_length=1, max_length=100),
    difficulty: int | None = Query(default=None, ge=1, le=5),
    standard_code: str | None = Query(default=None, max_length=128),
    blooms_level: str | None = Query(default=None, max_length=16),
    folder_path: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await _bank_access(conn, bank_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question bank not found")
    filters = ["bank_id = %s"]
    params: list[object] = [bank_id]
    if search:
        filters.append("question->>'question_text' ILIKE %s")
        params.append(f"%{search}%")
    if tag:
        filters.append("question->'tags' ? %s")
        params.append(tag)
    if difficulty is not None:
        filters.append("(question->>'difficulty')::int = %s")
        params.append(difficulty)
    if standard_code:
        filters.append("question->>'standard_code' = %s")
        params.append(standard_code)
    if blooms_level:
        filters.append("question->>'blooms_level' = %s")
        params.append(blooms_level)
    if folder_path:
        filters.append("question->>'folder_path' = %s")
        params.append(folder_path)
    params.extend((limit, offset))
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT id, bank_id, question, version, created_at, updated_at
            FROM question_bank_items
            WHERE {' AND '.join(filters)}
            ORDER BY updated_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )
        return [QuestionBankItemRead(**row) for row in await cur.fetchall()]


@banks_router.post(
    "/api/question-banks/{bank_id}/questions",
    response_model=QuestionBankItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_bank_question(
    bank_id: UUID,
    data: BankQuestionCreate,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await _bank_access(conn, bank_id, user, manage=True):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question bank not found")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO question_bank_items (bank_id, question)
            VALUES (%s, %s)
            RETURNING id, bank_id, question, version, created_at, updated_at
            """,
            (bank_id, Jsonb(data.question.model_dump(mode="json"))),
        )
        return QuestionBankItemRead(**(await cur.fetchone()))


@banks_router.put(
    "/api/question-bank-items/{item_id}",
    response_model=QuestionBankItemRead,
)
async def update_bank_question(
    item_id: UUID,
    data: BankQuestionCreate,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT qbi.id, qbi.bank_id, qbi.question, qbi.version
            FROM question_bank_items qbi
            JOIN question_banks qb ON qb.id = qbi.bank_id
            WHERE qbi.id = %s AND (qb.owner_id = %s OR %s = 'administrator')
            FOR UPDATE OF qbi
            """,
            (item_id, user.id, user.role.value),
        )
        previous = await cur.fetchone()
        if previous is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question bank item not found")
        await cur.execute(
            """
            INSERT INTO question_bank_item_versions (item_id, version, question)
            VALUES (%s, %s, %s)
            """,
            (item_id, previous["version"], Jsonb(previous["question"])),
        )
        await cur.execute(
            """
            UPDATE question_bank_items
            SET question = %s, version = version + 1, updated_at = NOW()
            WHERE id = %s
            RETURNING id, bank_id, question, version, created_at, updated_at
            """,
            (Jsonb(data.question.model_dump(mode="json")), item_id),
        )
        return QuestionBankItemRead(**(await cur.fetchone()))


@banks_router.delete(
    "/api/question-bank-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_bank_question(
    item_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            DELETE FROM question_bank_items qbi
            USING question_banks qb
            WHERE qbi.bank_id = qb.id AND qbi.id = %s
              AND (qb.owner_id = %s OR %s = 'administrator')
            RETURNING qbi.id
            """,
            (item_id, user.id, user.role.value),
        )
        if await cur.fetchone() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question bank item not found")


@banks_router.get(
    "/api/question-bank-items/{item_id}/versions",
    response_model=list[QuestionBankVersionRead],
)
async def list_bank_question_versions(
    item_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT qbi.bank_id, qbi.version, qbi.question AS current_question,
                   qb.owner_id, qb.institute_id
            FROM question_bank_items qbi
            JOIN question_banks qb ON qb.id = qbi.bank_id
            WHERE qbi.id = %s
            """,
            (item_id,),
        )
        item = await cur.fetchone()
        if item is None or (
            item["owner_id"] != user.id
            and user.role != Role.administrator
            and not await _bank_access(conn, item["bank_id"], user)
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question bank item not found")
        await cur.execute(
            """
            SELECT version, question, created_at
            FROM question_bank_item_versions
            WHERE item_id = %s
            UNION ALL
            SELECT %s AS version, %s AS question, NOW() AS created_at
            ORDER BY version
            """,
            (item_id, item["version"], Jsonb(item["current_question"])),
        )
        return [QuestionBankVersionRead(**row) for row in await cur.fetchall()]


@banks_router.post(
    "/api/quizzes/{quiz_id}/question-pools",
    response_model=list[UUID],
    status_code=status.HTTP_201_CREATED,
)
async def pull_question_pool(
    quiz_id: UUID,
    data: QuestionPoolPull,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_quiz(conn, quiz_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    if not await _bank_access(conn, data.bank_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question bank not found")
    filters = ["bank_id = %s"]
    params: list[object] = [data.bank_id]
    if data.difficulty is not None:
        filters.append("(question->>'difficulty')::int = %s")
        params.append(data.difficulty)
    if data.tags:
        filters.append("question->'tags' ?| %s")
        params.append(data.tags)
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT question
            FROM question_bank_items
            WHERE {' AND '.join(filters)}
            ORDER BY RANDOM()
            LIMIT %s
            """,
            (*params, data.count),
        )
        selected = await cur.fetchall()
    if len(selected) < data.count:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Pool contains only {len(selected)} questions matching the requested filters",
        )
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next_position FROM quiz_questions WHERE quiz_id = %s",
            (quiz_id,),
        )
        next_position = (await cur.fetchone())["next_position"]
    created_ids = []
    for row in selected:
        question = BankQuestionCreate(question=row["question"]).question
        question.position = next_position
        next_position += 1
        created_ids.append(await store_quiz_question(conn, quiz_id, question))
    return created_ids
