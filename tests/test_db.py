import psycopg
import pytest

from referrals.db import SHEET_LOCK_KEY, advisory_lock, migrate
from tests.factories import EMP_A

INSERT_REFERRAL = """
INSERT INTO referrals (submission_key, first_name, last_name, phone, email, worked_before,
    referrer_tg_user_id, referrer_emplid, referrer_name, photo_file_id, photo_kind)
VALUES (gen_random_uuid(), 'A', 'B', %s, %s, false, 1, %s, 'R', 'f', %s)
"""


async def test_migrate_is_idempotent(migrated_url):
    assert await migrate(migrated_url) == []


@pytest.mark.parametrize("phone,email,kind", [
    ("6502530000", "a@b.co", "photo"),
    ("+16502530000", "A@b.co", "photo"),
    ("+16502530000", "a@b.co", "video"),
])
async def test_referral_check_constraints(db, phone, email, kind):
    async with db.connection() as conn:
        await conn.execute("INSERT INTO employees (emplid, qr_data, name) VALUES (%s, %s, 'A')", (EMP_A, EMP_A))
    with pytest.raises(psycopg.errors.CheckViolation):
        async with db.connection() as conn:
            await conn.execute(INSERT_REFERRAL, (phone, email, EMP_A, kind))


async def test_advisory_lock_is_exclusive(db):
    async with advisory_lock(db, SHEET_LOCK_KEY) as first:
        async with advisory_lock(db, SHEET_LOCK_KEY) as second:
            assert first is True
            assert second is False
    async with advisory_lock(db, SHEET_LOCK_KEY) as again:
        assert again is True
