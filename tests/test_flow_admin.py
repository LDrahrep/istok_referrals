from referrals import repo
from referrals.flow.admin import on_admin_button, on_unbind
from referrals.flow.admin_texts import referral_caption
from referrals.flow.steps import AUTH_WAIT_ID, MENU
from referrals.i18n import t
from referrals.models import Session
from tests.factories import EMP_A, EMP_B, make_referral
from tests.fakes import FakeIo
from tests.helpers import seed_employees

ADMINS = frozenset({7})
CARD = (-100, 555)


async def waiting_user(db, tg_user_id=111, language="en"):
    await repo.save_session(db, Session(tg_user_id=tg_user_id, step=AUTH_WAIT_ID, language=language,
                                        data={"fails": 3, "admin_card": [-100, 555]}))


async def test_non_admin_cannot_approve(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await waiting_user(db)
    io = FakeIo()
    await on_admin_button(db, io, 8, ADMINS, f"v:111:{EMP_A}", CARD)
    assert io.answered == ["Нет прав"]
    assert await repo.get_referrer(db, 111) is None


async def test_approve_binds_and_notifies_user(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await waiting_user(db)
    io = FakeIo()
    await on_admin_button(db, io, 7, ADMINS, f"v:111:{EMP_A}", CARD)
    assert (await repo.get_referrer(db, 111)).emplid == EMP_A
    assert [(tg, text) for tg, text, _ in io.user_messages] == [
        (111, t("en", "welcome", name="Ivan Petrov")), (111, t("en", "menu"))]
    assert io.admin_edits == [(CARD, f"✅ Подтверждено: Ivan Petrov ({EMP_A})")]
    session = await repo.load_session(db, 111)
    assert (session.step, session.data) == (MENU, {})


async def test_approve_when_already_verified(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await repo.bind_referrer(db, 111, EMP_A, None, "qr")
    io = FakeIo()
    await on_admin_button(db, io, 7, ADMINS, f"v:111:{EMP_A}", CARD)
    assert io.admin_edits == [(CARD, "Неактуально: сотрудник уже подтверждён.")]
    assert io.user_messages == []


async def test_approve_when_emplid_taken(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await repo.bind_referrer(db, 999, EMP_A, None, "qr")
    await waiting_user(db)
    io = FakeIo()
    await on_admin_button(db, io, 7, ADMINS, f"v:111:{EMP_A}", CARD)
    assert "уже привязан" in io.admin_edits[-1][1]
    assert await repo.get_referrer(db, 111) is None


async def test_reject_notifies_user_and_clears_card(db):
    await waiting_user(db)
    io = FakeIo()
    await on_admin_button(db, io, 7, ADMINS, "x:111", CARD)
    assert io.user_messages[-1][:2] == (111, t("en", "admin_rejected"))
    assert io.admin_edits == [(CARD, "❌ Отклонено")]
    assert "admin_card" not in (await repo.load_session(db, 111)).data


async def test_unbind(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await repo.bind_referrer(db, 111, EMP_A, None, "qr")
    await repo.save_session(db, Session(tg_user_id=111, step=MENU, language="ru"))
    io = FakeIo()
    await on_unbind(db, io, 8, ADMINS, (EMP_A,))
    assert io.replies == [] and await repo.get_referrer(db, 111) is not None
    await on_unbind(db, io, 7, ADMINS, ())
    assert io.last_text == "Формат: /unbind EMP-…"
    await on_unbind(db, io, 7, ADMINS, (EMP_B,))
    assert io.last_text == f"Привязки для {EMP_B} нет."
    await on_unbind(db, io, 7, ADMINS, (EMP_A,))
    assert io.last_text == f"Привязка снята: {EMP_A} (Telegram id 111)."
    assert await repo.get_referrer(db, 111) is None
    assert (await repo.load_session(db, 111)).step == AUTH_WAIT_ID


def test_referral_caption():
    caption = referral_caption(make_referral(7, worked_before=False))
    assert caption.splitlines() == [
        "🆕 Заявка R-000007",
        "Кандидат: Aziz Karimov",
        "Телефон: +16502530000",
        "Почта: aziz@example.com",
        "Работал у нас: Нет",
        f"Рекомендовал: Ivan Petrov ({EMP_A})",
    ]
