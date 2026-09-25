"""Подключение к Postgres, миграции и advisory-блокировки."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import resources

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

MIGRATION_LOCK_KEY = 7_401_001
SHEET_LOCK_KEY = 7_401_002


class Db:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, url: str, *, max_size: int = 5) -> Db:
        pool = AsyncConnectionPool(
            url, min_size=1, max_size=max_size, open=False, kwargs={"row_factory": dict_row}
        )
        await pool.open(wait=True, timeout=30)
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    def connection(self):
        return self.pool.connection()


def migration_files() -> list[tuple[str, str]]:
    folder = resources.files("referrals.migrations")
    files = sorted((f for f in folder.iterdir() if f.name.endswith(".sql")), key=lambda f: f.name)
    return [(f.name.removesuffix(".sql"), f.read_text(encoding="utf-8")) for f in files]


async def migrate(url: str) -> list[str]:
    """Применяет новые SQL-файлы из referrals/migrations по порядку, каждый в своей транзакции."""
    applied: list[str] = []
    async with await psycopg.AsyncConnection.connect(url, autocommit=True, row_factory=dict_row) as conn:
        await conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
        try:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            cur = await conn.execute("SELECT version FROM schema_migrations")
            done = {row["version"] for row in await cur.fetchall()}
            for version, sql in migration_files():
                if version in done:
                    continue
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                applied.append(version)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
    return applied


@asynccontextmanager
async def advisory_lock(db: Db, key: int) -> AsyncIterator[bool]:
    """Неблокирующая сессионная блокировка Postgres: True — взяли, False — держит кто-то другой."""
    async with db.connection() as conn:
        cur = await conn.execute("SELECT pg_try_advisory_lock(%s) AS locked", (key,))
        locked = (await cur.fetchone())["locked"]
        await conn.commit()
        try:
            yield locked
        finally:
            if locked:
                await conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
                await conn.commit()
