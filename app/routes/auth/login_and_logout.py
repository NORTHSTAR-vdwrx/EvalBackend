import secrets
from datetime import datetime, timedelta, timezone

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from db import get_db
from app.routes.auth.auth import auth_router
from models import PublicUserAccount
from app.routes.auth.security import SESSION_COOKIE, hash_token

ph = PasswordHasher()
DUMMY_HASH = ph.hash("not-a-real-password")
SESSION_TTL = timedelta(days=7)
COOKIE_SECURE = False  # Make this TRUE in PROD


class LoginRequest(BaseModel):
    username: str
    password: str


@auth_router.post("/login", response_model=PublicUserAccount)
async def login(
    data: LoginRequest,
    response: Response,
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, username, email, role, created_at, password_hash
            FROM users WHERE username = %s
            """,
            (data.username,),
        )
        user = await cur.fetchone()

    stored_hash = user["password_hash"] if user else DUMMY_HASH
    try:
        await run_in_threadpool(ph.verify, stored_hash, data.password)
    except VerifyMismatchError:
        user = None

    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_TTL

    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
            (hash_token(token), user["id"], expires_at),
        )

    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return PublicUserAccount(**user)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if session:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM sessions WHERE token_hash = %s", (hash_token(session),)
            )
    response.delete_cookie(SESSION_COOKIE, path="/")