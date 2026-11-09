from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from db import get_db
from models import ExtendedUserRead, ExtendedUserUpdate, ExtendedUserWrite, PublicUserAccount
from app.routes.auth.security import get_current_user, require_role
from models import Role


extended_users_router = APIRouter(prefix="/api/extended-users", tags=["extended users"])


@extended_users_router.get("/me", response_model=ExtendedUserRead)
async def get_my_extended_user(
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, acc_name, institute_id, institute_member_number, phone,
                   timezone, is_active, email_verified_at, last_login_at, updated_at
            FROM extended_users
            WHERE id = %s
            """,
            (user.id,),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Extended user profile not found. Create one with PUT /api/extended-users/me.",
        )
    return ExtendedUserRead(**row)


@extended_users_router.put(
    "/me",
    response_model=ExtendedUserRead,
    status_code=status.HTTP_200_OK,
)
async def upsert_my_extended_user(
    data: ExtendedUserWrite,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    acc_name = data.acc_name.strip()
    if not acc_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account name cannot be empty")
    async with conn.cursor() as cur:
        await cur.execute("SELECT id FROM institutes WHERE id = %s", (data.institute_id,))
        if await cur.fetchone() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Institute not found")

        try:
            await cur.execute(
                """
                INSERT INTO extended_users (
                    id, acc_name, institute_id, institute_member_number, phone, timezone
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    acc_name = EXCLUDED.acc_name,
                    institute_id = EXCLUDED.institute_id,
                    institute_member_number = EXCLUDED.institute_member_number,
                    phone = EXCLUDED.phone,
                    timezone = EXCLUDED.timezone,
                    updated_at = NOW()
                RETURNING id, acc_name, institute_id, institute_member_number, phone,
                          timezone, is_active, email_verified_at, last_login_at, updated_at
                """,
                (
                    user.id,
                    acc_name,
                    data.institute_id,
                    data.institute_member_number,
                    data.phone,
                    data.timezone,
                ),
            )
            row = await cur.fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Institute member number is already in use",
            )

    return ExtendedUserRead(**row)


@extended_users_router.patch("/me", response_model=ExtendedUserRead)
async def update_my_extended_user(
    data: ExtendedUserUpdate,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one field is required")
    if any(updates.get(field) is None for field in ("acc_name", "institute_id", "timezone")):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Account name, institute, and timezone cannot be null",
        )
    if "acc_name" in updates:
        updates["acc_name"] = updates["acc_name"].strip()
        if not updates["acc_name"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account name cannot be empty")

    async with conn.cursor() as cur:
        if "institute_id" in updates:
            await cur.execute(
                "SELECT id FROM institutes WHERE id = %s",
                (updates["institute_id"],),
            )
            if await cur.fetchone() is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Institute not found")

        assignments = ", ".join(f"{field} = %s" for field in updates)
        values = list(updates.values())
        try:
            await cur.execute(
                f"""
                UPDATE extended_users
                SET {assignments}, updated_at = NOW()
                WHERE id = %s
                RETURNING id, acc_name, institute_id, institute_member_number, phone,
                          timezone, is_active, email_verified_at, last_login_at, updated_at
                """,
                (*values, user.id),
            )
            row = await cur.fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Institute member number is already in use",
            )

    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Extended user profile not found")
    return ExtendedUserRead(**row)


@extended_users_router.get("", response_model=list[ExtendedUserRead])
async def list_extended_users(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    conn: psycopg.AsyncConnection = Depends(get_db),
    _: PublicUserAccount = Depends(require_role(Role.administrator)),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, acc_name, institute_id, institute_member_number, phone,
                   timezone, is_active, email_verified_at, last_login_at, updated_at
            FROM extended_users
            ORDER BY acc_name, id
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        rows = await cur.fetchall()
    return [ExtendedUserRead(**row) for row in rows]


@extended_users_router.get("/{user_id}", response_model=ExtendedUserRead)
async def get_extended_user(
    user_id: UUID,
    conn: psycopg.AsyncConnection = Depends(get_db),
    _: PublicUserAccount = Depends(require_role(Role.administrator)),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, acc_name, institute_id, institute_member_number, phone,
                   timezone, is_active, email_verified_at, last_login_at, updated_at
            FROM extended_users
            WHERE id = %s
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Extended user profile not found")
    return ExtendedUserRead(**row)


@extended_users_router.put("/{user_id}", response_model=ExtendedUserRead)
async def upsert_extended_user(
    user_id: UUID,
    data: ExtendedUserWrite,
    conn: psycopg.AsyncConnection = Depends(get_db),
    _: PublicUserAccount = Depends(require_role(Role.administrator)),
):
    acc_name = data.acc_name.strip()
    if not acc_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account name cannot be empty")
    async with conn.cursor() as cur:
        await cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if await cur.fetchone() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        await cur.execute("SELECT id FROM institutes WHERE id = %s", (data.institute_id,))
        if await cur.fetchone() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Institute not found")
        try:
            await cur.execute(
                """
                INSERT INTO extended_users (
                    id, acc_name, institute_id, institute_member_number, phone, timezone
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    acc_name = EXCLUDED.acc_name,
                    institute_id = EXCLUDED.institute_id,
                    institute_member_number = EXCLUDED.institute_member_number,
                    phone = EXCLUDED.phone,
                    timezone = EXCLUDED.timezone,
                    updated_at = NOW()
                RETURNING id, acc_name, institute_id, institute_member_number, phone,
                          timezone, is_active, email_verified_at, last_login_at, updated_at
                """,
                (
                    user_id,
                    acc_name,
                    data.institute_id,
                    data.institute_member_number,
                    data.phone,
                    data.timezone,
                ),
            )
            row = await cur.fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Institute member number is already in use",
            )
    return ExtendedUserRead(**row)


@extended_users_router.patch("/{user_id}", response_model=ExtendedUserRead)
async def update_extended_user(
    user_id: UUID,
    data: ExtendedUserUpdate,
    conn: psycopg.AsyncConnection = Depends(get_db),
    _: PublicUserAccount = Depends(require_role(Role.administrator)),
):
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one field is required")
    if any(value is None for value in updates.values()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Profile fields cannot be null")
    if "acc_name" in updates:
        updates["acc_name"] = updates["acc_name"].strip()
        if not updates["acc_name"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account name cannot be empty")

    async with conn.cursor() as cur:
        if "institute_id" in updates:
            await cur.execute("SELECT id FROM institutes WHERE id = %s", (updates["institute_id"],))
            if await cur.fetchone() is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Institute not found")
        assignments = ", ".join(f"{field} = %s" for field in updates)
        try:
            await cur.execute(
                f"""
                UPDATE extended_users
                SET {assignments}, updated_at = NOW()
                WHERE id = %s
                RETURNING id, acc_name, institute_id, institute_member_number, phone,
                          timezone, is_active, email_verified_at, last_login_at, updated_at
                """,
                (*updates.values(), user_id),
            )
            row = await cur.fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Institute member number is already in use",
            )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Extended user profile not found")
    return ExtendedUserRead(**row)


@extended_users_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_extended_user(
    user_id: UUID,
    conn: psycopg.AsyncConnection = Depends(get_db),
    _: PublicUserAccount = Depends(require_role(Role.administrator)),
):
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM extended_users WHERE id = %s RETURNING id",
            (user_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Extended user profile not found")
