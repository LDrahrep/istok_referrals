from datetime import timedelta

import psycopg
import pytest

from referrals import repo
from referrals.models import PhotoBlob, Session
from tests.factories import EMP_A, make_draft, make_photo
from tests.helpers import seed_referrer


def menu_session(tg_user_id: int = 111) -> Session:
    return Session(tg_user_id=tg_user_id, step="menu", language="ru")


async def count(db, table: str) -> int:
    async with db.connection() as conn:
        cur = await conn.execute(f"SELECT count(*) AS n FROM {table}")
        return (await cur.fetchone())["n"]


async def test_create_referral_stores_referral_photo_and_session(db):
    await seed_referrer(db)
    await repo.save_session(db, Session(tg_user_id=111, step="ref_confirm", data={"x": 1}))
    photo = make_photo()
    result = await repo.create_referral(db, make_draft(), photo, menu_session())
    assert result.created and result.number == "R-000001"
    assert await repo.get_photo(db, result.id) == photo
    assert (await repo.load_session(db, 111)).step == "menu"
    [referral] = await repo.all_referrals(db)
    assert (referral.phone, referral.referrer_emplid, referral.photo_kind, referral.hr_data) == (
        "+16502530000", EMP_A, "photo", {})


async def test_same_submission_key_creates_one_referral(db):
    await seed_referrer(db)
    draft = make_draft()
    first = await repo.create_referral(db, draft, make_photo(), menu_session())
    second = await repo.create_referral(db, draft, make_photo(), menu_session())
    assert (second.id, second.created) == (first.id, False)
    assert await count(db, "referrals") == 1
    assert await count(db, "referral_photos") == 1


async def test_duplicate_phone_rolls_back_everything(db):
    await seed_referrer(db)
    first = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    await repo.save_session(db, Session(tg_user_id=111, step="ref_confirm", data={"keep": True}))
    with pytest.raises(repo.DuplicateCandidate) as err:
        await repo.create_referral(db, make_draft(email="other@example.com"), make_photo(), menu_session())
    assert err.value.existing_id == first.id
    assert err.value.number == "R-000001"
    assert await count(db, "referrals") == 1
    assert await count(db, "referral_photos") == 1
    assert (await repo.load_session(db, 111)).data == {"keep": True}


async def test_duplicate_email_detected(db):
    await seed_referrer(db)
    first = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    with pytest.raises(repo.DuplicateCandidate) as err:
        await repo.create_referral(db, make_draft(phone="+16502530001"), make_photo(), menu_session())
    assert err.value.existing_id == first.id


async def test_find_by_phone_and_email(db):
    await seed_referrer(db)
    created = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    assert await repo.find_referral_by_phone(db, "+16502530000") == created.id
    assert await repo.find_referral_by_email(db, "aziz@example.com") == created.id
    assert await repo.find_referral_by_phone(db, "+16502530009") is None
    assert await repo.find_referral_by_email(db, "nobody@example.com") is None


async def test_sheet_sync_bookkeeping(db):
    await seed_referrer(db)
    a = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    b = await repo.create_referral(db, make_draft(phone="+16502530001", email="b@example.com"), make_photo(), menu_session())
    assert [r.id for r in await repo.referrals_pending_sheet(db)] == [a.id, b.id]
    await repo.mark_sheet_synced(db, [a.id])
    await repo.mark_sheet_synced(db, [])
    assert [r.id for r in await repo.referrals_pending_sheet(db)] == [b.id]


async def test_apply_sheet_feedback(db):
    await seed_referrer(db)
    created = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    await repo.apply_sheet_feedback(db, {created.id: ("https://drive/x", {"Статус": "Позвонили"})})
    [referral] = await repo.all_referrals(db)
    assert (referral.photo_url, referral.hr_data) == ("https://drive/x", {"Статус": "Позвонили"})


async def test_notify_bookkeeping(db):
    await seed_referrer(db)
    created = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    assert [r.id for r in await repo.referrals_pending_notify(db)] == [created.id]
    await repo.mark_notified(db, created.id)
    assert await repo.referrals_pending_notify(db) == []


async def test_stale_photos_and_file_id_update(db):
    await seed_referrer(db)
    a = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    b = await repo.create_referral(db, make_draft(phone="+16502530001", email="b@example.com"), make_photo(), menu_session())
    async with db.connection() as conn:
        await conn.execute("UPDATE referrals SET created_at = now() - interval '2 days'")
    await repo.apply_sheet_feedback(db, {b.id: ("https://drive/b", {})})
    assert [r.id for r in await repo.stale_photo_referrals(db, timedelta(hours=24))] == [a.id]
    await repo.update_photo_file_id(db, a.id, "new-file")
    assert (await repo.all_referrals(db))[0].photo_file_id == "new-file"


def test_photo_blob_rejects_empty():
    with pytest.raises(ValueError):
        PhotoBlob.from_bytes(b"", "image/jpeg")


async def test_photo_failure_rolls_back_referral(db):
    await seed_referrer(db)
    await repo.save_session(db, Session(tg_user_id=111, step="ref_confirm", data={"keep": True}))
    oversized = PhotoBlob.from_bytes(b"x" * (20 * 1024 * 1024 + 1), "image/jpeg")
    with pytest.raises(psycopg.errors.CheckViolation):
        await repo.create_referral(db, make_draft(), oversized, menu_session())
    assert await count(db, "referrals") == 0
    assert (await repo.load_session(db, 111)).data == {"keep": True}
