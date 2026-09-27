from referrals import repo
from referrals.flow.admin import on_admin_button
from referrals.flow.events import Button, Command, Text, User
from referrals.flow.router import handle_event
from referrals.flow.steps import AUTH_WAIT_ID, MENU
from referrals.i18n import t
from referrals.models import Session
from tests.factories import EMP_A
from tests.fakes import FakeIo
from tests.helpers import seed_employees

USER = User(id=111, username="ivan", full_name="Ivan P")


async def verified(db, io, lang="ru"):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await handle_event(db, io, USER, Command("start"))
    await handle_event(db, io, USER, Button(f"lang:{lang}"))
    await handle_event(db, io, USER, Text(EMP_A))


async def test_keyboard_appears_after_verification(db):
    io = FakeIo()
    await verified(db, io)
    assert io.keyboards == [(t("ru", "welcome", name="Ivan Petrov"), [t("ru", "btn_cancel")])]


async def test_cancel_button_mid_form_cancels_draft(db):
    io = FakeIo()
    await verified(db, io)
    await handle_event(db, io, USER, Button("menu:refer"))
    await handle_event(db, io, USER, Text("Aziz"))
    await handle_event(db, io, USER, Text(t("ru", "btn_cancel")))
    assert t("ru", "cancelled") in io.texts() and io.last_text == t("ru", "menu")
    session = await repo.load_session(db, 111)
    assert (session.step, session.data) == (MENU, {})


async def test_cancel_button_in_menu_just_shows_menu(db):
    io = FakeIo()
    await verified(db, io)
    before = len(io.replies)
    await handle_event(db, io, USER, Text(t("ru", "btn_cancel")))
    assert [text for text, _ in io.replies[before:]] == [t("ru", "menu")]


async def test_cancel_label_of_other_language_works(db):
    io = FakeIo()
    await verified(db, io, lang="en")
    await handle_event(db, io, USER, Button("menu:refer"))
    await handle_event(db, io, USER, Text(t("ru", "btn_cancel")))
    assert t("en", "cancelled") in io.texts()


async def test_start_and_language_switch_resend_keyboard(db):
    io = FakeIo()
    await verified(db, io)
    await handle_event(db, io, USER, Command("start"))
    assert io.keyboards[-1] == (t("ru", "keyboard_hint"), [t("ru", "btn_cancel")])
    await handle_event(db, io, USER, Button("menu:language"))
    await handle_event(db, io, USER, Button("lang:en"))
    assert io.keyboards[-1] == (t("en", "keyboard_hint"), [t("en", "btn_cancel")])
    assert io.last_text == t("en", "menu")


async def test_cancel_button_for_unverified_user_returns_to_id_prompt(db):
    io = FakeIo()
    await handle_event(db, io, USER, Command("start"))
    await handle_event(db, io, USER, Button("lang:ru"))
    await handle_event(db, io, USER, Text(t("ru", "btn_cancel")))
    assert io.last_text == t("ru", "ask_id")
    assert (await repo.load_session(db, 111)).step == AUTH_WAIT_ID


async def test_admin_approval_sends_keyboard_to_user(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await repo.save_session(db, Session(tg_user_id=111, step=AUTH_WAIT_ID, language="ru"))
    io = FakeIo()
    await on_admin_button(db, io, 7, frozenset({7}), f"v:111:{EMP_A}", (-100, 1))
    assert io.user_keyboards == [(111, t("ru", "welcome", name="Ivan Petrov"), [t("ru", "btn_cancel")])]


async def test_cancel_on_language_step_returns_to_working_menu(db):
    io = FakeIo()
    await verified(db, io)
    await handle_event(db, io, USER, Button("menu:language"))
    await handle_event(db, io, USER, Text(t("ru", "btn_cancel")))
    assert io.last_text == t("ru", "menu")
    assert (await repo.load_session(db, 111)).step == MENU
    await handle_event(db, io, USER, Button("menu:refer"))
    assert io.last_text == t("ru", "ask_first_name")
