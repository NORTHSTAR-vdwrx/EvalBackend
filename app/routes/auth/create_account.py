import psycopg
from argon2 import PasswordHasher
from fastapi import Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from db import get_db
from models import PublicUserAccount, UserCreate

from app.routes.auth.auth import auth_router

ph = PasswordHasher()


@auth_router.post("/create", response_model=PublicUserAccount, status_code=status.HTTP_201_CREATED)
async def create_account(data: UserCreate, conn: psycopg.AsyncConnection = Depends(get_db),
):
    password_hash = await run_in_threadpool(ph.hash, data.password)

    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO users (username, email, password_hash, role)
                VALUES (%s, %s, %s, 'student')
                RETURNING id, username, email, role, created_at
                """,
                (data.username, data.email, password_hash),
            )
            row = await cur.fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already in use",
        )

    return PublicUserAccount(**row)