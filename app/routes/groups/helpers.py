from uuid import UUID

import psycopg

from models import PublicUserAccount


async def get_accessible_group(
    conn: psycopg.AsyncConnection,
    group_id: UUID,
    user: PublicUserAccount,
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT ug.id, ug.group_name, ug.is_public, ug.creating_teacher,
                   creator.username AS created_by_username, ug.institute_id,
                   ug.created_at,
                   COUNT(gm.user_id)::int AS member_count
            FROM user_groups ug
            JOIN users creator ON creator.id = ug.creating_teacher
            LEFT JOIN extended_users viewer_profile ON viewer_profile.id = %s
            LEFT JOIN group_members gm ON gm.group_id = ug.id
            WHERE ug.id = %s
              AND (
                  (ug.is_public AND viewer_profile.institute_id = ug.institute_id)
                  OR ug.creating_teacher = %s
                  OR %s = 'administrator'
                  OR EXISTS (
                      SELECT 1 FROM group_members membership
                      WHERE membership.group_id = ug.id AND membership.user_id = %s
                  )
              )
            GROUP BY ug.id, creator.username
            """,
            (user.id, group_id, user.id, user.role.value, user.id),
        )
        return await cur.fetchone()


async def can_manage_group(
    conn: psycopg.AsyncConnection,
    group_id: UUID,
    user: PublicUserAccount,
) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id FROM user_groups
            WHERE id = %s AND (creating_teacher = %s OR %s = 'administrator')
            """,
            (group_id, user.id, user.role.value),
        )
        return await cur.fetchone() is not None
