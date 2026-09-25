import httpx
import pytest

from referrals import jobs, repo
from referrals.alerts import Alerter
from referrals.db import SHEET_LOCK_KEY, advisory_lock
from referrals.models import Session
from referrals.sheet_model import BOT_HEADERS, PHOTO_HEADER, SheetLayoutError
from tests.factories import EMP_A, EMP_B, EMP_C, make_draft, make_photo
from tests.fakes import FakeSheet
from tests.helpers import seed_employees, seed_referrer

HEADER = [*BOT_HEADERS, PHOTO_HEADER]


def collecting_alerter():
    sent = []

    async def send(text):
        sent.append(text)

    return Alerter(send), sent


async def create_referral(db, i=0):
    if await repo.get_referrer(db, 111) is None:
        await seed_referrer(db)
    draft = make_draft(phone=f"+1650253000{i}", email=f"c{i}@example.com")
    return await repo.create_referral(db, draft, make_photo(), Session(tg_user_id=111, step="menu"))


class FakeNotifier:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.sent = []
        self.reuploaded = []

    async def send_referral(self, referral):
        if referral.id == self.fail_on:
            raise RuntimeError("telegram down")
        self.sent.append(referral.id)

    async def reupload(self, referral, photo):
        self.reuploaded.append((referral.id, photo.sha256))
        return f"new-{referral.id}"


async def test_employee_sync_alerts_when_list_shrinks(db):
    await seed_employees(db, (EMP_A, "A A"), (EMP_B, "B B"), (EMP_C, "C C"))
    payload = {"employees": [{"id": EMP_A, "qr_data": EMP_A, "name": "A A"}]}
    alerter, sent = collecting_alerter()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as http:
        result = await jobs.run_employee_sync(db, http, "http://tabeli", alerter)
    assert result.skipped_deactivation
    assert len(sent) == 1 and "tabeli" in sent[0]


async def test_push_skips_when_locked_and_writes_pending(db):
    await create_referral(db)
    sheet = FakeSheet([HEADER])
    alerter, sent = collecting_alerter()
    async with advisory_lock(db, SHEET_LOCK_KEY):
        assert await jobs.run_sheet_sync(db, lambda: sheet, alerter, full=False) is None
    report = await jobs.run_sheet_sync(db, lambda: sheet, alerter, full=False)
    assert report.appended == 1

    def must_not_open():
        raise AssertionError("лист не должен открываться, если нечего писать")

    assert (await jobs.run_sheet_sync(db, must_not_open, alerter, full=False)).appended == 0
    assert sent == []


async def test_reconcile_alerts_about_unknown_rows(db):
    await create_referral(db)
    sheet = FakeSheet([HEADER, ["R-000777"]])
    alerter, sent = collecting_alerter()
    report = await jobs.run_sheet_sync(db, lambda: sheet, alerter, full=True)
    assert report.unknown_numbers == ["R-000777"]
    assert len(sent) == 1 and "R-000777" in sent[0]


async def test_push_does_not_alert_about_other_rows(db):
    await create_referral(db)
    sheet = FakeSheet([HEADER, ["R-000777"]])
    alerter, sent = collecting_alerter()
    await jobs.run_sheet_sync(db, lambda: sheet, alerter, full=False)
    assert sent == []


async def test_layout_error_alerts_and_raises(db):
    await create_referral(db)
    alerter, sent = collecting_alerter()
    with pytest.raises(SheetLayoutError):
        await jobs.run_sheet_sync(db, lambda: FakeSheet([["№"]]), alerter, full=True)
    assert any("Запись в таблицу остановлена" in m for m in sent)


async def test_notify_marks_sent_and_stops_on_failure(db):
    a = await create_referral(db, 0)
    b = await create_referral(db, 1)
    notifier = FakeNotifier(fail_on=b.id)
    with pytest.raises(RuntimeError):
        await jobs.run_notify(db, notifier)
    assert notifier.sent == [a.id]
    assert [r.id for r in await repo.referrals_pending_notify(db)] == [b.id]
    assert await jobs.run_notify(db, FakeNotifier()) == 1


async def test_reupload_replaces_file_id(db):
    created = await create_referral(db)
    async with db.connection() as conn:
        await conn.execute("UPDATE referrals SET created_at = now() - interval '2 days'")
    notifier = FakeNotifier()
    assert await jobs.run_reupload(db, notifier) == 1
    assert notifier.reuploaded == [(created.id, make_photo().sha256)]
    assert (await repo.all_referrals(db))[0].photo_file_id == f"new-{created.id}"
