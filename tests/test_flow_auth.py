from referrals import repo
from referrals.flow.admin_texts import CARD_OBSOLETE
from referrals.flow.events import Button, Command, Document, Other, Photo, Text, User
from referrals.flow.router import handle_event
from referrals.flow.steps import AUTH_WAIT_ID, MENU, REF_LAST_NAME
from referrals.i18n import t
from tests.factories import EMP_A, EMP_B
from tests.fakes import FakeIo
from tests.helpers import seed_employees
from tests.qr_images import blank_photo_jpeg, qr_photo_jpeg

USER = User(id=111, username="ivan", full_name="Ivan P")


async def start_ru(db, io, user=USER):
    await handle_event(db, io, user, Command("start"))
    await handle_event(db, io, user, Button("lang:ru"))


async def verify_method(db, tg_user_id: int) -> str:
    async with db.connection() as conn:
        cur = await conn.execute("SELECT verify_method FROM referrers WHERE tg_user_id = %s", (tg_user_id,))
        return (await cur.fetchone())["verify_method"]


async def test_new_user_gets_language_then_id_prompt(db):
    io = FakeIo()
    await handle_event(db, io, USER, Command("start"))
    assert io.last_text == t(None, "choose_language")
    assert io.button_data() == ["lang:ru", "lang:en"]
    await handle_event(db, io, USER, Text("привет"))
    assert io.last_text == t(None, "choose_language")
    await handle_event(db, io, USER, Button("lang:ru"))
    assert io.last_text == t("ru", "ask_id")
    assert (await repo.load_session(db, 111)).step == AUTH_WAIT_ID


async def test_text_id_verifies(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(f"мой id {EMP_A.upper()}"))
    assert t("ru", "welcome", name="Ivan Petrov") in io.texts()
    assert io.last_text == t("ru", "menu")
    assert (await repo.get_referrer(db, 111)).emplid == EMP_A
    assert await verify_method(db, 111) == "manual_id"


async def test_qr_photo_verifies(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo(files={"qr": qr_photo_jpeg(EMP_A)})
    await start_ru(db, io)
    await handle_event(db, io, USER, Photo("qr", 80_000))
    assert (await repo.get_referrer(db, 111)).emplid == EMP_A
    assert await verify_method(db, 111) == "qr"


async def test_admin_button_appears_after_third_failure(db):
    io = FakeIo(files={"blank": blank_photo_jpeg()})
    await start_ru(db, io)
    for attempt in range(3):
        await handle_event(db, io, USER, Photo("blank", 50_000))
        assert io.last_text == t("ru", "qr_not_read")
        assert io.button_data() == ([] if attempt < 2 else ["auth:admin"])
    assert (await repo.load_session(db, 111)).step == AUTH_WAIT_ID


async def test_not_an_id_text_does_not_count_as_failure(db):
    io = FakeIo()
    await start_ru(db, io)
    for _ in range(3):
        await handle_event(db, io, USER, Text("привет"))
    assert io.last_text == t("ru", "not_an_id")
    assert (await repo.load_session(db, 111)).data.get("fails", 0) == 0


async def test_unknown_and_inactive_ids_are_not_found(db):
    await seed_employees(db, (EMP_A, "A A"), (EMP_B, "B B"))
    await repo.deactivate_missing(db, [EMP_A])
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(EMP_B))
    assert io.last_text == t("ru", "not_found")
    await handle_event(db, io, USER, Text("EMP-00000000-0000-4000-8000-0000000000ff"))
    assert io.last_text == t("ru", "not_found")
    assert (await repo.load_session(db, 111)).data["fails"] == 2


async def test_id_bound_to_other_account_alerts_admin(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await repo.bind_referrer(db, 999, EMP_A, "other", "qr")
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(EMP_A))
    assert io.last_text == t("ru", "id_taken")
    assert "Ivan Petrov" in io.admin_messages[-1][0]
    assert await repo.get_referrer(db, 111) is None


async def test_oversized_document_not_downloaded(db):
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Document("huge", "image/jpeg", 25 * 1024 * 1024))
    assert io.last_text == t("ru", "qr_not_read")


async def test_sticker_and_non_image_file_get_reminder(db):
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Other())
    assert io.last_text == t("ru", "send_photo_or_id")
    await handle_event(db, io, USER, Document("doc", "application/pdf", 1000))
    assert io.last_text == t("ru", "send_photo_or_id")


async def test_admin_request_flow(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo(files={"blank": blank_photo_jpeg()})
    await start_ru(db, io)
    await handle_event(db, io, USER, Button("auth:admin"))
    assert io.last_text == t("ru", "stale_button")
    for _ in range(3):
        await handle_event(db, io, USER, Photo("blank", 50_000))
    await handle_event(db, io, USER, Button("auth:admin"))
    assert io.last_text == t("ru", "ask_full_name_for_admin")
    await handle_event(db, io, USER, Text("petrov   ivan"))
    card_text, card_buttons = io.admin_messages[-1]
    assert "petrov ivan" in card_text
    assert [data for row in card_buttons for _, data in row] == [f"v:111:{EMP_A}", "x:111"]
    assert io.last_text == t("ru", "admin_request_sent")
    session = await repo.load_session(db, 111)
    assert session.step == AUTH_WAIT_ID and session.data["admin_card"] == [-100, 101]
    await handle_event(db, io, USER, Text(EMP_A))
    assert io.admin_edits[-1] == ((-100, 101), CARD_OBSOLETE)
    assert (await repo.get_referrer(db, 111)).emplid == EMP_A


async def test_photo_while_typing_name_goes_to_qr_check(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo(files={"blank": blank_photo_jpeg(), "qr": qr_photo_jpeg(EMP_A)})
    await start_ru(db, io)
    for _ in range(3):
        await handle_event(db, io, USER, Photo("blank", 50_000))
    await handle_event(db, io, USER, Button("auth:admin"))
    await handle_event(db, io, USER, Photo("qr", 80_000))
    assert (await repo.get_referrer(db, 111)).emplid == EMP_A
    assert io.admin_messages == []


async def test_deactivated_referrer_gets_access_closed(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"), (EMP_B, "B B"))
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(EMP_A))
    await repo.deactivate_missing(db, [EMP_B])
    for event in (Text("hi"), Button("menu:refer"), Command("start")):
        await handle_event(db, io, USER, event)
        assert io.last_text == t("ru", "access_closed")


async def test_menu_and_language_switch(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(EMP_A))
    await handle_event(db, io, USER, Button("menu:language"))
    assert io.last_text == t(None, "choose_language")
    await handle_event(db, io, USER, Button("lang:en"))
    assert io.last_text == t("en", "menu")
    assert io.button_data() == ["menu:refer", "menu:mine", "menu:language"]


async def test_start_mid_form_reprompts_and_cancel_returns_to_menu(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(EMP_A))
    await handle_event(db, io, USER, Button("menu:refer"))
    await handle_event(db, io, USER, Text("Aziz"))
    assert (await repo.load_session(db, 111)).step == REF_LAST_NAME
    await handle_event(db, io, USER, Command("start"))
    assert io.last_text == t("ru", "ask_last_name")
    await handle_event(db, io, USER, Command("cancel"))
    assert t("ru", "cancelled") in io.texts() and io.last_text == t("ru", "menu")
    assert (await repo.load_session(db, 111)).step == MENU


async def test_buttons_are_acknowledged(db):
    io = FakeIo()
    await start_ru(db, io)
    assert io.answered == [None]


async def test_unbound_user_in_menu_is_sent_back_to_auth(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(EMP_A))
    await repo.unbind_emplid(db, EMP_A)
    await handle_event(db, io, USER, Text("hi"))
    assert io.last_text == t("ru", "not_an_id")
