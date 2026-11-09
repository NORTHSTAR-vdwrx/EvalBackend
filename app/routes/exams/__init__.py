from app.routes.exams.attempts import attempts_router
from app.routes.exams.scheduled import exam_sessions_router
from app.routes.exams.student_analytics import student_analytics_router

__all__ = ["attempts_router", "exam_sessions_router", "student_analytics_router"]
