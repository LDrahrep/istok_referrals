import copy
from uuid import uuid4

from referrals import repo
from referrals.flow import referral
from referrals.flow.events import Button, Document, Photo, Text, User
from referrals.flow.steps import MENU, REF_CONFIRM, REF_FIRST_NAME, REF_PHONE, REF_PHOTO
from referrals.i18n import t
from referrals.models import Session
from tests.factories import EMP_A, EMP_B, make_draft, make_photo
from tests.fakes import FakeIo
from tests.helpers import seed_employees, seed_referrer

USER = User(id=111, username="ivan", full_name="Ivan P")
FORM_INPUTS = [
    Text("Aziz"), Text("Karimov"), Text("(650) 253-0000"), Text("Aziz@Example.com"),
    Button("yn:yes"), Photo("photo-1", 90_000),
]
CONFIRM_BUTTONS = ["form:submit", "form:restart", "nav:cancel"]


async def verified(db):
    ref = await seed_referrer(db)
    s = Session(tg_user_id=111, step=MENU, language="ru")
    await repo.save_session(db, s)
    return s, ref


async def fill(db, io, s, ref, inputs=FORM_INPUTS):
    await referral.start_form(db, io, s)
    for event in inputs:
        await referral.on_form(db, io, USER, s, ref, event)


async def test_start_form_issues_key_and_prompts(db):
    s, ref = await verified(db)
    io = FakeIo()
    await referral.start_form(db, io, s)
    assert s.step == REF_FIRST_NAME and s.submission_key is not None
    assert io.last_text == t("ru", "ask_first_name")
    assert io.button_data() == ["nav:back", "nav:cancel"]
    assert (await repo.load_session(db, 111)).submission_key == s.submission_key


async def test_happy_path_creates_referral(db):
    s, ref = await verified(db)
    io = FakeIo(files={"photo-1": b"\xff\xd8work-permit"})
    await fill(db, io, s, ref)
    assert s.step == REF_CONFIRM
    assert io.last_text == t("ru", "confirm", first_name="Aziz", last_name="Karimov",
                             phone="+16502530000", email="aziz@example.com", worked="Да")
    assert io.button_data() == CONFIRM_BUTTONS
    await referral.on_form(db, io, USER, s, ref, Button("form:submit"))
    [created] = await repo.all_referrals(db)
    assert (created.first_name, created.phone, created.email, created.worked_before, created.referrer_emplid) == (
        "Aziz", "+16502530000", "aziz@example.com", True, EMP_A)
    assert (await repo.get_photo(db, created.id)).content == b"\xff\xd8work-permit"
    assert t("ru", "submitted", number="R-000001") in io.texts()
    assert io.last_text == t("ru", "menu") and io.kicks == 1
    stored = await repo.load_session(db, 111)
    assert (stored.step, stored.data, stored.submission_key) == (MENU, {}, None)


async def test_bad_name_is_rejected(db):
    s, ref = await verified(db)
    io = FakeIo()
    await referral.start_form(db, io, s)
    await referral.on_form(db, io, USER, s, ref, Text("Aziz2"))
    assert io.last_text == t("ru", "bad_name") and s.step == REF_FIRST_NAME


async def test_phone_already_referred_ends_form(db):
    s, ref = await verified(db)
    await repo.create_referral(db, make_draft(), make_photo(), Session(tg_user_id=111, step=MENU))
    io = FakeIo()
    await fill(db, io, s, ref, FORM_INPUTS[:3])
    assert t("ru", "already_referred", number="R-000001") in io.texts()
    assert s.step == MENU and io.last_text == t("ru", "menu")


async def test_email_already_referred_ends_form(db):
    s, ref = await verified(db)
    await repo.create_referral(db, make_draft(phone="+16502530001"), make_photo(), Session(tg_user_id=111, step=MENU))
    io = FakeIo()
    await fill(db, io, s, ref, FORM_INPUTS[:4])
    assert t("ru", "already_referred", number="R-000001") in io.texts()
    assert s.step == MENU


async def test_back_and_cancel(db):
    s, ref = await verified(db)
    io = FakeIo()
    await fill(db, io, s, ref, FORM_INPUTS[:1])
    await referral.on_form(db, io, USER, s, ref, Button("nav:back"))
    assert s.step == REF_FIRST_NAME and io.last_text == t("ru", "ask_first_name")
    await referral.on_form(db, io, USER, s, ref, Button("nav:back"))
    assert s.step == MENU and t("ru", "cancelled") in io.texts()
    await referral.start_form(db, io, s)
    await referral.on_form(db, io, USER, s, ref, Text("Aziz"))
    await referral.on_form(db, io, USER, s, ref, Button("nav:cancel"))
    stored = await repo.load_session(db, 111)
    assert (stored.step, stored.data, stored.submission_key) == (MENU, {}, None)


async def test_worked_step_requires_buttons(db):
    s, ref = await verified(db)
    io = FakeIo()
    await fill(db, io, s, ref, FORM_INPUTS[:4])
    await referral.on_form(db, io, USER, s, ref, Text("да"))
    assert io.replies[-2][0] == t("ru", "use_buttons")
    assert io.last_text == t("ru", "ask_worked")
    assert io.button_data() == ["yn:yes", "yn:no", "nav:back", "nav:cancel"]


async def test_photo_step_validation(db):
    s, ref = await verified(db)
    io = FakeIo()
    await fill(db, io, s, ref, FORM_INPUTS[:5])
    for bad in (Document("pdf", "application/pdf", 1000), Photo("big", 21 * 1024 * 1024), Text("вот")):
        await referral.on_form(db, io, USER, s, ref, bad)
        assert io.last_text == t("ru", "bad_photo") and s.step == REF_PHOTO
    await referral.on_form(db, io, USER, s, ref, Document("scan", "image/png", 5000))
    assert s.data["photo"] == {"file_id": "scan", "kind": "document", "mime": "image/png", "size": 5000}
    assert s.step == REF_CONFIRM


async def test_stale_button_keeps_step(db):
    s, ref = await verified(db)
    io = FakeIo()
    await fill(db, io, s, ref, FORM_INPUTS[:2])
    await referral.on_form(db, io, USER, s, ref, Button("yn:yes"))
    assert io.replies[-2][0] == t("ru", "stale_button")
    assert io.last_text == t("ru", "ask_phone")
    assert s.step == REF_PHONE and s.data == {"first_name": "Aziz", "last_name": "Karimov"}


async def test_second_photo_at_confirm_is_ignored(db):
    s, ref = await verified(db)
    io = FakeIo()
    await fill(db, io, s, ref)
    await referral.on_form(db, io, USER, s, ref, Photo("photo-2", 1000))
    assert s.step == REF_CONFIRM and s.data["photo"]["file_id"] == "photo-1"
    assert io.replies[-2][0] == t("ru", "use_buttons")
    assert io.button_data() == CONFIRM_BUTTONS


async def test_incomplete_draft_restarts_form(db):
    s, ref = await verified(db)
    s.step, s.data, s.submission_key = REF_CONFIRM, {"first_name": "Aziz"}, uuid4()
    await repo.save_session(db, s)
    io = FakeIo()
    await referral.on_form(db, io, USER, s, ref, Button("form:submit"))
    assert (s.step, s.data) == (REF_FIRST_NAME, {})
    assert io.last_text == t("ru", "ask_first_name")
    assert await repo.all_referrals(db) == []


async def test_photo_download_failure_keeps_draft(db):
    s, ref = await verified(db)
    io = FakeIo()
    await fill(db, io, s, ref)
    await referral.on_form(db, io, USER, s, ref, Button("form:submit"))
    assert t("ru", "submit_failed_download") in io.texts()
    assert io.button_data() == CONFIRM_BUTTONS
    assert await repo.all_referrals(db) == []
    assert (await repo.load_session(db, 111)).step == REF_CONFIRM


async def test_replayed_submit_does_not_duplicate(db):
    s, ref = await verified(db)
    io = FakeIo(files={"photo-1": b"x"})
    await fill(db, io, s, ref)
    replay = copy.deepcopy(s)
    await referral.on_form(db, io, USER, s, ref, Button("form:submit"))
    await referral.on_form(db, io, USER, replay, ref, Button("form:submit"))
    assert len(await repo.all_referrals(db)) == 1
    assert io.texts().count(t("ru", "submitted", number="R-000001")) == 2


async def test_candidate_referred_by_someone_else_meanwhile(db):
    s, ref = await verified(db)
    io = FakeIo(files={"photo-1": b"x"})
    await fill(db, io, s, ref)
    await seed_employees(db, (EMP_B, "Other Person"))
    await repo.bind_referrer(db, 222, EMP_B, None, "qr")
    other = make_draft(referrer_tg_user_id=222, referrer_emplid=EMP_B, referrer_name="Other Person")
    await repo.create_referral(db, other, make_photo(), Session(tg_user_id=222, step=MENU))
    await referral.on_form(db, io, USER, s, ref, Button("form:submit"))
    assert t("ru", "already_referred", number="R-000001") in io.texts()
    assert (await repo.load_session(db, 111)).step == MENU
    assert len(await repo.all_referrals(db)) == 1


async def test_english_prompts(db):
    s, ref = await verified(db)
    s.language = "en"
    io = FakeIo()
    await referral.start_form(db, io, s)
    assert io.last_text == t("en", "ask_first_name")
