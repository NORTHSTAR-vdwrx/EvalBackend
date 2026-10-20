import os

from db import get_sync_connection


def init_db() -> None:
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = f.read()

    with get_sync_connection() as conn: 
        with conn.cursor() as cur:
            cur.execute(schema)

    print("Database schema initialized successfully!")


if __name__ == "__main__":
    init_db()