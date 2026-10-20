from fastapi import FastAPI

from app.routes.admin.settings import admin_router
from app.routes.auth.auth import auth_router
from app.routes.home import home_router
from app.routes.practice import practice_router


def create_app() -> FastAPI:
    app = FastAPI(title="NORTHSTAR Eval API")

    app.include_router(home_router)
    app.include_router(admin_router)
    app.include_router(practice_router)
    app.include_router(auth_router)
    return app