from telegram import Bot, InlineKeyboardMarkup, Update

from referrals.app import build_application, to_event, to_markup, to_user
from referrals.config import Config
from referrals.flow.events import Button, Command, Document, Other, Photo, Text, User

BOT = Bot("123456:TEST_TOKEN")
FROM = {"id": 111, "is_bot": False, "first_name": "Ivan", "last_name": "P", "username": "ivan"}
MSG = {"message_id": 1, "date": 0, "chat": {"id": 111, "type": "private"}, "from": FROM}
CFG = Config(
    telegram_bot_token="123456:TEST_TOKEN", database_url="postgresql://x", tabeli_url="http://t",
    google_credentials={}, spreadsheet_id="s", sheet_name="Заявки", admin_chat_id=-100,
    admin_user_ids=frozenset({7}),
)


def update_from(payload: dict) -> Update:
    return Update.de_json({"update_id": 1, **payload}, BOT)


def test_photo_uses_largest_size_and_user_is_mapped():
    update = update_from({"message": {**MSG, "photo": [
        {"file_id": "small", "file_unique_id": "s", "width": 90, "height": 90, "file_size": 1000},
        {"file_id": "big", "file_unique_id": "b", "width": 1280, "height": 960, "file_size": 90000},
    ]}})
    assert to_event(update) == Photo("big", 90000)
    assert to_user(update) == User(111, "ivan", "Ivan P")


def test_document():
    update = update_from({"message": {**MSG, "document": {
        "file_id": "d", "file_unique_id": "du", "mime_type": "image/png", "file_size": 5000}}})
    assert to_event(update) == Document("d", "image/png", 5000)


def test_text_and_commands():
    assert to_event(update_from({"message": {**MSG, "text": "Aziz"}})) == Text("Aziz")
    assert to_event(update_from({"message": {**MSG, "text": "/start@istok_referrals_bot"}})) == Command("start")
    assert to_event(update_from({"message": {**MSG, "text": "/cancel now"}})) == Command("cancel", ("now",))


def test_callback_query():
    update = update_from({"callback_query": {"id": "q", "from": FROM, "chat_instance": "ci",
                                             "data": "yn:yes", "message": MSG}})
    assert to_event(update) == Button("yn:yes")


def test_sticker_is_other():
    update = update_from({"message": {**MSG, "sticker": {
        "file_id": "st", "file_unique_id": "stu", "width": 512, "height": 512,
        "is_animated": False, "is_video": False, "type": "regular"}}})
    assert to_event(update) == Other()


def test_to_markup():
    assert to_markup(None) is None
    markup = to_markup([[("Да", "yn:yes"), ("Нет", "yn:no")]])
    assert isinstance(markup, InlineKeyboardMarkup)
    assert [(b.text, b.callback_data) for b in markup.inline_keyboard[0]] == [("Да", "yn:yes"), ("Нет", "yn:no")]


def test_build_application_registers_handlers():
    app = build_application(CFG)
    assert app.job_queue is not None
    assert len(app.handlers[0]) == 5
    assert app.error_handlers
    assert app.bot_data["cfg"] is CFG


class FakeQuery:
    def __init__(self, answer_error=None):
        self.answer_error = answer_error
        self.answers = []
        self.markups_removed = 0

    async def answer(self, text=None):
        if self.answer_error:
            raise self.answer_error
        self.answers.append(text)

    async def edit_message_reply_markup(self, markup):
        self.markups_removed += 1


def telegram_io(query):
    from types import SimpleNamespace

    from referrals.app import TelegramIo
    return TelegramIo(SimpleNamespace(bot=None, application=None), 111, query)


async def test_answer_button_survives_expired_query():
    from telegram.error import BadRequest
    query = FakeQuery(answer_error=BadRequest("Query is too old and response timeout expired or query id is invalid"))
    await telegram_io(query).answer_button()
    assert query.markups_removed == 1


async def test_answer_button_can_keep_keyboard():
    query = FakeQuery()
    await telegram_io(query).answer_button("Нет прав", remove_keyboard=False)
    assert query.answers == ["Нет прав"] and query.markups_removed == 0


async def test_sheet_reader_reads_status_from_configured_sheet(monkeypatch):
    from referrals import app as app_module
    from referrals.sheet_model import BOT_HEADERS, PHOTO_HEADER
    from tests.fakes import FakeSheet
    opened = []
    row = ["R-000001"] + [""] * (len(BOT_HEADERS) - 1) + ["", "Интервью"]
    sheet = FakeSheet([[*BOT_HEADERS, PHOTO_HEADER, "Статус"], row])

    def fake_open(credentials, spreadsheet_id, sheet_name):
        opened.append((spreadsheet_id, sheet_name))
        return sheet

    monkeypatch.setattr(app_module, "open_worksheet", fake_open)
    assert await app_module.sheet_reader(CFG).hr_status("R-000001") == "Интервью"
    assert opened == [("s", "Заявки")]


def test_reply_keyboard_markup():
    from telegram import ReplyKeyboardMarkup

    from referrals.app import _markup
    markup = _markup(None, ["✖️ Отмена"])
    assert isinstance(markup, ReplyKeyboardMarkup) and markup.is_persistent and markup.resize_keyboard
    assert [b.text for b in markup.keyboard[0]] == ["✖️ Отмена"]
    assert _markup(None, None) is None
