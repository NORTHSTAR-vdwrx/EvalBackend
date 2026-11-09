from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.types.json import Jsonb

from app.routes.auth.security import require_role
from app.routes.exams.grading import auto_grade
from app.routes.quiz.helpers import can_manage_question, can_manage_quiz
from app.routes.quiz.parameterization import materialize_question
from app.routes.quiz.question_storage import replace_question_options, store_quiz_question
from db import get_db
from models import (
    PublicUserAccount,
    QuestionOptionRead,
    QuestionRead,
    QuestionRegradeResult,
    QuestionWrite,
    Role,
    RubricCriterionWrite,
    RubricUpdate,
    QuestionBankVersionRead,
)


questions_router = APIRouter(tags=["quiz questions"])


async def _question_with_options(
    conn: psycopg.AsyncConnection,
    question_id: UUID,
) -> QuestionRead | None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, quiz_id, question_text, question_type, points, position,
                   image_url, accepted_answers, answer_config, interaction_config,
                   parameter_config, media, feedback, worked_solution, partial_credit, tags, difficulty,
                   standard_code, blooms_level, folder_path, version
            FROM quiz_questions
            WHERE id = %s
            """,
            (question_id,),
        )
        question = await cur.fetchone()
        if question is None:
            return None
        await cur.execute(
            """
            SELECT id, option_text, is_correct, media, feedback
            FROM question_options
            WHERE question_id = %s
            ORDER BY position, id
            """,
            (question_id,),
        )
        options = await cur.fetchall()
    return QuestionRead(
        **question,
        options=[QuestionOptionRead(**option) for option in options],
    )


@questions_router.get(
    "/api/quizzes/{quiz_id}/questions",
    response_model=list[QuestionRead],
)
async def list_quiz_questions(
    quiz_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_quiz(conn, quiz_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id
            FROM quiz_questions
            WHERE quiz_id = %s
            ORDER BY position, created_at, id
            """,
            (quiz_id,),
        )
        question_ids = [row["id"] for row in await cur.fetchall()]
    questions = []
    for question_id in question_ids:
        question = await _question_with_options(conn, question_id)
        if question is not None:
            questions.append(question)
    return questions


@questions_router.post(
    "/api/quizzes/{quiz_id}/questions",
    response_model=QuestionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_quiz_question(
    quiz_id: UUID,
    data: QuestionWrite,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_quiz(conn, quiz_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    question_id = await store_quiz_question(conn, quiz_id, data)
    question = await _question_with_options(conn, question_id)
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    return question


@questions_router.put("/api/questions/{question_id}", response_model=QuestionRead)
async def update_question(
    question_id: UUID,
    data: QuestionWrite,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_question(conn, question_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    image_url = str(data.image_url) if data.image_url else None
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO quiz_question_versions (question_id, version, question)
            SELECT qq.id, qq.version,
                   jsonb_build_object(
                       'question_text', qq.question_text,
                       'question_type', qq.question_type,
                       'points', qq.points,
                       'position', qq.position,
                       'image_url', qq.image_url,
                       'accepted_answers', qq.accepted_answers,
                       'answer_config', qq.answer_config,
                       'interaction_config', qq.interaction_config,
                       'parameter_config', qq.parameter_config,
                       'media', qq.media,
                       'feedback', qq.feedback,
                       'worked_solution', qq.worked_solution,
                       'partial_credit', qq.partial_credit,
                       'tags', qq.tags,
                       'difficulty', qq.difficulty,
                       'standard_code', qq.standard_code,
                       'blooms_level', qq.blooms_level,
                       'folder_path', qq.folder_path,
                       'options', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'option_text', qo.option_text,
                               'is_correct', qo.is_correct,
                               'media', qo.media,
                               'feedback', qo.feedback
                           ) ORDER BY qo.position)
                           FROM question_options qo
                           WHERE qo.question_id = qq.id
                       ), '[]'::jsonb)
                   )
            FROM quiz_questions qq
            WHERE qq.id = %s
            """,
            (question_id,),
        )
        await cur.execute(
            """
            UPDATE quiz_questions
            SET question_text = %s,
                question_type = %s,
                points = %s,
                position = %s,
                image_url = %s,
                accepted_answers = %s,
                answer_config = %s,
                interaction_config = %s,
                parameter_config = %s,
                media = %s,
                feedback = %s,
                worked_solution = %s,
                partial_credit = %s,
                tags = %s,
                difficulty = %s,
                standard_code = %s,
                blooms_level = %s,
                folder_path = %s,
                version = version + 1,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                data.question_text.strip(),
                data.question_type.value,
                data.points,
                data.position,
                image_url,
                Jsonb(data.accepted_answers),
                Jsonb(data.answer_config),
                Jsonb(data.interaction_config),
                Jsonb({
                    name: bounds.model_dump()
                    for name, bounds in data.parameter_config.items()
                }),
                Jsonb([media.model_dump(mode="json") for media in data.media]),
                data.feedback,
                data.worked_solution,
                Jsonb(data.partial_credit),
                Jsonb(data.tags),
                data.difficulty,
                data.standard_code,
                data.blooms_level,
                data.folder_path,
                question_id,
            ),
        )
    await replace_question_options(conn, question_id, data)
    question = await _question_with_options(conn, question_id)
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    return question


@questions_router.get(
    "/api/questions/{question_id}/versions",
    response_model=list[QuestionBankVersionRead],
)
async def list_question_versions(
    question_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_question(conn, question_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT version, question, created_at
            FROM quiz_question_versions
            WHERE question_id = %s
            ORDER BY version
            """,
            (question_id,),
        )
        return [QuestionBankVersionRead(**row) for row in await cur.fetchall()]


@questions_router.put(
    "/api/questions/{question_id}/rubric",
    response_model=list[RubricCriterionWrite],
)
async def update_question_rubric(
    question_id: UUID,
    data: RubricUpdate,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_question(conn, question_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT points, question_type FROM quiz_questions WHERE id = %s",
            (question_id,),
        )
        question = await cur.fetchone()
        if question is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
        if question["question_type"] not in ("long_answer", "code", "short_answer"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Rubrics are only supported for manually graded question types",
            )
        total_points = sum(item.max_points for item in data.criteria)
        if total_points > question["points"]:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Rubric criterion points cannot exceed the question points",
            )
        await cur.execute(
            "DELETE FROM question_rubrics WHERE question_id = %s",
            (question_id,),
        )
        if data.criteria:
            await cur.executemany(
                """
                INSERT INTO question_rubrics (
                    question_id, position, title, description, max_points
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        question_id,
                        index,
                        item.title.strip(),
                        item.description,
                        item.max_points,
                    )
                    for index, item in enumerate(data.criteria)
                ],
            )
    return data.criteria


@questions_router.get(
    "/api/questions/{question_id}/rubric",
    response_model=list[RubricCriterionWrite],
)
async def get_question_rubric(
    question_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_question(conn, question_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT title, description, max_points
            FROM question_rubrics
            WHERE question_id = %s
            ORDER BY position
            """,
            (question_id,),
        )
        return [RubricCriterionWrite(**row) for row in await cur.fetchall()]


@questions_router.post(
    "/api/questions/{question_id}/regrade",
    response_model=QuestionRegradeResult,
)
async def regrade_question_attempts(
    question_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_question(conn, question_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, question_type, points, accepted_answers, answer_config,
                   parameter_config, partial_credit, feedback
            FROM quiz_questions
            WHERE id = %s
            """,
            (question_id,),
        )
        current_question = await cur.fetchone()
        if current_question is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
        await cur.execute(
            """
            SELECT id, option_text, is_correct
            FROM question_options
            WHERE question_id = %s
            ORDER BY position, id
            """,
            (question_id,),
        )
        current_options = await cur.fetchall()
        await cur.execute(
            """
            SELECT ea.id, ea.question_snapshot
            FROM exam_attempts ea
            WHERE ea.status = 'submitted'
              AND EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(ea.question_snapshot) AS q
                  WHERE q->>'id' = %s
              )
            FOR UPDATE
            """,
            (str(question_id),),
        )
        attempts = await cur.fetchall()

        updated_attempts = []
        for attempt in attempts:
            snapshot = attempt["question_snapshot"]
            snapshot_question = next(
                (item for item in snapshot if item["id"] == str(question_id)),
                None,
            )
            if snapshot_question is None:
                continue
            if snapshot_question["question_type"] != current_question["question_type"]:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Question type changes cannot be regraded against existing attempts",
                )
            question = dict(snapshot_question)
            question["accepted_answers"] = current_question["accepted_answers"]
            question["answer_config"] = current_question["answer_config"]
            question["partial_credit"] = current_question["partial_credit"]
            question["feedback"] = current_question["feedback"]
            question["parameter_config"] = current_question["parameter_config"]

            correct_texts = {
                option["option_text"]
                for option in current_options
                if option["is_correct"]
            }
            question["correct_option_ids"] = [
                option["id"]
                for option in question.get("options", [])
                if option["option_text"] in correct_texts
            ]
            try:
                question = materialize_question(
                    question,
                    snapshot_question.get("parameter_values"),
                )
            except (ArithmeticError, SyntaxError, ValueError) as error:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Question has an invalid parameter configuration: {error}",
                )
            snapshot[snapshot.index(snapshot_question)] = question

            await cur.execute(
                """
                SELECT selected_option_ids, text_answer, answer_data,
                       points_awarded, graded_by
                FROM attempt_answers
                WHERE attempt_id = %s AND question_id = %s
                """,
                (attempt["id"], question_id),
            )
            answer = await cur.fetchone()
            if answer is None or answer["graded_by"] is None:
                awarded = auto_grade(question, answer)
                if awarded is not None:
                    await cur.execute(
                        """
                        INSERT INTO attempt_answers (
                            attempt_id, question_id, points_awarded, grader_feedback,
                            graded_at
                        )
                        VALUES (%s, %s, %s, %s, NOW())
                        ON CONFLICT (attempt_id, question_id) DO UPDATE SET
                            points_awarded = EXCLUDED.points_awarded,
                            grader_feedback = EXCLUDED.grader_feedback,
                            graded_at = NOW(),
                            updated_at = NOW()
                        """,
                        (
                            attempt["id"],
                            question_id,
                            awarded,
                            question.get("feedback"),
                        ),
                    )

            await cur.execute(
                "UPDATE exam_attempts SET question_snapshot = %s WHERE id = %s",
                (Jsonb(snapshot), attempt["id"]),
            )
            await cur.execute(
                """
                SELECT COALESCE(SUM(points_awarded), 0)::double precision AS score,
                       COUNT(*) FILTER (WHERE points_awarded IS NOT NULL)::int AS graded_count
                FROM attempt_answers
                WHERE attempt_id = %s
                """,
                (attempt["id"],),
            )
            totals = await cur.fetchone()
            max_score = sum(float(item["points"]) for item in snapshot)
            complete = totals["graded_count"] == len(snapshot)
            await cur.execute(
                """
                UPDATE exam_attempts
                SET score = %s, max_score = %s,
                    graded_at = CASE WHEN %s THEN NOW() ELSE NULL END
                WHERE id = %s
                """,
                (totals["score"], max_score, complete, attempt["id"]),
            )
            updated_attempts.append(attempt["id"])
    return QuestionRegradeResult(
        question_id=question_id,
        attempts_regraded=len(updated_attempts),
    )


@questions_router.delete(
    "/api/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_question(
    question_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_question(conn, question_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM quiz_questions WHERE id = %s RETURNING id",
            (question_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
