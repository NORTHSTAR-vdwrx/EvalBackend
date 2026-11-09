from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.admin.settings import admin_router
from app.routes.admin.users import admin_users_router
from app.routes.auth import auth_router
from app.routes.exams import (
    attempts_router,
    exam_sessions_router,
    student_analytics_router,
)
from app.routes.groups import groups_router
from app.routes.home import home_router
from app.routes.institutes import institutes_router
from app.routes.practice import practice_router
from app.routes.profiles import extended_users_router
from app.routes.quiz import (
    banks_router,
    imports_router,
    questions_router,
    quizzes_router,
    structure_router,
)
from db import pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open(wait=True)  
    yield
    await pool.close()


def create_app() -> FastAPI:
    app = FastAPI(title="NORTHSTAR Eval API", lifespan=lifespan)

    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(home_router)
    app.include_router(admin_router)
    app.include_router(admin_users_router)
    app.include_router(practice_router)
    app.include_router(auth_router)
    app.include_router(extended_users_router)
    app.include_router(institutes_router)
    app.include_router(groups_router)
    app.include_router(quizzes_router)
    app.include_router(exam_sessions_router)
    app.include_router(student_analytics_router)
    app.include_router(questions_router)
    app.include_router(banks_router)
    app.include_router(imports_router)
    app.include_router(structure_router)
    app.include_router(attempts_router)
    
    return app