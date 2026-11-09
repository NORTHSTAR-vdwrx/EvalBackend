import psycopg
from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from uuid import UUID

from app.routes.auth.security import require_role
from db import get_db
from models import (
    AdminUserCreate,
    AdminUserDirectoryEntry,
    AdminUserUpdate,
    PublicUserAccount,
    Role,
)


admin_users_router = APIRouter(prefix="/api/admin/users", tags=["admin users"])
password_hasher = PasswordHasher()


@admin_users_router.get("", response_model=list[AdminUserDirectoryEntry])
async def list_users(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    conn: psycopg.AsyncConnection = Depends(get_db),
    _: PublicUserAccount = Depends(require_role(Role.administrator)),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT u.id, u.id AS user_id,
                   COALESCE(eu.acc_name, u.username) AS name,
                   u.username, u.email, u.role, u.created_at,
                   eu.acc_name, eu.institute_id, eu.institute_member_number,
                   eu.phone, eu.timezone
            FROM users u
            LEFT JOIN extended_users eu ON eu.id = u.id
            ORDER BY u.created_at DESC, u.id
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        rows = await cur.fetchall()
    return [AdminUserDirectoryEntry(**row) for row in rows]


@admin_users_router.get("/{user_id}", response_model=AdminUserDirectoryEntry)
async def get_user(
    user_id: UUID,
    conn: psycopg.AsyncConnection = Depends(get_db),
    _: PublicUserAccount = Depends(require_role(Role.administrator)),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT u.id, u.id AS user_id,
                   COALESCE(eu.acc_name, u.username) AS name,
                   u.username, u.email, u.role, u.created_at,
                   eu.acc_name, eu.institute_id, eu.institute_member_number,
                   eu.phone, eu.timezone
            FROM users u
            LEFT JOIN extended_users eu ON eu.id = u.id
            WHERE u.id = %s
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return AdminUserDirectoryEntry(**row)


@admin_users_router.post(
    "",
    response_model=PublicUserAccount,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    data: AdminUserCreate,
    conn: psycopg.AsyncConnection = Depends(get_db),
    _: PublicUserAccount = Depends(require_role(Role.administrator)),
):
    username = data.username.strip()
    if not username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Username cannot be empty")
    password_hash = await run_in_threadpool(password_hasher.hash, data.password)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO users (username, email, password_hash, role)
                VALUES (%s, %s, %s, %s)
                RETURNING id, username, email, role, created_at
                """,
                (username, data.email, password_hash, data.role.value),
            )
            row = await cur.fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already in use")
    return PublicUserAccount(**row)


@admin_users_router.patch("/{user_id}", response_model=PublicUserAccount)
async def update_user(
    user_id: UUID,
    data: AdminUserUpdate,
    admin: PublicUserAccount = Depends(require_role(Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one field is required")
    if any(value is None for value in updates.values()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User fields cannot be null")
    if "username" in updates:
        updates["username"] = updates["username"].strip()
        if not updates["username"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Username cannot be empty")
    if user_id == admin.id and updates.get("role") not in (None, Role.administrator):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Administrators cannot remove their own administrator role",
        )
    if "role" in updates:
        updates["role"] = updates["role"].value

    assignments = ", ".join(f"{field} = %s" for field in updates)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                UPDATE users
                SET {assignments}
                WHERE id = %s
                RETURNING id, username, email, role, created_at
                """,
                (*updates.values(), user_id),
            )
            row = await cur.fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already in use")
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return PublicUserAccount(**row)


@admin_users_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    admin: PublicUserAccount = Depends(require_role(Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Administrators cannot delete their own account",
        )
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
