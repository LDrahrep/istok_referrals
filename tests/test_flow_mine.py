from referrals import repo
from referrals.flow.events import Button, Text, User
from referrals.flow.router import handle_event
from referrals.flow.steps import MENU, REF_LAST_NAME
from referrals.i18n import t
from referrals.models import Session
from tests.factories import EMP_B, make_draft, make_photo
from tests.fakes import FakeIo, FakeSheetReader
from tests.helpers import seed_referrer

USER = User(id=111, username="ivan", full_name="Ivan P")


async def setup(db):
    await seed_referrer(db)
    await seed_referrer(db, tg_user_id=222, emplid=EMP_B, name="Other Person")
    await repo.save_session(db, Session(tg_user_id=111, step=MENU, language="ru"))
    a = await repo.create_referral(db, make_draft(), make_photo(), Session(tg_user_id=111, step=MENU, language="ru"))
    foreign = make_draft(phone="+16502530001", email="o@example.com", referrer_tg_user_id=222,
                         referrer_emplid=EMP_B, referrer_name="Other Person")
    b = await repo.create_referral(db, foreign, make_photo(), Session(tg_user_id=222, step=MENU))
    c = await repo.create_referral(db, make_draft(phone="+16502530002", email="c@example.com"), make_photo(),
                                   Session(tg_user_id=111, step=MENU, language="ru"))
    return a, b, c


async def press(db, io, data, sheet=None):
    await handle_event(db, io, USER, Button(data), sheet=sheet)


async def test_list_shows_only_own_referrals_newest_first(db):
    a, _, c = await setup(db)
    io = FakeIo()
    await press(db, io, "menu:mine")
    assert io.last_text == t("ru", "mine_title")
    assert io.button_data() == [f"my:show:{c.id}", f"my:show:{a.id}", "my:menu"]
    labels = [label for row in io.replies[-1][1] for label, _ in row]
    assert labels[0].startswith("R-000003 · Aziz Karimov · ")


async def test_empty_list(db):
    await seed_referrer(db)
    await repo.save_session(db, Session(tg_user_id=111, step=MENU, language="ru"))
    io = FakeIo()
    await press(db, io, "menu:mine")
    assert t("ru", "mine_empty") in io.texts() and io.last_text == t("ru", "menu")


async def test_card_shows_data_but_no_hr_status(db):
    a, _, _ = await setup(db)
    await repo.apply_sheet_feedback(db, {a.id: (None, {"Статус": "Интервью"})})
    io = FakeIo()
    await press(db, io, f"my:show:{a.id}")
    assert "+16502530000" in io.last_text and "Интервью" not in io.last_text
    assert io.button_data() == [f"my:withdraw:{a.id}", "my:list"]


async def test_foreign_and_garbage_buttons_are_stale(db):
    _, b, _ = await setup(db)
    for data in (f"my:show:{b.id}", f"my:confirm:{b.id}", "my:show:abc", "my:explode:1", "my:confirm:999"):
        io = FakeIo()
        await press(db, io, data, sheet=FakeSheetReader())
        assert io.replies[0][0] == t("ru", "stale_button")
    assert (await repo.get_referral(db, b.id)).withdrawn_at is None


async def test_withdraw_flow(db):
    a, _, _ = await setup(db)
    io = FakeIo()
    sheet = FakeSheetReader({"R-000001": ""})
    await press(db, io, f"my:withdraw:{a.id}", sheet)
    assert io.last_text == t("ru", "withdraw_confirm", number="R-000001")
    assert io.button_data() == [f"my:confirm:{a.id}", f"my:show:{a.id}"]
    await press(db, io, f"my:confirm:{a.id}", sheet)
    assert t("ru", "withdrawn_done", number="R-000001") in io.texts()
    assert io.admin_messages[-1][0] == "↩️ Заявка R-000001 (Aziz Karimov) отозвана рекомендателем Ivan Petrov"
    assert io.kicks == 1 and sheet.calls == ["R-000001"]
    assert (await repo.get_referral(db, a.id)).withdrawn_at is not None
    labels = [label for row in io.replies[-1][1] for label, _ in row]
    assert labels[1].endswith("· отозвана")
    await press(db, io, f"my:confirm:{a.id}", sheet)
    assert t("ru", "already_withdrawn", number="R-000001") in io.texts()


async def test_withdraw_blocked_by_hr_status(db):
    a, _, _ = await setup(db)
    io = FakeIo()
    await press(db, io, f"my:confirm:{a.id}", FakeSheetReader({"R-000001": "Интервью"}))
    assert t("ru", "withdraw_blocked") in io.texts()
    assert not any("Интервью" in text for text in io.texts())
    assert (await repo.get_referral(db, a.id)).withdrawn_at is None
    assert io.admin_messages == []


async def test_withdraw_falls_back_to_db_copy_when_sheet_down(db):
    a, _, c = await setup(db)
    await repo.apply_sheet_feedback(db, {a.id: (None, {"Статус": "Позвонили"})})
    io = FakeIo()
    await press(db, io, f"my:confirm:{a.id}", FakeSheetReader(fail=True))
    assert t("ru", "withdraw_blocked") in io.texts()
    await press(db, io, f"my:confirm:{c.id}", FakeSheetReader(fail=True))
    assert (await repo.get_referral(db, c.id)).withdrawn_at is not None


async def test_candidate_can_be_referred_again_after_withdrawal(db):
    a, _, _ = await setup(db)
    io = FakeIo()
    await press(db, io, f"my:confirm:{a.id}", FakeSheetReader())
    await press(db, io, "menu:refer")
    for text in ("Aziz", "Karimov", "(650) 253-0000"):
        await handle_event(db, io, USER, Text(text))
    assert io.last_text == t("ru", "ask_email")


async def test_my_button_mid_form_is_stale(db):
    await setup(db)
    io = FakeIo()
    await press(db, io, "menu:refer")
    await handle_event(db, io, USER, Text("Aziz"))
    await press(db, io, "my:list")
    assert io.replies[-2][0] == t("ru", "stale_button")
    assert io.last_text == t("ru", "ask_last_name")
    session = await repo.load_session(db, 111)
    assert session.step == REF_LAST_NAME and session.data == {"first_name": "Aziz"}


async def test_hanging_sheet_read_falls_back_to_db_copy(db, monkeypatch):
    import time

    from referrals.flow import mine
    monkeypatch.setattr(mine, "HR_STATUS_TIMEOUT", 0.05)
    a, _, c = await setup(db)
    await repo.apply_sheet_feedback(db, {a.id: (None, {"Статус": "Позвонили"})})
    io = FakeIo()
    started = time.monotonic()
    await press(db, io, f"my:confirm:{a.id}", FakeSheetReader({"R-000001": ""}, delay=5))
    await press(db, io, f"my:confirm:{c.id}", FakeSheetReader({"R-000003": ""}, delay=5))
    assert time.monotonic() - started < 2
    assert t("ru", "withdraw_blocked") in io.texts()
    assert (await repo.get_referral(db, a.id)).withdrawn_at is None
    assert (await repo.get_referral(db, c.id)).withdrawn_at is not None
