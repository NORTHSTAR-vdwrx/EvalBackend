import csv
import io
import json
import xml.etree.ElementTree as ET
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.routes.auth.security import require_role
from app.routes.quiz.helpers import can_manage_quiz
from app.routes.quiz.question_storage import store_quiz_question
from db import get_db
from models import (
    PublicUserAccount,
    QuestionImportRequest,
    QuestionType,
    QuestionWrite,
    Role,
)


imports_router = APIRouter(tags=["question import and export"])
NORTHSTAR_NS = "urn:northstar:eval:question"
ET.register_namespace("ns", NORTHSTAR_NS)
CSV_FIELDS = (
    "question_text",
    "question_type",
    "points",
    "position",
    "image_url",
    "accepted_answers",
    "answer_config",
    "interaction_config",
    "parameter_config",
    "media",
    "options",
    "feedback",
    "worked_solution",
    "partial_credit",
    "tags",
    "difficulty",
    "standard_code",
    "blooms_level",
    "folder_path",
)


def _json_field(row: dict[str, str], field: str, default):
    value = row.get(field, "")
    return json.loads(value) if value else default


def _parse_csv(content: str) -> list[QuestionWrite]:
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames or "question_text" not in reader.fieldnames:
        raise ValueError("CSV must include a question_text column")
    questions = []
    for row in reader:
        raw: dict = {
            "question_text": row.get("question_text", ""),
            "question_type": row.get("question_type") or "long_answer",
            "points": int(row.get("points") or 1),
            "position": int(row.get("position") or 0),
        }
        for field in (
            "accepted_answers",
            "answer_config",
            "interaction_config",
            "parameter_config",
            "media",
            "options",
            "partial_credit",
            "tags",
        ):
            raw[field] = _json_field(
                row,
                field,
                {}
                if field in (
                    "answer_config",
                    "interaction_config",
                    "parameter_config",
                    "partial_credit",
                )
                else [],
            )
        for field in (
            "image_url",
            "feedback",
            "worked_solution",
            "difficulty",
            "standard_code",
            "blooms_level",
            "folder_path",
        ):
            value = row.get(field)
            raw[field] = int(value) if field == "difficulty" and value else value or None
        questions.append(QuestionWrite.model_validate(raw))
    return questions


def _parse_json(content: str) -> list[QuestionWrite]:
    payload = json.loads(content)
    if isinstance(payload, dict):
        payload = payload.get("questions")
    if not isinstance(payload, list):
        raise ValueError("JSON must be an array of questions or an object with a questions array")
    return [QuestionWrite.model_validate(question) for question in payload]


def _parse_qti(content: str) -> list[QuestionWrite]:
    root = ET.fromstring(content)
    items = [
        node for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] in ("assessmentItem", "item")
    ]
    if root.tag.rsplit("}", 1)[-1] in ("assessmentItem", "item"):
        items = [root]
    if not items:
        raise ValueError("No QTI assessmentItem elements found")
    questions = []
    for item in items:
        extension = item.find(f".//{{{NORTHSTAR_NS}}}payload")
        if extension is not None and extension.text:
            questions.append(QuestionWrite.model_validate(json.loads(extension.text)))
            continue

        local = lambda node: node.tag.rsplit("}", 1)[-1]
        body = next((node for node in item.iter() if local(node) == "itemBody"), None)
        if body is not None:
            paragraphs = [node for node in body.iter() if local(node) == "p"]
            prompt = " ".join(" ".join(node.itertext()).strip() for node in paragraphs).strip()
            choice = next((node for node in body.iter() if local(node) == "choiceInteraction"), None)
            choices = (
                [node for node in choice if local(node) == "simpleChoice"]
                if choice is not None
                else []
            )
            multiple = choice is not None and choice.get("maxChoices", "1") != "1"
        else:
            presentation = next(
                (node for node in item.iter() if local(node) == "presentation"),
                None,
            )
            if presentation is None:
                raise ValueError("QTI item has no question presentation")
            prompt_node = next(
                (
                    node for node in presentation.iter()
                    if local(node) == "mattext"
                ),
                None,
            )
            prompt = "".join(prompt_node.itertext()).strip() if prompt_node is not None else ""
            response_lid = next(
                (node for node in presentation.iter() if local(node) == "response_lid"),
                None,
            )
            choices = (
                [node for node in response_lid.iter() if local(node) == "response_label"]
                if response_lid is not None else []
            )
            multiple = response_lid is not None and response_lid.get("rcardinality") == "Multiple"

        correct: set[str] = set()

        def collect_correct(node, negated: bool = False) -> None:
            is_negated = negated or local(node) == "not"
            if local(node) in ("value", "varequal") and node.text and not is_negated:
                correct.add(node.text)
            for child in node:
                collect_correct(child, is_negated)

        collect_correct(item)
        if choices:
            questions.append(
                QuestionWrite(
                    question_text=prompt,
                    question_type=(
                        QuestionType.multiple_choice if multiple else QuestionType.single_choice
                    ),
                    options=[
                        {
                            "option_text": " ".join(
                                "".join(text_node.itertext()).strip()
                                for text_node in node.iter()
                                if local(text_node) in ("mattext", "simpleChoice")
                            ).strip() or "".join(node.itertext()).strip(),
                            "is_correct": (
                                node.get("identifier") or node.get("ident")
                            ) in correct,
                        }
                        for node in choices
                    ],
                )
            )
            continue
        accepted = [value for value in correct]
        questions.append(
            QuestionWrite(
                question_text=prompt,
                question_type=QuestionType.fill_blank if accepted else QuestionType.long_answer,
                accepted_answers=accepted,
            )
        )
    return questions


def _export_qti(questions: list[dict]) -> str:
    root = ET.Element("questestinterop")
    for index, question in enumerate(questions, start=1):
        response_id = "RESPONSE"
        option_identifiers = {
            str(option["id"]): f"OPTION{option_index}"
            for option_index, option in enumerate(question["options"], start=1)
        }
        correct_ids = [
            option_identifiers[str(option["id"])]
            for option in question["options"]
            if option["is_correct"]
        ]
        item = ET.SubElement(root, "item", {"ident": f"question-{index}", "title": f"Question {index}"})
        presentation = ET.SubElement(item, "presentation")
        material = ET.SubElement(presentation, "material")
        ET.SubElement(material, "mattext", {"texttype": "text/plain"}).text = (
            question["question_text"]
        )
        if question["options"]:
            response_lid = ET.SubElement(
                presentation,
                "response_lid",
                {
                    "ident": response_id,
                    "rcardinality": (
                        "Multiple"
                        if question["question_type"] == "multiple_choice"
                        else "Single"
                    ),
                },
            )
            render_choice = ET.SubElement(response_lid, "render_choice", {"shuffle": "No"})
            for option in question["options"]:
                label = ET.SubElement(
                    render_choice,
                    "response_label",
                    {"ident": option_identifiers[str(option["id"])]},
                )
                option_material = ET.SubElement(label, "material")
                ET.SubElement(
                    option_material,
                    "mattext",
                    {"texttype": "text/plain"},
                ).text = option["option_text"]
        else:
            response_str = ET.SubElement(
                presentation,
                "response_str",
                {"ident": response_id, "rcardinality": "Single"},
            )
            ET.SubElement(response_str, "render_fib", {"fibtype": "String"})
        if correct_ids or question["accepted_answers"]:
            resprocessing = ET.SubElement(item, "resprocessing")
            respcondition = ET.SubElement(resprocessing, "respcondition", {"continue": "No"})
            conditionvar = ET.SubElement(respcondition, "conditionvar")
            if question["question_type"] == "multiple_choice":
                condition = ET.SubElement(conditionvar, "and")
                for option in question["options"]:
                    target = (
                        condition
                        if option["is_correct"]
                        else ET.SubElement(condition, "not")
                    )
                    ET.SubElement(target, "varequal", {"respident": response_id}).text = (
                        option_identifiers[str(option["id"])]
                    )
            else:
                for answer in correct_ids or question["accepted_answers"]:
                    ET.SubElement(conditionvar, "varequal", {"respident": response_id}).text = (
                        answer
                    )
            ET.SubElement(
                respcondition,
                "setvar",
                {"action": "Set", "varname": "SCORE"},
            ).text = str(question["points"])
        ET.SubElement(item, f"{{{NORTHSTAR_NS}}}payload").text = json.dumps(
            {
                **{
                    key: value
                    for key, value in question.items()
                    if key not in ("id", "quiz_id", "version", "options")
                },
                "options": [
                    {
                        "option_text": option["option_text"],
                        "is_correct": option["is_correct"],
                        "media": option["media"],
                        "feedback": option["feedback"],
                    }
                    for option in question["options"]
                ],
            },
            ensure_ascii=False,
        )
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


async def _quiz_questions(conn: psycopg.AsyncConnection, quiz_id: UUID) -> list[dict]:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT qq.*, COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                    'id', qo.id,
                    'option_text', qo.option_text,
                    'is_correct', qo.is_correct,
                    'media', qo.media,
                    'feedback', qo.feedback
                ) ORDER BY qo.position, qo.id)
                FROM question_options qo
                WHERE qo.question_id = qq.id
            ), '[]'::jsonb) AS options
            FROM quiz_questions qq
            WHERE qq.quiz_id = %s
            ORDER BY qq.position, qq.created_at, qq.id
            """,
            (quiz_id,),
        )
        return await cur.fetchall()


@imports_router.get("/api/quizzes/{quiz_id}/questions/export")
async def export_quiz_questions(
    quiz_id: UUID,
    format: str = Query(pattern="^(csv|json|qti)$"),
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_quiz(conn, quiz_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    questions = await _quiz_questions(conn, quiz_id)
    if format == "qti":
        return Response(_export_qti(questions), media_type="application/xml")
    if format == "json":
        exported = []
        for question in questions:
            exported.append(
                {
                    key: value
                    for key, value in question.items()
                    if key not in ("id", "quiz_id", "version", "created_at", "updated_at")
                }
            )
            exported[-1]["options"] = [
                {
                    key: value
                    for key, value in option.items()
                    if key != "id"
                }
                for option in question["options"]
            ]
        return Response(
            json.dumps(exported, ensure_ascii=False, indent=2),
            media_type="application/json",
        )

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for question in questions:
        row = dict(question)
        row["options"] = [
            {
                "option_text": option["option_text"],
                "is_correct": option["is_correct"],
                "media": option["media"],
                "feedback": option["feedback"],
            }
            for option in question["options"]
        ]
        for field in (
            "accepted_answers",
            "answer_config",
            "interaction_config",
            "parameter_config",
            "media",
            "options",
            "partial_credit",
            "tags",
        ):
            row[field] = json.dumps(row[field], ensure_ascii=False)
        writer.writerow(row)
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8")


@imports_router.post(
    "/api/quizzes/{quiz_id}/questions/import",
    response_model=list[UUID],
    status_code=status.HTTP_201_CREATED,
)
async def import_quiz_questions(
    quiz_id: UUID,
    data: QuestionImportRequest,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_quiz(conn, quiz_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    try:
        parsers = {
            "csv": _parse_csv,
            "json": _parse_json,
            "qti": _parse_qti,
        }
        questions = parsers[data.format](data.content)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, ET.ParseError) as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid {data.format.upper()} content: {error}")
    if len(questions) > 500:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "At most 500 questions can be imported at once")
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next_position FROM quiz_questions WHERE quiz_id = %s",
            (quiz_id,),
        )
        next_position = (await cur.fetchone())["next_position"]
    created = []
    for question in questions:
        question.position = next_position
        next_position += 1
        created.append(await store_quiz_question(conn, quiz_id, question))
    return created
