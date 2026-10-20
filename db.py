import os
from collections.abc import AsyncIterator

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

load_dotenv()

conninfo = make_conninfo(
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5432"),
)

pool = AsyncConnectionPool(
    conninfo,
    min_size=1,
    max_size=10,
    kwargs={"row_factory": dict_row}, 
    open=False,
)


async def get_db() -> AsyncIterator[psycopg.AsyncConnection]:
    """FastAPI dependency: borrows a connection and returns it to the pool."""
    async with pool.connection() as conn:
        yield conn


def get_sync_connection() -> psycopg.Connection:
    return psycopg.connect(conninfo)