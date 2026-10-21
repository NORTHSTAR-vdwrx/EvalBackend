from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.admin.settings import admin_router
from app.routes.auth import auth_router
from app.routes.home import home_router
from app.routes.practice import practice_router
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
    app.include_router(practice_router)
    app.include_router(auth_router)
    
    
    return app