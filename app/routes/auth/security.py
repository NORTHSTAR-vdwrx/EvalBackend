import hashlib

import psycopg
from fastapi import Cookie, Depends, HTTPException, status

from db import get_db
from models import PublicUserAccount, Role

SESSION_COOKIE = "session"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_current_user(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    conn: psycopg.AsyncConnection = Depends(get_db),
) -> PublicUserAccount:
    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT u.id, u.username, u.email, u.role, u.created_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = %s AND s.expires_at > NOW()
            """,
            (hash_token(session),),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return PublicUserAccount(**row)


def require_role(*roles: Role):
    async def checker(user: PublicUserAccount = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user
    return checker