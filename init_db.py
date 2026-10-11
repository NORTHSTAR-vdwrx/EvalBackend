import os
from app.db import get_db_connection

def init_db():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
            with open(schema_path, 'r') as f:
                cur.execute(f.read())
            conn.commit()
        print("Database schema initialized successfully!")
    finally:
        conn.close()

if __name__ == '__main__':
    init_db()