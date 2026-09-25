import asyncio
import os

import psycopg
import pytest
import pytest_asyncio

from referrals.db import Db, migrate

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:test@localhost:55432/postgres"
)
TABLES = "referral_photos, referrals, sessions, referrers, employees"


@pytest.fixture(scope="session")
def migrated_url() -> str:
    try:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute("DROP SCHEMA public CASCADE")
            conn.execute("CREATE SCHEMA public")
    except psycopg.OperationalError as exc:
        pytest.fail(
            f"Postgres для тестов недоступен ({exc}). Запустите: docker run -d --name "
            "referrals-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16-alpine"
        )
    asyncio.run(migrate(TEST_DATABASE_URL))
    return TEST_DATABASE_URL


@pytest_asyncio.fixture
async def db(migrated_url):
    database = await Db.connect(migrated_url, max_size=3)
    async with database.connection() as conn:
        await conn.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
    yield database
    await database.close()
