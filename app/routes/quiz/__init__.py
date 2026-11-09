from app.routes.quiz.questions import questions_router
from app.routes.quiz.crud import quizzes_router
from app.routes.quiz.banks import banks_router
from app.routes.quiz.import_export import imports_router
from app.routes.quiz.structure import structure_router

__all__ = [
    "questions_router",
    "quizzes_router",
    "banks_router",
    "imports_router",
    "structure_router",
]
