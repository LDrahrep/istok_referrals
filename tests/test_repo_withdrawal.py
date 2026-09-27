from datetime import timedelta

import psycopg
import pytest

from referrals import repo
from referrals.db import migrate, migration_files
from referrals.models import Session, WithdrawResult
from tests.factories import EMP_A, EMP_B, make_draft, make_photo
from tests.helpers import seed_referrer


def menu_session(tg_user_id: int = 111) -> Session:
    return Session(tg_user_id=tg_user_id, step="menu", language="ru")


async def test_withdraw_releases_phone_and_email(db):
    await seed_referrer(db)
    first = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    assert await repo.withdraw_referral(db, first.id, EMP_A) is WithdrawResult.WITHDRAWN
    assert await repo.find_referral_by_phone(db, "+16502530000") is None
    assert await repo.find_referral_by_email(db, "aziz@example.com") is None
    second = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    assert second.created and second.id != first.id
    with pytest.raises(repo.DuplicateCandidate) as err:
        await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    assert err.value.existing_id == second.id


async def test_withdraw_outcomes(db):
    await seed_referrer(db)
    await seed_referrer(db, tg_user_id=222, emplid=EMP_B, name="Other Person")
    created = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    assert await repo.withdraw_referral(db, created.id, EMP_B) is WithdrawResult.NOT_FOUND
    assert await repo.withdraw_referral(db, 999, EMP_A) is WithdrawResult.NOT_FOUND
    assert await repo.withdraw_referral(db, created.id, EMP_A) is WithdrawResult.WITHDRAWN
    assert await repo.withdraw_referral(db, created.id, EMP_A) is WithdrawResult.ALREADY


async def test_withdraw_marks_referral_for_sheet_sync(db):
    await seed_referrer(db)
    created = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    await repo.mark_sheet_synced(db, [created.id])
    await repo.withdraw_referral(db, created.id, EMP_A)
    [pending] = await repo.referrals_pending_sheet(db)
    assert pending.id == created.id and pending.withdrawn_at is not None


async def test_list_and_get(db):
    await seed_referrer(db)
    await seed_referrer(db, tg_user_id=222, emplid=EMP_B, name="Other Person")
    a = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    other = make_draft(phone="+16502530001", email="o@example.com", referrer_tg_user_id=222,
                       referrer_emplid=EMP_B, referrer_name="Other Person")
    await repo.create_referral(db, other, make_photo(), menu_session(222))
    c = await repo.create_referral(db, make_draft(phone="+16502530002", email="c@example.com"), make_photo(), menu_session())
    assert [r.id for r in await repo.list_referrals_by_referrer(db, EMP_A)] == [c.id, a.id]
    assert [r.id for r in await repo.list_referrals_by_referrer(db, EMP_A, limit=1)] == [c.id]
    assert (await repo.get_referral(db, a.id)).phone == "+16502530000"
    assert await repo.get_referral(db, 999) is None


async def test_stale_photos_skip_withdrawn(db):
    await seed_referrer(db)
    created = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    async with db.connection() as conn:
        await conn.execute("UPDATE referrals SET created_at = now() - interval '2 days'")
    await repo.withdraw_referral(db, created.id, EMP_A)
    assert await repo.stale_photo_referrals(db, timedelta(hours=24)) == []


async def test_migration_002_on_existing_data(migrated_url):
    base, _ = migrated_url.rsplit("/", 1)
    with psycopg.connect(migrated_url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS mig_002_test")
        admin.execute("CREATE DATABASE mig_002_test")
    url = f"{base}/mig_002_test"
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("CREATE TABLE schema_migrations (version text PRIMARY KEY, "
                         "applied_at timestamptz NOT NULL DEFAULT now())")
            conn.execute(dict(migration_files())["001_init"])
            conn.execute("INSERT INTO schema_migrations (version) VALUES ('001_init')")
            conn.execute("INSERT INTO employees (emplid, qr_data, name) VALUES (%s, %s, 'A')", (EMP_A, EMP_A))
            conn.execute(
                "INSERT INTO referrals (submission_key, first_name, last_name, phone, email, worked_before, "
                "referrer_tg_user_id, referrer_emplid, referrer_name, photo_file_id, photo_kind) "
                "VALUES (gen_random_uuid(), 'A', 'B', '+16502530000', 'a@b.co', false, 1, %s, 'R', 'f', 'photo')",
                (EMP_A,))
        assert await migrate(url) == ["002_withdrawal"]
        with psycopg.connect(url) as conn:
            assert conn.execute("SELECT withdrawn_at FROM referrals").fetchone() == (None,)
    finally:
        with psycopg.connect(migrated_url, autocommit=True) as admin:
            admin.execute("DROP DATABASE IF EXISTS mig_002_test")
