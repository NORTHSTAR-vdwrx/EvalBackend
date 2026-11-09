from collections import defaultdict
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Query

from app.routes.auth.security import require_role
from db import get_db
from models import (
    PublicUserAccount,
    Role,
    StudentPerformanceAnalytics,
    StudentPerformanceGroup,
    StudentPerformanceSummary,
    StudentPerformanceTrendPoint,
    StudentQuizPerformance,
    StudentScoreBucket,
)


student_analytics_router = APIRouter(tags=["student performance analytics"])


def _subject_for(question: dict) -> str:
    folder_path = question.get("folder_path")
    if folder_path:
        return folder_path.split("/", 1)[0].strip() or "Uncategorized"
    standard_code = question.get("standard_code")
    if standard_code:
        return standard_code.split("-", 1)[0].strip() or "Uncategorized"
    return question.get("section_title") or "Uncategorized"


def _skill_categories(question: dict) -> list[str]:
    tags = question.get("tags") or []
    if tags:
        return list(dict.fromkeys(str(tag) for tag in tags if str(tag).strip()))
    for field in ("standard_code", "section_title", "question_type"):
        value = question.get(field)
        if value:
            return [str(value)]
    return ["Uncategorized"]


def _group_performance(groups: dict[str, dict]) -> list[StudentPerformanceGroup]:
    result = []
    for category, data in groups.items():
        possible_points = data["possible_points"]
        result.append(
            StudentPerformanceGroup(
                category=category,
                attempt_count=len(data["attempt_ids"]),
                question_count=data["question_count"],
                earned_points=data["earned_points"],
                possible_points=possible_points,
                accuracy_percent=(
                    data["earned_points"] / possible_points * 100
                    if possible_points
                    else None
                ),
            )
        )
    return sorted(
        result,
        key=lambda item: (-item.question_count, item.category.casefold()),
    )


@student_analytics_router.get(
    "/api/students/me/performance",
    response_model=StudentPerformanceAnalytics,
)
async def get_my_performance_analytics(
    days: int = Query(default=365, ge=1, le=3650),
    user: PublicUserAccount = Depends(require_role(Role.student)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT ea.id AS attempt_id, ea.attempt_number, ea.started_at,
                   COALESCE(ea.submitted_at, ea.started_at) AS submitted_at,
                   ea.score, ea.max_score, ea.graded_at,
                   es.quiz_id, q.title AS quiz_title,
                   snapshot.question,
                   COALESCE(snapshot.question->'tags', qq.tags, '[]'::jsonb) AS tags,
                   COALESCE(snapshot.question->>'difficulty', qq.difficulty::text) AS difficulty,
                   COALESCE(snapshot.question->>'standard_code', qq.standard_code) AS standard_code,
                   COALESCE(snapshot.question->>'blooms_level', qq.blooms_level) AS blooms_level,
                   COALESCE(snapshot.question->>'folder_path', qq.folder_path) AS folder_path,
                   aa.points_awarded
            FROM exam_attempts ea
            JOIN exam_sessions es ON es.id = ea.exam_session_id
            JOIN quizzes q ON q.id = es.quiz_id
            CROSS JOIN LATERAL jsonb_array_elements(ea.question_snapshot)
                AS snapshot(question)
            LEFT JOIN quiz_questions qq
                ON qq.id = (snapshot.question->>'id')::uuid
            LEFT JOIN attempt_answers aa
                ON aa.attempt_id = ea.id
               AND aa.question_id = (snapshot.question->>'id')::uuid
            WHERE ea.student_id = %s
              AND ea.status = 'submitted'
              AND COALESCE(ea.submitted_at, ea.started_at)
                  >= NOW() - (%s * INTERVAL '1 day')
            ORDER BY COALESCE(ea.submitted_at, ea.started_at) DESC,
                     snapshot.question->>'position'
            """,
            (user.id, days),
        )
        rows = await cur.fetchall()

    attempts: dict[UUID, dict] = {}
    grouped = {
        key: defaultdict(
            lambda: {
                "attempt_ids": set(),
                "question_count": 0,
                "earned_points": 0.0,
                "possible_points": 0.0,
            }
        )
        for key in (
            "subject",
            "skill",
            "standard",
            "blooms",
            "question_type",
            "difficulty",
        )
    }

    for row in rows:
        attempt = attempts.setdefault(
            row["attempt_id"],
            {
                "attempt_id": row["attempt_id"],
                "attempt_number": row["attempt_number"],
                "started_at": row["started_at"],
                "submitted_at": row["submitted_at"],
                "score": row["score"],
                "max_score": row["max_score"],
                "graded_at": row["graded_at"],
                "quiz_id": row["quiz_id"],
                "quiz_title": row["quiz_title"],
                "questions": [],
            },
        )
        question = dict(row["question"])
        for field in ("tags", "difficulty", "standard_code", "blooms_level", "folder_path"):
            question[field] = row[field]
        question["points_awarded"] = row["points_awarded"]
        attempt["questions"].append(question)

    graded_attempts = [
        attempt for attempt in attempts.values() if attempt["graded_at"] is not None
    ]
    graded_attempts.sort(key=lambda attempt: attempt["submitted_at"])
    trend = []
    quiz_groups: dict[UUID, list[dict]] = defaultdict(list)
    total_earned = 0.0
    total_possible = 0.0

    for attempt in graded_attempts:
        score = float(attempt["score"] or 0)
        max_score = float(attempt["max_score"] or 0)
        score_percent = score / max_score * 100 if max_score else 0.0
        duration_seconds = max(
            0.0,
            (attempt["submitted_at"] - attempt["started_at"]).total_seconds(),
        )
        trend.append(
            StudentPerformanceTrendPoint(
                attempt_id=attempt["attempt_id"],
                quiz_id=attempt["quiz_id"],
                quiz_title=attempt["quiz_title"],
                submitted_at=attempt["submitted_at"],
                attempt_number=attempt["attempt_number"],
                score=score,
                max_score=max_score,
                score_percent=score_percent,
                duration_seconds=duration_seconds,
            )
        )
        quiz_groups[attempt["quiz_id"]].append(
            {
                "title": attempt["quiz_title"],
                "score_percent": score_percent,
                "submitted_at": attempt["submitted_at"],
            }
        )
        total_earned += score
        total_possible += max_score

        for question in attempt["questions"]:
            awarded = question["points_awarded"]
            if awarded is None:
                continue
            points = float(question.get("points", 0))
            earned = float(awarded)
            categories = {
                "subject": [_subject_for(question)],
                "skill": _skill_categories(question),
                "standard": [question["standard_code"]]
                if question.get("standard_code")
                else [],
                "blooms": [question["blooms_level"]]
                if question.get("blooms_level")
                else [],
                "question_type": [question.get("question_type", "unknown")],
                "difficulty": [f"Level {question['difficulty']}"]
                if question.get("difficulty") is not None
                else [],
            }
            for group_name, values in categories.items():
                for category in values:
                    metric = grouped[group_name][str(category)]
                    metric["attempt_ids"].add(attempt["attempt_id"])
                    metric["question_count"] += 1
                    metric["earned_points"] += earned
                    metric["possible_points"] += points

    score_percents = [point.score_percent for point in trend]
    distributions = [
        ("0-49%", 0, 49),
        ("50-59%", 50, 59),
        ("60-69%", 60, 69),
        ("70-79%", 70, 79),
        ("80-89%", 80, 89),
        ("90-100%", 90, 100),
    ]
    score_distribution = [
        StudentScoreBucket(
            label=label,
            minimum_percent=minimum,
            maximum_percent=maximum,
            attempt_count=sum(
                minimum <= min(100, max(0, score)) < maximum + 1
                for score in score_percents
            ),
        )
        for label, minimum, maximum in distributions
    ]
    quiz_performance = []
    for quiz_id, values in quiz_groups.items():
        ordered = sorted(values, key=lambda value: value["submitted_at"])
        percentages = [value["score_percent"] for value in ordered]
        quiz_performance.append(
            StudentQuizPerformance(
                quiz_id=quiz_id,
                quiz_title=ordered[-1]["title"],
                attempt_count=len(ordered),
                average_score_percent=sum(percentages) / len(percentages),
                highest_score_percent=max(percentages),
                latest_score_percent=percentages[-1],
            )
        )
    quiz_performance.sort(
        key=lambda item: (-item.attempt_count, item.quiz_title.casefold())
    )

    average_duration = (
        sum(point.duration_seconds for point in trend) / len(trend)
        if trend
        else None
    )
    analytics = {
        "period_days": days,
        "summary": StudentPerformanceSummary(
            submitted_attempts=len(attempts),
            graded_attempts=len(graded_attempts),
            pending_grading_attempts=len(attempts) - len(graded_attempts),
            average_score_percent=(
                sum(score_percents) / len(score_percents) if score_percents else None
            ),
            highest_score_percent=max(score_percents) if score_percents else None,
            latest_score_percent=score_percents[-1] if score_percents else None,
            overall_accuracy_percent=(
                total_earned / total_possible * 100 if total_possible else None
            ),
            average_duration_seconds=average_duration,
        ),
        "score_trend": trend,
        "score_distribution": score_distribution,
        "quiz_performance": quiz_performance,
        "subject_performance": _group_performance(grouped["subject"]),
        "skill_performance": _group_performance(grouped["skill"]),
        "standard_performance": _group_performance(grouped["standard"]),
        "blooms_level_performance": _group_performance(grouped["blooms"]),
        "question_type_performance": _group_performance(grouped["question_type"]),
        "difficulty_performance": _group_performance(grouped["difficulty"]),
    }
    return StudentPerformanceAnalytics(**analytics)
