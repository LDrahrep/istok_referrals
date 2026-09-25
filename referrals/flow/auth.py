"""Выбор языка и проверка, что пользователь — сотрудник Istok."""
from __future__ import annotations

import asyncio

from referrals import repo
from referrals.db import Db
from referrals.flow import admin_texts
from referrals.flow.common import show_menu
from referrals.flow.events import Button, Document, Event, Photo, Text, User, is_image_document, too_big
from referrals.flow.io import Io
from referrals.flow.steps import ADMIN_BUTTON_AFTER_FAILS, AUTH_ADMIN_NAME, AUTH_WAIT_ID, MENU
from referrals.i18n import LANGS, t
from referrals.models import BindResult, Referrer, Session
from referrals.qr import decode_emp_id
from referrals.validation import extract_emp_id


async def prompt_auth(io: Io, s: Session) -> None:
    if s.step == AUTH_ADMIN_NAME:
        await io.reply(t(s.language, "ask_full_name_for_admin"), [[(t(s.language, "btn_cancel"), "nav:cancel")]])
    else:
        await io.reply(t(s.language, "ask_id"))


async def on_language(db: Db, io: Io, s: Session, ref: Referrer | None, lang: str) -> None:
    if lang not in LANGS:
        await io.reply(t(s.language, "stale_button"))
        return
    s.language = lang
    if ref is not None:
        s.step, s.data, s.submission_key = MENU, {}, None
        await repo.save_session(db, s)
        await show_menu(io, lang)
        return
    s.step = AUTH_WAIT_ID
    await repo.save_session(db, s)
    await prompt_auth(io, s)


def _admin_button_allowed(s: Session) -> bool:
    return s.data.get("fails", 0) >= ADMIN_BUTTON_AFTER_FAILS and not s.data.get("admin_card")


async def _fail(db: Db, io: Io, s: Session, key: str) -> None:
    s.data["fails"] = s.data.get("fails", 0) + 1
    await repo.save_session(db, s)
    buttons = [[(t(s.language, "btn_ask_admin"), "auth:admin")]] if _admin_button_allowed(s) else None
    await io.reply(t(s.language, key), buttons)


async def _verify(db: Db, io: Io, user: User, s: Session, emplid: str, method: str) -> None:
    employee = await repo.find_employee(db, emplid)
    if employee is None or not employee.active:
        await _fail(db, io, s, "not_found")
        return
    result = await repo.bind_referrer(db, user.id, employee.emplid, user.username, method)
    if result is BindResult.EMPLID_TAKEN:
        await io.send_admin(admin_texts.id_taken_text(user, employee))
        await _fail(db, io, s, "id_taken")
        return
    name = employee.name
    if result is BindResult.ALREADY:
        existing = await repo.get_referrer(db, user.id)
        name = existing.name if existing else name
    card = s.data.get("admin_card")
    if card:
        await io.edit_admin((card[0], card[1]), admin_texts.CARD_OBSOLETE)
    s.step, s.data, s.submission_key = MENU, {}, None
    await repo.save_session(db, s)
    await io.reply(t(s.language, "welcome", name=name))
    await show_menu(io, s.language)


async def on_wait_id(db: Db, io: Io, user: User, s: Session, event: Event) -> None:
    lang = s.language
    if isinstance(event, Photo) or (isinstance(event, Document) and is_image_document(event)):
        if too_big(event.size):
            await _fail(db, io, s, "qr_not_read")
            return
        data = await io.download(event.file_id)
        emplid = await asyncio.to_thread(decode_emp_id, data)
        if emplid is None:
            await _fail(db, io, s, "qr_not_read")
            return
        await _verify(db, io, user, s, emplid, "qr")
    elif isinstance(event, Text):
        emplid = extract_emp_id(event.text)
        if emplid is None:
            await io.reply(t(lang, "not_an_id"))
            return
        await _verify(db, io, user, s, emplid, "manual_id")
    elif isinstance(event, Button):
        if event.data == "auth:admin" and _admin_button_allowed(s):
            s.step = AUTH_ADMIN_NAME
            await repo.save_session(db, s)
            await prompt_auth(io, s)
        else:
            await io.reply(t(lang, "stale_button"))
    else:
        await io.reply(t(lang, "send_photo_or_id"))


async def on_admin_name(db: Db, io: Io, user: User, s: Session, event: Event) -> None:
    if isinstance(event, Button) and event.data == "nav:cancel":
        s.step = AUTH_WAIT_ID
        await repo.save_session(db, s)
        await prompt_auth(io, s)
        return
    if isinstance(event, (Photo, Document)) or (isinstance(event, Text) and extract_emp_id(event.text)):
        s.step = AUTH_WAIT_ID
        await on_wait_id(db, io, user, s, event)
        return
    if not isinstance(event, Text):
        await prompt_auth(io, s)
        return
    typed = " ".join(event.text.split())
    if not typed or len(typed) > 100:
        await prompt_auth(io, s)
        return
    matches = await repo.search_active_employees_by_name(db, typed)
    card = await io.send_admin(
        admin_texts.verify_request_text(user, typed, matches),
        admin_texts.verify_request_buttons(user.id, matches),
    )
    s.data["admin_card"] = [card[0], card[1]]
    s.step = AUTH_WAIT_ID
    await repo.save_session(db, s)
    await io.reply(t(s.language, "admin_request_sent"))
