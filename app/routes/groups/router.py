from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from db import get_db
from app.routes.groups.helpers import can_manage_group, get_accessible_group
from models import (
    GroupCreate,
    GroupMemberCreate,
    GroupMemberRead,
    GroupRead,
    GroupStudentSearchResult,
    GroupUpdate,
    PublicUserAccount,
    Role,
)
from app.routes.auth.security import get_current_user, require_role


groups_router = APIRouter(prefix="/api/groups", tags=["groups"])


@groups_router.get("/students", response_model=list[GroupStudentSearchResult])
async def search_institute_students(
    search: str = Query(min_length=2, max_length=255),
    limit: int = Query(default=30, ge=1, le=100),
    user: PublicUserAccount = Depends(require_role(Role.teacher)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    term = search.strip()
    if len(term) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Search must contain at least two characters")

    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT institute_id FROM extended_users WHERE id = %s",
            (user.id,),
        )
        profile = await cur.fetchone()
        if profile is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Create an extended user profile before searching for students",
            )

        pattern = f"%{term}%"
        await cur.execute(
            """
            SELECT u.id AS user_id, eu.acc_name, u.username, u.email,
                   eu.institute_member_number
            FROM users u
            JOIN extended_users eu ON eu.id = u.id
            WHERE eu.institute_id = %s
              AND u.role = 'student'
              AND (
                  eu.acc_name ILIKE %s
                  OR u.username ILIKE %s
                  OR u.email ILIKE %s
                  OR COALESCE(eu.institute_member_number, '') ILIKE %s
              )
            ORDER BY eu.acc_name, u.username
            LIMIT %s
            """,
            (profile["institute_id"], pattern, pattern, pattern, pattern, limit),
        )
        rows = await cur.fetchall()
    return [GroupStudentSearchResult(**row) for row in rows]


@groups_router.get("", response_model=list[GroupRead])
async def list_groups(
    created_by_me: bool = Query(default=False),
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        if created_by_me:
            await cur.execute(
                """
                SELECT ug.id, ug.group_name, ug.is_public, ug.creating_teacher,
                       creator.username AS created_by_username, ug.institute_id,
                       ug.created_at, COUNT(gm.user_id)::int AS member_count
                FROM user_groups ug
                JOIN users creator ON creator.id = ug.creating_teacher
                LEFT JOIN group_members gm ON gm.group_id = ug.id
                WHERE ug.creating_teacher = %s
                GROUP BY ug.id, creator.username
                ORDER BY ug.created_at DESC
                """,
                (user.id,),
            )
        else:
            await cur.execute(
                """
                SELECT ug.id, ug.group_name, ug.is_public, ug.creating_teacher,
                       creator.username AS created_by_username, ug.institute_id,
                       ug.created_at, COUNT(gm.user_id)::int AS member_count
                FROM user_groups ug
                JOIN users creator ON creator.id = ug.creating_teacher
                LEFT JOIN extended_users viewer_profile ON viewer_profile.id = %s
                LEFT JOIN group_members gm ON gm.group_id = ug.id
                WHERE (ug.is_public AND viewer_profile.institute_id = ug.institute_id)
                   OR ug.creating_teacher = %s
                   OR %s = 'administrator'
                   OR EXISTS (
                       SELECT 1 FROM group_members membership
                       WHERE membership.group_id = ug.id AND membership.user_id = %s
                   )
                GROUP BY ug.id, creator.username
                ORDER BY ug.created_at DESC
                """,
                (user.id, user.id, user.role.value, user.id),
            )
        rows = await cur.fetchall()
    return [GroupRead(**row) for row in rows]


@groups_router.post("", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(
    data: GroupCreate,
    user: PublicUserAccount = Depends(require_role(Role.teacher, Role.administrator)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    group_name = data.group_name.strip()
    if not group_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Group name cannot be empty")
    async with conn.cursor() as cur:
        if user.role == Role.administrator:
            institute_id = data.institute_id
            if institute_id is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Administrators must provide an institute_id",
                )
            await cur.execute("SELECT id FROM institutes WHERE id = %s", (institute_id,))
            if await cur.fetchone() is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Institute not found")
        else:
            await cur.execute(
                "SELECT institute_id FROM extended_users WHERE id = %s",
                (user.id,),
            )
            profile = await cur.fetchone()
            if profile is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Create an extended user profile before creating a group",
                )
            institute_id = profile["institute_id"]
            if data.institute_id is not None and data.institute_id != institute_id:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "Teachers can only create groups in their profile institute",
                )
        await cur.execute(
            """
            INSERT INTO user_groups (group_name, is_public, creating_teacher, institute_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id, group_name, is_public, creating_teacher, institute_id, created_at
            """,
            (group_name, data.is_public, user.id, institute_id),
        )
        row = await cur.fetchone()
        row["created_by_username"] = user.username
        row["member_count"] = 0
    return GroupRead(**row)


@groups_router.get("/{group_id}", response_model=GroupRead)
async def get_group(
    group_id: UUID,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    row = await get_accessible_group(conn, group_id, user)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return GroupRead(**row)


@groups_router.get("/{group_id}/members", response_model=list[GroupMemberRead])
async def list_group_members(
    group_id: UUID,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    group = await get_accessible_group(conn, group_id, user)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    if user.role != Role.administrator and user.id != group["creating_teacher"]:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM group_members WHERE group_id = %s AND user_id = %s",
                (group_id, user.id),
            )
            if await cur.fetchone() is None:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Group membership required")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT u.id AS user_id, u.username, u.email, u.role, gm.added_at
            FROM group_members gm
            JOIN users u ON u.id = gm.user_id
            WHERE gm.group_id = %s
            ORDER BY gm.added_at
            """,
            (group_id,),
        )
        rows = await cur.fetchall()
    return [GroupMemberRead(**row) for row in rows]


@groups_router.post(
    "/{group_id}/members",
    response_model=GroupMemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_group_member(
    group_id: UUID,
    data: GroupMemberCreate,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_group(conn, group_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT u.id, u.username, u.email, u.role, eu.institute_id
            FROM users u
            LEFT JOIN extended_users eu ON eu.id = u.id
            WHERE u.id = %s
            """,
            (data.user_id,),
        )
        target = await cur.fetchone()
        if target is None or target["role"] != Role.student or target["institute_id"] is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Student with an institute profile not found")
        await cur.execute(
            "SELECT institute_id FROM user_groups WHERE id = %s",
            (group_id,),
        )
        group = await cur.fetchone()
        if group is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
        if target["institute_id"] != group["institute_id"]:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Student and group must belong to the same institute",
            )
        try:
            await cur.execute(
                """
                INSERT INTO group_members (group_id, user_id)
                VALUES (%s, %s)
                RETURNING added_at
                """,
                (group_id, data.user_id),
            )
            membership = await cur.fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(status.HTTP_409_CONFLICT, "Student is already in this group")
    return GroupMemberRead(
        user_id=target["id"],
        username=target["username"],
        email=target["email"],
        role=target["role"],
        added_at=membership["added_at"],
    )


@groups_router.post(
    "/{group_id}/join",
    response_model=GroupMemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def join_public_group(
    group_id: UUID,
    user: PublicUserAccount = Depends(require_role(Role.student)),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT ug.institute_id, ug.is_public, eu.institute_id AS user_institute_id
            FROM user_groups ug
            LEFT JOIN extended_users eu ON eu.id = %s
            WHERE ug.id = %s
            """,
            (user.id, group_id),
        )
        row = await cur.fetchone()
        if row is None or not row["is_public"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Public group not found")
        if row["user_institute_id"] is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Create an extended user profile before joining a group",
            )
        if row["user_institute_id"] != row["institute_id"]:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Student and group must belong to the same institute",
            )
        try:
            await cur.execute(
                """
                INSERT INTO group_members (group_id, user_id)
                VALUES (%s, %s)
                RETURNING added_at
                """,
                (group_id, user.id),
            )
            membership = await cur.fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(status.HTTP_409_CONFLICT, "Already a member of this group")
    return GroupMemberRead(
        user_id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        added_at=membership["added_at"],
    )


@groups_router.delete("/{group_id}/members/me", status_code=status.HTTP_204_NO_CONTENT)
async def leave_group(
    group_id: UUID,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM group_members WHERE group_id = %s AND user_id = %s RETURNING user_id",
            (group_id, user.id),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group membership not found")


@groups_router.delete(
    "/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_group_member(
    group_id: UUID,
    user_id: UUID,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_group(conn, group_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM group_members WHERE group_id = %s AND user_id = %s RETURNING user_id",
            (group_id, user_id),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group membership not found")


@groups_router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: UUID,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    if not await can_manage_group(conn, group_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM user_groups WHERE id = %s RETURNING id", (group_id,))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")


@groups_router.patch("/{group_id}", response_model=GroupRead)
async def update_group(
    group_id: UUID,
    data: GroupUpdate,
    user: PublicUserAccount = Depends(get_current_user),
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one field is required")
    if any(value is None for value in updates.values()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Group fields cannot be null")
    if "group_name" in updates:
        updates["group_name"] = updates["group_name"].strip()
        if not updates["group_name"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Group name cannot be empty")
    if not await can_manage_group(conn, group_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")

    assignments = ", ".join(f"{field} = %s" for field in updates)
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            UPDATE user_groups
            SET {assignments}
            WHERE id = %s
            RETURNING id, group_name, is_public, creating_teacher, institute_id, created_at
            """,
            (*updates.values(), group_id),
        )
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
        await cur.execute(
            """
            SELECT username FROM users WHERE id = %s
            """,
            (row["creating_teacher"],),
        )
        creator = await cur.fetchone()
        row["created_by_username"] = creator["username"]
        await cur.execute(
            "SELECT COUNT(*)::int AS member_count FROM group_members WHERE group_id = %s",
            (group_id,),
        )
        row["member_count"] = (await cur.fetchone())["member_count"]
    return GroupRead(**row)
