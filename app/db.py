import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

def _connection_parameters() -> dict[str, str | None]:
    return {
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "host": os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "5432"),
    }


def get_db_connection() -> psycopg.Connection:
    return psycopg.connect(**_connection_parameters())


async def get_async_db_connection() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(**_connection_parameters())