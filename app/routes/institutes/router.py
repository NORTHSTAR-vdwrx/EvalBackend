from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from db import get_db
from models import InstituteCreate, InstituteRead, InstituteUpdate, PublicUserAccount, Role
from app.routes.auth.security import require_role


institutes_router = APIRouter(prefix="/api/institutes", tags=["institutes"])


@institutes_router.get("", response_model=list[InstituteRead])
async def list_institutes(conn: psycopg.AsyncConnection = Depends(get_db)):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, institute_name FROM institutes ORDER BY institute_name"
        )
        rows = await cur.fetchall()
    return [InstituteRead(**row) for row in rows]


@institutes_router.get("/{institute_id}", response_model=InstituteRead)
async def get_institute(
    institute_id: UUID,
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, institute_name FROM institutes WHERE id = %s",
            (institute_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Institute not found")
    return InstituteRead(**row)


@institutes_router.post(
    "",
    response_model=InstituteRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_institute(
    data: InstituteCreate,
    conn: psycopg.AsyncConnection = Depends(get_db),
    _: PublicUserAccount = Depends(require_role(Role.administrator)),
):
    institute_name = data.institute_name.strip()
    if not institute_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Institute name cannot be empty")
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO institutes (institute_name)
                VALUES (%s)
                RETURNING id, institute_name
                """,
                (institute_name,),
            )
            row = await cur.fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "Institute already exists")
    return InstituteRead(**row)


@institutes_router.patch("/{institute_id}", response_model=InstituteRead)
async def update_institute(
    institute_id: UUID,
    data: InstituteUpdate,
    conn: psycopg.AsyncConnection = Depends(get_db),
    _: PublicUserAccount = Depends(require_role(Role.administrator)),
):
    name = data.institute_name
    if name is None or not name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Institute name is required")

    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE institutes
                SET institute_name = %s
                WHERE id = %s
                RETURNING id, institute_name
                """,
                (name.strip(), institute_id),
            )
            row = await cur.fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "Institute already exists")
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Institute not found")
    return InstituteRead(**row)


@institutes_router.delete(
    "/{institute_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_institute(
    institute_id: UUID,
    conn: psycopg.AsyncConnection = Depends(get_db),
    _: PublicUserAccount = Depends(require_role(Role.administrator)),
):
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM institutes WHERE id = %s RETURNING id",
                (institute_id,),
            )
            row = await cur.fetchone()
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Institute is still associated with users or groups",
        )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Institute not found")
