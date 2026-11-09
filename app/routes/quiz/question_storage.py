from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from models import QuestionType, QuestionWrite


async def store_quiz_question(
    conn: psycopg.AsyncConnection,
    quiz_id: UUID,
    data: QuestionWrite,
) -> UUID:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO quiz_questions (
                quiz_id, question_text, question_type, points, position, image_url,
                accepted_answers, answer_config, interaction_config, media,
                parameter_config, feedback, worked_solution, partial_credit, tags,
                difficulty, standard_code,
                blooms_level, folder_path
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                quiz_id,
                data.question_text,
                data.question_type.value,
                data.points,
                data.position,
                str(data.image_url) if data.image_url else None,
                Jsonb(data.accepted_answers),
                Jsonb(data.answer_config),
                Jsonb(data.interaction_config),
                Jsonb([media.model_dump(mode="json") for media in data.media]),
                Jsonb({
                    name: bounds.model_dump()
                    for name, bounds in data.parameter_config.items()
                }),
                data.feedback,
                data.worked_solution,
                Jsonb(data.partial_credit),
                Jsonb(data.tags),
                data.difficulty,
                data.standard_code,
                data.blooms_level,
                data.folder_path,
            ),
        )
        question_id = (await cur.fetchone())["id"]
        if data.question_type in (
            QuestionType.single_choice,
            QuestionType.multiple_choice,
            QuestionType.true_false,
        ):
            await cur.executemany(
                """
                INSERT INTO question_options (
                    question_id, option_text, is_correct, position, media, feedback
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        question_id,
                        option.option_text,
                        option.is_correct,
                        index,
                        Jsonb([media.model_dump(mode="json") for media in option.media]),
                        option.feedback,
                    )
                    for index, option in enumerate(data.options)
                ],
            )
    return question_id


async def replace_question_options(
    conn: psycopg.AsyncConnection,
    question_id: UUID,
    data: QuestionWrite,
) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM question_options WHERE question_id = %s",
            (question_id,),
        )
        if data.question_type not in (
            QuestionType.single_choice,
            QuestionType.multiple_choice,
            QuestionType.true_false,
        ):
            return
        await cur.executemany(
            """
            INSERT INTO question_options (
                question_id, option_text, is_correct, position, media, feedback
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    question_id,
                    option.option_text,
                    option.is_correct,
                    index,
                    Jsonb([media.model_dump(mode="json") for media in option.media]),
                    option.feedback,
                )
                for index, option in enumerate(data.options)
            ],
        )
