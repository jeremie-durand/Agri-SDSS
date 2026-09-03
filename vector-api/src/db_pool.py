"""Shared asyncpg connection pool for custom vector-api routers."""

import os
from typing import Optional

import asyncpg

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASS"],
            host=os.environ["POSTGRES_HOST"],
            port=int(os.environ["POSTGRES_PORT"]),
            database=os.environ["POSTGRES_DBNAME"],
            min_size=2,
            max_size=5,
        )
    return _pool
