"""Обвязка python-telegram-bot: перевод апдейтов в события, отправка сообщений, расписание задач."""
from __future__ import annotations

import logging
import mimetypes
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from referrals import jobs
from referrals.alerts import Alerter, FailureTracker
from referrals.config import Config, load_config
from referrals.db import Db, migrate
from referrals.flow import admin as admin_flow
from referrals.flow.admin_texts import referral_caption
from referrals.flow.events import Button, Command, Document, Event, Other, Photo, Text, User
from referrals.flow.io import Buttons
from referrals.flow.router import handle_event
from referrals.models import PhotoBlob, Referral
from referrals.sheets import open_worksheet

log = logging.getLogger("referrals")

SOMETHING_WRONG = "Что-то пошло не так. Попробуйте ещё раз. / Something went wrong, please try again."


# ─── перевод апдейтов ──────────────────────────────────────────

def to_user(update: Update) -> User:
    user = update.effective_user
    return User(id=user.id, username=user.username, full_name=user.full_name)


def to_event(update: Update) -> Event:
    if update.callback_query is not None:
        return Button(update.callback_query.data or "")
    message = update.message
    if message is None:
        return Other()
    if message.photo:
        largest = message.photo[-1]
        return Photo(largest.file_id, largest.file_size)
    if message.document:
        doc = message.document
        return Document(doc.file_id, doc.mime_type, doc.file_size)
    if message.text:
        if message.text.startswith("/"):
            parts = message.text[1:].split()
            name = parts[0].split("@")[0].lower() if parts else ""
            return Command(name, tuple(parts[1:]))
        return Text(message.text)
    return Other()


def to_markup(buttons: Buttons | None) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in buttons]
    )


# ─── зависимости и реализации Io/Notifier ──────────────────────

@dataclass
class Deps:
    cfg: Config
    db: Db
    http: httpx.AsyncClient
    alerter: Alerter
    failures: FailureTracker


def _deps(context: ContextTypes.DEFAULT_TYPE) -> Deps:
    return context.application.bot_data["deps"]


class TelegramIo:
    def __init__(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, query=None) -> None:
        self._context = context
        self._bot = context.bot
        self._chat_id = chat_id
        self._query = query

    async def reply(self, text: str, buttons: Buttons | None = None) -> None:
        await self._bot.send_message(self._chat_id, text, reply_markup=to_markup(buttons))

    async def download(self, file_id: str) -> bytes:
        file = await self._bot.get_file(file_id)
        return bytes(await file.download_as_bytearray())

    async def send_admin(self, text: str, buttons: Buttons | None = None) -> tuple[int, int]:
        message = await self._bot.send_message(_deps(self._context).cfg.admin_chat_id, text,
                                                reply_markup=to_markup(buttons))
        return message.chat_id, message.message_id

    async def edit_admin(self, ref: tuple[int, int], text: str) -> None:
        try:
            await self._bot.edit_message_text(text, chat_id=ref[0], message_id=ref[1])
        except BadRequest as exc:
            log.warning("не удалось изменить сообщение %s: %s", ref, exc)

    async def send_user(self, tg_user_id: int, text: str, buttons: Buttons | None = None) -> None:
        await self._bot.send_message(tg_user_id, text, reply_markup=to_markup(buttons))

    async def answer_button(self, text: str | None = None) -> None:
        if self._query is None:
            return
        await self._query.answer(text)
        try:
            await self._query.edit_message_reply_markup(None)
        except BadRequest:
            pass

    def kick_background(self) -> None:
        self._context.application.job_queue.run_once(job_push, 1)
        self._context.application.job_queue.run_once(job_notify, 2)


class TelegramNotifier:
    def __init__(self, bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def send_referral(self, referral: Referral) -> None:
        caption = referral_caption(referral)
        if referral.photo_kind == "photo":
            await self._bot.send_photo(self._chat_id, referral.photo_file_id, caption=caption)
        else:
            await self._bot.send_document(self._chat_id, referral.photo_file_id, caption=caption)

    async def reupload(self, referral: Referral, photo: PhotoBlob) -> str:
        caption = f"♻️ Перезаливка фото {referral.number}: на Диске его нет больше суток."
        if referral.photo_kind == "photo":
            message = await self._bot.send_photo(self._chat_id, photo.content, caption=caption)
            return message.photo[-1].file_id
        extension = mimetypes.guess_extension(photo.mime_type) or ".jpg"
        message = await self._bot.send_document(self._chat_id, photo.content, caption=caption,
                                                filename=f"{referral.number}{extension}")
        return message.document.file_id


# ─── обработчики ───────────────────────────────────────────────

async def on_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    io = TelegramIo(context, update.effective_chat.id, update.callback_query)
    await handle_event(_deps(context).db, io, to_user(update), to_event(update))


async def on_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    deps = _deps(context)
    io = TelegramIo(context, query.message.chat_id, query)
    await admin_flow.on_admin_button(deps.db, io, query.from_user.id, deps.cfg.admin_user_ids, query.data,
                                     (query.message.chat_id, query.message.message_id))


async def on_unbind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    deps = _deps(context)
    io = TelegramIo(context, update.effective_chat.id)
    await admin_flow.on_unbind(deps.db, io, update.effective_user.id, deps.cfg.admin_user_ids,
                               tuple(context.args or ()))


async def on_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in _deps(context).cfg.admin_user_ids:
        return
    for job in (job_employees, job_push, job_reconcile):
        context.job_queue.run_once(job, 0)
    await update.effective_message.reply_text("Синхронизация запущена.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("ошибка обработки апдейта", exc_info=context.error)
    deps = context.application.bot_data.get("deps")
    if deps is not None:
        await deps.alerter.alert("handler_error", f"Ошибка обработки сообщения: {context.error!r}")
    if isinstance(update, Update) and update.effective_chat and update.effective_chat.type == "private":
        try:
            await context.bot.send_message(update.effective_chat.id, SOMETHING_WRONG)
        except Exception:
            log.exception("не удалось сообщить пользователю об ошибке")


# ─── фоновые задачи ────────────────────────────────────────────

async def _run_job(context: ContextTypes.DEFAULT_TYPE, name: str,
                   work: Callable[[Deps, ContextTypes.DEFAULT_TYPE], Awaitable[object]]) -> None:
    deps = _deps(context)
    try:
        await work(deps, context)
    except Exception as exc:
        log.exception("задача %s упала", name)
        if deps.failures.record(name, ok=False):
            await deps.alerter.alert(f"job:{name}",
                                     f"Задача {name} падает {deps.failures.threshold}+ раз подряд: {exc!r}")
    else:
        deps.failures.record(name, ok=True)


def _open_ws(deps: Deps) -> Callable[[], object]:
    cfg = deps.cfg
    return lambda: open_worksheet(cfg.google_credentials, cfg.spreadsheet_id, cfg.sheet_name)


async def job_employees(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_job(context, "employees",
                   lambda d, c: jobs.run_employee_sync(d.db, d.http, d.cfg.tabeli_url, d.alerter))


async def job_push(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_job(context, "sheet_push",
                   lambda d, c: jobs.run_sheet_sync(d.db, _open_ws(d), d.alerter, full=False))


async def job_reconcile(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_job(context, "sheet_reconcile",
                   lambda d, c: jobs.run_sheet_sync(d.db, _open_ws(d), d.alerter, full=True))


async def job_notify(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_job(context, "notify_hr",
                   lambda d, c: jobs.run_notify(d.db, TelegramNotifier(c.bot, d.cfg.admin_chat_id)))


async def job_reupload(context: ContextTypes.DEFAULT_TYPE) -> None:
    async def work(d: Deps, c: ContextTypes.DEFAULT_TYPE) -> None:
        if await jobs.run_reupload(d.db, TelegramNotifier(c.bot, d.cfg.admin_chat_id)):
            c.job_queue.run_once(job_reconcile, 5)

    await _run_job(context, "reupload_photos", work)


# ─── жизненный цикл ────────────────────────────────────────────

async def post_init(app: Application) -> None:
    cfg: Config = app.bot_data["cfg"]
    applied = await migrate(cfg.database_url)
    if applied:
        log.info("применены миграции: %s", ", ".join(applied))
    db = await Db.connect(cfg.database_url)
    alerter = Alerter(lambda text: app.bot.send_message(cfg.admin_chat_id, text))
    app.bot_data["deps"] = Deps(cfg, db, httpx.AsyncClient(), alerter, FailureTracker())

    queue = app.job_queue
    queue.run_repeating(job_employees, interval=15 * 60, first=1)
    queue.run_repeating(job_push, interval=60, first=20)
    queue.run_repeating(job_notify, interval=60, first=30)
    queue.run_repeating(job_reconcile, interval=15 * 60, first=60)
    queue.run_repeating(job_reupload, interval=24 * 3600, first=10 * 60)
    await app.bot.set_my_commands([BotCommand("start", "Начать / меню"), BotCommand("cancel", "Отменить анкету")])


async def post_shutdown(app: Application) -> None:
    deps: Deps | None = app.bot_data.get("deps")
    if deps is not None:
        await deps.http.aclose()
        await deps.db.close()


def build_application(cfg: Config) -> Application:
    app = (ApplicationBuilder().token(cfg.telegram_bot_token)
           .post_init(post_init).post_shutdown(post_shutdown).build())
    app.bot_data["cfg"] = cfg
    app.add_handler(CommandHandler("unbind", on_unbind))
    app.add_handler(CommandHandler("sync", on_sync))
    app.add_handler(CallbackQueryHandler(on_admin_callback, pattern=r"^[vx]:"))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE, on_private))
    app.add_handler(CallbackQueryHandler(on_private))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = build_application(load_config())
    app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)
