import ast
from datetime import datetime
from enum import StrEnum
from math import isfinite
import re
from typing import Any
from uuid import UUID
from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    HttpUrl,
    computed_field,
    field_validator,
    model_validator,
)

class Role(StrEnum):
    student = "student"
    teacher = "teacher"
    administrator = "administrator"

class PublicUserAccount(BaseModel):
    id: UUID
    username: str = Field(min_length=4, max_length=32)
    email: EmailStr
    role: Role
    created_at: datetime

    @computed_field
    @property
    def user_id(self) -> UUID:
        return self.id


class AdminUserDirectoryEntry(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    username: str
    email: EmailStr
    role: Role
    created_at: datetime
    acc_name: str | None
    institute_id: UUID | None
    institute_member_number: str | None
    phone: str | None
    timezone: str | None

class FullUserAccount(PublicUserAccount):
    password_hash: str = Field(repr=False)

class UserCreate(BaseModel):
    username: str = Field(min_length=4, max_length=32)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=4, max_length=32)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role


class AdminUserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=4, max_length=32)
    email: EmailStr | None = None
    role: Role | None = None


class InstituteCreate(BaseModel):
    institute_name: str = Field(min_length=1, max_length=255)


class InstituteUpdate(BaseModel):
    institute_name: str | None = Field(default=None, min_length=1, max_length=255)


class InstituteRead(BaseModel):
    id: UUID
    institute_name: str


class ExtendedUserWrite(BaseModel):
    acc_name: str = Field(min_length=1, max_length=255)
    institute_id: UUID
    institute_member_number: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=30)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class ExtendedUserUpdate(BaseModel):
    acc_name: str | None = Field(default=None, min_length=1, max_length=255)
    institute_id: UUID | None = None
    institute_member_number: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=30)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)


class ExtendedUserRead(BaseModel):
    id: UUID
    acc_name: str
    institute_id: UUID
    institute_member_number: str | None
    phone: str | None
    timezone: str
    is_active: bool
    email_verified_at: datetime | None
    last_login_at: datetime | None
    updated_at: datetime


class GroupCreate(BaseModel):
    group_name: str = Field(min_length=1, max_length=255)
    is_public: bool = False
    institute_id: UUID | None = None


class GroupUpdate(BaseModel):
    group_name: str | None = Field(default=None, min_length=1, max_length=255)
    is_public: bool | None = None


class GroupRead(BaseModel):
    id: UUID
    group_name: str
    is_public: bool
    creating_teacher: UUID
    created_by_username: str
    institute_id: UUID
    created_at: datetime
    member_count: int


class GroupMemberCreate(BaseModel):
    user_id: UUID


class GroupMemberRead(BaseModel):
    user_id: UUID
    username: str
    email: EmailStr
    role: Role
    added_at: datetime


class GroupStudentSearchResult(BaseModel):
    user_id: UUID
    acc_name: str
    username: str
    email: EmailStr
    institute_member_number: str | None


class QuizCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    duration_minutes: int = Field(gt=0)
    instructions: str | None = Field(default=None, max_length=10000)
    shuffle_questions: bool = False
    shuffle_options: bool = False
    questions_to_serve: int | None = Field(default=None, gt=0)
    allow_multiple_attempts: bool = False
    scoring_policy: str = Field(default="latest", pattern="^(latest|best|average)$")


class QuizUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    duration_minutes: int | None = Field(default=None, gt=0)
    instructions: str | None = Field(default=None, max_length=10000)
    shuffle_questions: bool | None = None
    shuffle_options: bool | None = None
    questions_to_serve: int | None = Field(default=None, gt=0)
    allow_multiple_attempts: bool | None = None
    scoring_policy: str | None = Field(default=None, pattern="^(latest|best|average)$")


class QuizRead(BaseModel):
    id: UUID
    teacher_id: UUID
    title: str
    duration_minutes: int
    created_at: datetime
    updated_at: datetime
    group_ids: list[UUID] = Field(default_factory=list)
    instructions: str | None = None
    shuffle_questions: bool = False
    shuffle_options: bool = False
    questions_to_serve: int | None = None
    allow_multiple_attempts: bool = False
    scoring_policy: str = "latest"


class QuizGroupsUpdate(BaseModel):
    group_ids: list[UUID]


class ExamSessionCreate(BaseModel):
    quiz_id: UUID
    start_time: datetime
    end_time: datetime
    max_attempts: int = Field(default=1, gt=0)


class ExamSessionUpdate(BaseModel):
    start_time: datetime | None = None
    end_time: datetime | None = None
    max_attempts: int | None = Field(default=None, gt=0)


class ExamSessionRead(BaseModel):
    id: UUID
    quiz_id: UUID
    quiz_title: str
    join_code: str
    start_time: datetime
    end_time: datetime
    max_attempts: int
    created_at: datetime


class QuestionType(StrEnum):
    single_choice = "single_choice"
    multiple_choice = "multiple_choice"
    true_false = "true_false"
    short_answer = "short_answer"
    numeric = "numeric"
    fill_blank = "fill_blank"
    matching = "matching"
    ordering = "ordering"
    hotspot = "hotspot"
    drag_drop = "drag_drop"
    code = "code"
    long_answer = "long_answer"


class QuestionMediaWrite(BaseModel):
    media_type: str = Field(pattern="^(image|audio|video|diagram)$")
    url: HttpUrl
    alt_text: str | None = Field(default=None, max_length=500)


class QuestionParameterWrite(BaseModel):
    minimum: float
    maximum: float
    step: float = Field(default=1, gt=0)

    @model_validator(mode="after")
    def validate_bounds(self):
        if not all(isfinite(value) for value in (self.minimum, self.maximum, self.step)):
            raise ValueError("Parameter bounds and step must be finite")
        if self.minimum > self.maximum:
            raise ValueError("Parameter minimum cannot exceed maximum")
        if (self.maximum - self.minimum) / self.step > 100000:
            raise ValueError("Parameter range is too large")
        return self


class QuestionOptionWrite(BaseModel):
    option_text: str = Field(min_length=1, max_length=2000)
    is_correct: bool = False
    media: list[QuestionMediaWrite] = Field(default_factory=list)
    feedback: str | None = Field(default=None, max_length=5000)

    @field_validator("option_text")
    @classmethod
    def option_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Option text cannot be empty")
        return value


class QuestionWrite(BaseModel):
    question_text: str = Field(min_length=1, max_length=10000)
    question_type: QuestionType
    points: int = Field(default=1, gt=0)
    position: int = Field(default=0, ge=0)
    image_url: HttpUrl | None = None
    options: list[QuestionOptionWrite] = Field(default_factory=list)
    accepted_answers: list[str] = Field(default_factory=list)
    answer_config: dict[str, Any] = Field(default_factory=dict)
    interaction_config: dict[str, Any] = Field(default_factory=dict)
    parameter_config: dict[str, QuestionParameterWrite] = Field(default_factory=dict)
    media: list[QuestionMediaWrite] = Field(default_factory=list)
    feedback: str | None = Field(default=None, max_length=5000)
    worked_solution: str | None = Field(default=None, max_length=20000)
    partial_credit: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=30)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    standard_code: str | None = Field(default=None, max_length=128)
    blooms_level: str | None = Field(
        default=None,
        pattern="^(remember|understand|apply|analyze|evaluate|create)$",
    )
    folder_path: str | None = Field(default=None, max_length=500)

    @field_validator("question_text")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question text cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_question_shape(self):
        if self.question_type == QuestionType.single_choice:
            if len(self.options) < 2 or sum(option.is_correct for option in self.options) != 1:
                raise ValueError("Single-choice questions require at least two options and one correct option")
            if self.accepted_answers:
                raise ValueError("Choice questions cannot include accepted text answers")
        elif self.question_type == QuestionType.multiple_choice:
            if len(self.options) < 2 or not any(option.is_correct for option in self.options):
                raise ValueError("Multiple-choice questions require at least two options and one or more correct options")
            if self.accepted_answers:
                raise ValueError("Choice questions cannot include accepted text answers")
        elif self.question_type == QuestionType.true_false:
            if len(self.options) != 2 or sum(option.is_correct for option in self.options) != 1:
                raise ValueError("True/false questions require two options and one correct option")
            if self.accepted_answers:
                raise ValueError("True/false questions cannot include accepted text answers")
        elif self.question_type in (QuestionType.fill_blank, QuestionType.short_answer):
            if self.options:
                raise ValueError("Text-answer questions cannot include options")
            if not self.accepted_answers or any(not answer.strip() for answer in self.accepted_answers):
                raise ValueError("Text-answer questions require non-empty accepted answers")
        elif self.question_type == QuestionType.numeric:
            if self.options:
                raise ValueError("Numeric questions cannot include options")
            if self.accepted_answers:
                raise ValueError("Numeric questions cannot include accepted text answers")
            correct_value = self.answer_config.get("correct_value")
            correct_expression = self.answer_config.get("correct_value_expression")
            tolerance = self.answer_config.get("tolerance", 0)
            has_value = (
                not isinstance(correct_value, (int, float))
                or isinstance(correct_value, bool)
                or not isfinite(correct_value)
            )
            if self.parameter_config and not isinstance(correct_expression, str):
                raise ValueError(
                    "Parameterized numeric questions require answer_config.correct_value_expression"
                )
            if not self.parameter_config and has_value:
                raise ValueError("Numeric questions require answer_config.correct_value")
            if (
                not isinstance(tolerance, (int, float))
                or isinstance(tolerance, bool)
                or not isfinite(tolerance)
                or tolerance < 0
            ):
                raise ValueError("Numeric tolerance cannot be negative")
            unit = self.answer_config.get("unit")
            if unit is not None and not isinstance(unit, str):
                raise ValueError("Numeric answer unit must be text")
        elif self.question_type in (
            QuestionType.matching,
            QuestionType.ordering,
            QuestionType.hotspot,
            QuestionType.drag_drop,
            QuestionType.code,
        ):
            if not self.answer_config:
                raise ValueError(f"{self.question_type.value} questions require answer_config")
            if (
                self.question_type != QuestionType.code
                and "correct_answer" not in self.answer_config
            ):
                raise ValueError(
                    f"{self.question_type.value} questions require answer_config.correct_answer"
                )
            if self.question_type == QuestionType.hotspot:
                target = self.answer_config["correct_answer"]
                if not isinstance(target, dict) or not all(
                    isinstance(target.get(axis), (int, float))
                    and not isinstance(target.get(axis), bool)
                    and isfinite(target[axis])
                    for axis in ("x", "y")
                ):
                    raise ValueError("Hotspot correct_answer must include finite x and y values")
                tolerance = self.answer_config.get("tolerance", 0)
                if (
                    not isinstance(tolerance, (int, float))
                    or isinstance(tolerance, bool)
                    or not isfinite(tolerance)
                    or tolerance < 0
                ):
                    raise ValueError("Hotspot tolerance must be a non-negative number")
        elif self.options or self.accepted_answers:
            raise ValueError("Long-answer questions cannot include options or accepted answers")
        if self.partial_credit:
            all_or_nothing = self.partial_credit.get("all_or_nothing", True)
            if not isinstance(all_or_nothing, bool):
                raise ValueError("partial_credit.all_or_nothing must be boolean")
            for key in ("per_correct_option", "penalty_per_incorrect_option"):
                value = self.partial_credit.get(key, 0)
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not isfinite(value)
                    or value < 0
                ):
                    raise ValueError(f"partial_credit.{key} must be a non-negative number")
        if self.parameter_config:
            if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in self.parameter_config):
                raise ValueError("Parameter names must be valid identifiers")
            referenced = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", self.question_text))
            if not referenced.intersection(self.parameter_config):
                raise ValueError("Question text must include at least one configured parameter")
            expression = self.answer_config.get("correct_value_expression")
            if expression is not None:
                if not isinstance(expression, str) or len(expression) > 256:
                    raise ValueError("Numeric answer expression must be a short string")
                try:
                    names = {
                        node.id
                        for node in ast.walk(ast.parse(expression, mode="eval"))
                        if isinstance(node, ast.Name)
                    }
                except SyntaxError as error:
                    raise ValueError("Numeric answer expression is not valid arithmetic") from error
                if not names.issubset(self.parameter_config):
                    raise ValueError("Numeric answer expression may only use configured parameters")
        return self


class QuestionRead(BaseModel):
    id: UUID
    quiz_id: UUID
    question_text: str
    question_type: QuestionType
    points: int
    position: int
    image_url: HttpUrl | None
    answer_config: dict[str, Any] = Field(default_factory=dict)
    interaction_config: dict[str, Any] = Field(default_factory=dict)
    parameter_config: dict[str, QuestionParameterWrite] = Field(default_factory=dict)
    media: list[QuestionMediaWrite] = Field(default_factory=list)
    feedback: str | None = None
    worked_solution: str | None = None
    partial_credit: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    difficulty: int | None = None
    standard_code: str | None = None
    blooms_level: str | None = None
    folder_path: str | None = None
    version: int = 1
    options: list["QuestionOptionRead"] = Field(default_factory=list)
    accepted_answers: list[str] = Field(default_factory=list)


class StudentQuestionRead(BaseModel):
    id: UUID
    question_text: str
    question_type: QuestionType
    points: int
    position: int
    image_url: HttpUrl | None
    section_id: UUID | None = None
    section_title: str | None = None
    section_instructions: str | None = None
    section_time_limit_minutes: int | None = None
    interaction_config: dict[str, Any] = Field(default_factory=dict)
    media: list[QuestionMediaWrite] = Field(default_factory=list)
    options: list["StudentQuestionOptionRead"] = Field(default_factory=list)


class QuestionOptionRead(BaseModel):
    id: UUID
    option_text: str
    is_correct: bool
    media: list[QuestionMediaWrite] = Field(default_factory=list)
    feedback: str | None = None


class StudentQuestionOptionRead(BaseModel):
    id: UUID
    option_text: str
    media: list[QuestionMediaWrite] = Field(default_factory=list)


class AttemptStartRead(BaseModel):
    id: UUID
    exam_session_id: UUID
    quiz_id: UUID
    started_at: datetime
    deadline_at: datetime
    status: str
    resumed: bool
    attempt_number: int = 1


class AttemptAnswerWrite(BaseModel):
    selected_option_ids: list[UUID] = Field(default_factory=list)
    text_answer: str | None = Field(default=None, max_length=20000)
    answer_data: dict[str, Any] = Field(default_factory=dict)


class AttemptAnswerRead(BaseModel):
    question_id: UUID
    selected_option_ids: list[UUID]
    text_answer: str | None
    answer_data: dict[str, Any] = Field(default_factory=dict)
    points_awarded: float | None = None
    grader_feedback: str | None = None
    worked_solution: str | None = None
    updated_at: datetime


class StudentAccommodationWrite(BaseModel):
    extra_time_percent: int = Field(default=0, ge=0, le=200)
    read_aloud: bool = False
    large_text: bool = False


class AttemptRead(BaseModel):
    id: UUID
    exam_session_id: UUID
    quiz_id: UUID
    quiz_title: str
    student_id: UUID | None = None
    student_name: str | None = None
    student_email: EmailStr | None = None
    attempt_number: int = 1
    started_at: datetime
    deadline_at: datetime
    status: str
    log_text: str | None
    score: float | None = None
    max_score: float | None = None
    graded_at: datetime | None = None
    grading_complete: bool = False
    accommodations: StudentAccommodationWrite = Field(default_factory=StudentAccommodationWrite)
    questions: list[StudentQuestionRead]
    answers: list[AttemptAnswerRead]


class AttemptLogUpdate(BaseModel):
    log_text: str | None = Field(default=None, max_length=100000)


class AttemptActivityCreate(BaseModel):
    event_type: str = Field(pattern="^(focus_lost|focus_returned|paste|copy|fullscreen_exit|heartbeat)$")
    details: dict[str, Any] = Field(default_factory=dict)


class ManualGradeWrite(BaseModel):
    points_awarded: float = Field(ge=0)
    feedback: str | None = Field(default=None, max_length=10000)


class QuestionRegradeResult(BaseModel):
    question_id: UUID
    attempts_regraded: int


class RubricCriterionWrite(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    max_points: float = Field(gt=0)


class RubricUpdate(BaseModel):
    criteria: list[RubricCriterionWrite] = Field(max_length=50)


class QuestionBankCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    institute_id: UUID | None = None


class BankQuestionCreate(BaseModel):
    question: QuestionWrite


class QuestionBankRead(BaseModel):
    id: UUID
    owner_id: UUID
    institute_id: UUID | None
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class QuestionBankItemRead(BaseModel):
    id: UUID
    bank_id: UUID
    question: QuestionWrite
    version: int
    created_at: datetime
    updated_at: datetime


class QuestionBankVersionRead(BaseModel):
    version: int
    question: dict[str, Any]
    created_at: datetime


class QuestionPoolPull(BaseModel):
    bank_id: UUID
    count: int = Field(gt=0, le=100)
    tags: list[str] = Field(default_factory=list, max_length=30)
    difficulty: int | None = Field(default=None, ge=1, le=5)


class QuestionImportRequest(BaseModel):
    format: str = Field(pattern="^(csv|json|qti)$")
    content: str = Field(min_length=1, max_length=5000000)


class QuizSectionWrite(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    position: int = Field(default=0, ge=0)
    instructions: str | None = Field(default=None, max_length=10000)
    time_limit_minutes: int | None = Field(default=None, gt=0)
    shuffle_questions: bool = False
    question_ids: list[UUID] = Field(default_factory=list)


class QuizSectionRead(QuizSectionWrite):
    id: UUID
    quiz_id: UUID
    question_ids: list[UUID] = Field(default_factory=list)


class QuizSectionsUpdate(BaseModel):
    sections: list[QuizSectionWrite] = Field(max_length=100)


class AttemptActivityRead(BaseModel):
    id: int
    event_type: str
    details: dict[str, Any]
    created_at: datetime


class AttemptGradeRead(BaseModel):
    attempt_id: UUID
    question_id: UUID
    points_awarded: float
    max_points: int
    grader_feedback: str | None
    graded_by: UUID | None
    graded_at: datetime | None


class QuizAnalyticsRead(BaseModel):
    question_id: UUID
    question_text: str
    response_count: int
    correct_count: int
    difficulty_index: float | None
    discrimination_index: float | None = None
    option_counts: dict[str, int] = Field(default_factory=dict)


class AttemptPolicyResult(BaseModel):
    exam_session_id: UUID
    attempts_used: int
    policy: str
    score_percent: float


class StudentPerformanceSummary(BaseModel):
    submitted_attempts: int
    graded_attempts: int
    pending_grading_attempts: int
    average_score_percent: float | None
    highest_score_percent: float | None
    latest_score_percent: float | None
    overall_accuracy_percent: float | None
    average_duration_seconds: float | None


class StudentPerformanceTrendPoint(BaseModel):
    attempt_id: UUID
    quiz_id: UUID
    quiz_title: str
    submitted_at: datetime
    attempt_number: int
    score: float
    max_score: float
    score_percent: float
    duration_seconds: float


class StudentPerformanceGroup(BaseModel):
    category: str
    attempt_count: int
    question_count: int
    earned_points: float
    possible_points: float
    accuracy_percent: float | None


class StudentQuizPerformance(BaseModel):
    quiz_id: UUID
    quiz_title: str
    attempt_count: int
    average_score_percent: float
    highest_score_percent: float
    latest_score_percent: float


class StudentScoreBucket(BaseModel):
    label: str
    minimum_percent: int
    maximum_percent: int
    attempt_count: int


class StudentPerformanceAnalytics(BaseModel):
    period_days: int
    summary: StudentPerformanceSummary
    score_trend: list[StudentPerformanceTrendPoint]
    score_distribution: list[StudentScoreBucket]
    quiz_performance: list[StudentQuizPerformance]
    subject_performance: list[StudentPerformanceGroup]
    skill_performance: list[StudentPerformanceGroup]
    standard_performance: list[StudentPerformanceGroup]
    blooms_level_performance: list[StudentPerformanceGroup]
    question_type_performance: list[StudentPerformanceGroup]
    difficulty_performance: list[StudentPerformanceGroup]