"""Анкета кандидата: шаги, проверки, отправка."""
from __future__ import annotations

import logging
from uuid import uuid4

from referrals import repo
from referrals.db import Db
from referrals.flow.common import nav_row, show_menu
from referrals.flow.events import Button, Document, Event, Photo, Text, User, is_image_document, too_big
from referrals.flow.io import Io
from referrals.flow.steps import (
    FORM_STEPS, MENU, REF_CONFIRM, REF_EMAIL, REF_FIRST_NAME, REF_LAST_NAME, REF_PHONE, REF_PHOTO, REF_WORKED,
)
from referrals.i18n import t
from referrals.models import PhotoBlob, ReferralDraft, Referrer, Session, referral_number
from referrals.validation import clean_name, normalize_email, normalize_phone

log = logging.getLogger(__name__)

PROMPT_KEYS = {
    REF_FIRST_NAME: "ask_first_name",
    REF_LAST_NAME: "ask_last_name",
    REF_PHONE: "ask_phone",
    REF_EMAIL: "ask_email",
    REF_PHOTO: "ask_photo",
}
REQUIRED_KEYS = ("first_name", "last_name", "phone", "email", "worked_before", "photo")


def draft_complete(data: dict) -> bool:
    return all(key in data for key in REQUIRED_KEYS)


async def prompt(io: Io, s: Session) -> None:
    lang = s.language
    if s.step == REF_WORKED:
        await io.reply(t(lang, "ask_worked"),
                       [[(t(lang, "btn_yes"), "yn:yes"), (t(lang, "btn_no"), "yn:no")], nav_row(lang)])
    elif s.step == REF_CONFIRM:
        d = s.data
        worked = t(lang, "btn_yes") if d.get("worked_before") else t(lang, "btn_no")
        text = t(lang, "confirm", first_name=d.get("first_name", "—"), last_name=d.get("last_name", "—"),
                 phone=d.get("phone", "—"), email=d.get("email", "—"), worked=worked)
        await io.reply(text, [[(t(lang, "btn_submit"), "form:submit")],
                              [(t(lang, "btn_restart"), "form:restart")],
                              [(t(lang, "btn_cancel"), "nav:cancel")]])
    else:
        await io.reply(t(lang, PROMPT_KEYS[s.step]), [nav_row(lang)])


async def start_form(db: Db, io: Io, s: Session) -> None:
    s.step, s.data, s.submission_key = REF_FIRST_NAME, {}, uuid4()
    await repo.save_session(db, s)
    await prompt(io, s)


async def _end_form(db: Db, s: Session) -> None:
    s.step, s.data, s.submission_key = MENU, {}, None
    await repo.save_session(db, s)


async def cancel_form(db: Db, io: Io, s: Session) -> None:
    await _end_form(db, s)
    await io.reply(t(s.language, "cancelled"))
    await show_menu(io, s.language)


async def _already_referred(db: Db, io: Io, s: Session, referral_id: int) -> None:
    await _end_form(db, s)
    await io.reply(t(s.language, "already_referred", number=referral_number(referral_id)))
    await show_menu(io, s.language)


async def _advance(db: Db, io: Io, s: Session) -> None:
    s.step = FORM_STEPS[FORM_STEPS.index(s.step) + 1]
    await repo.save_session(db, s)
    await prompt(io, s)


async def _go_back(db: Db, io: Io, s: Session) -> None:
    index = FORM_STEPS.index(s.step)
    if index == 0:
        await cancel_form(db, io, s)
        return
    s.step = FORM_STEPS[index - 1]
    await repo.save_session(db, s)
    await prompt(io, s)


async def _remind(io: Io, s: Session, event: Event) -> None:
    if isinstance(event, Button):
        await io.reply(t(s.language, "stale_button"))
    elif s.step in (REF_WORKED, REF_CONFIRM):
        await io.reply(t(s.language, "use_buttons"))
    await prompt(io, s)


def _photo_from_event(event: Event) -> dict | None:
    if isinstance(event, Photo) and not too_big(event.size):
        return {"file_id": event.file_id, "kind": "photo", "mime": "image/jpeg", "size": event.size}
    if isinstance(event, Document) and is_image_document(event) and not too_big(event.size):
        return {"file_id": event.file_id, "kind": "document", "mime": event.mime_type, "size": event.size}
    return None


async def on_form(db: Db, io: Io, user: User, s: Session, ref: Referrer, event: Event) -> None:
    lang = s.language
    if isinstance(event, Button) and event.data == "nav:cancel":
        await cancel_form(db, io, s)
        return
    if isinstance(event, Button) and event.data == "nav:back":
        await _go_back(db, io, s)
        return
    if s.submission_key is None or (s.step == REF_CONFIRM and not draft_complete(s.data)):
        await start_form(db, io, s)
        return

    step = s.step
    if step in (REF_FIRST_NAME, REF_LAST_NAME):
        if not isinstance(event, Text):
            await _remind(io, s, event)
            return
        name = clean_name(event.text)
        if name is None:
            await io.reply(t(lang, "bad_name"))
            return
        s.data["first_name" if step == REF_FIRST_NAME else "last_name"] = name
        await _advance(db, io, s)
    elif step == REF_PHONE:
        if not isinstance(event, Text):
            await _remind(io, s, event)
            return
        phone = normalize_phone(event.text)
        if phone is None:
            await io.reply(t(lang, "bad_phone"))
            return
        existing = await repo.find_referral_by_phone(db, phone)
        if existing is not None:
            await _already_referred(db, io, s, existing)
            return
        s.data["phone"] = phone
        await _advance(db, io, s)
    elif step == REF_EMAIL:
        if not isinstance(event, Text):
            await _remind(io, s, event)
            return
        email = normalize_email(event.text)
        if email is None:
            await io.reply(t(lang, "bad_email"))
            return
        existing = await repo.find_referral_by_email(db, email)
        if existing is not None:
            await _already_referred(db, io, s, existing)
            return
        s.data["email"] = email
        await _advance(db, io, s)
    elif step == REF_WORKED:
        if isinstance(event, Button) and event.data in ("yn:yes", "yn:no"):
            s.data["worked_before"] = event.data == "yn:yes"
            await _advance(db, io, s)
        else:
            await _remind(io, s, event)
    elif step == REF_PHOTO:
        if isinstance(event, Button):
            await _remind(io, s, event)
            return
        photo = _photo_from_event(event)
        if photo is None:
            await io.reply(t(lang, "bad_photo"))
            return
        s.data["photo"] = photo
        await _advance(db, io, s)
    elif step == REF_CONFIRM:
        if isinstance(event, Button) and event.data == "form:submit":
            await _submit(db, io, user, s, ref)
        elif isinstance(event, Button) and event.data == "form:restart":
            await start_form(db, io, s)
        else:
            await _remind(io, s, event)


async def _submit(db: Db, io: Io, user: User, s: Session, ref: Referrer) -> None:
    lang, d = s.language, s.data
    try:
        content = await io.download(d["photo"]["file_id"])
        photo = PhotoBlob.from_bytes(content, d["photo"]["mime"] or "image/jpeg")
    except Exception:
        log.exception("не удалось скачать фото заявки tg=%s", user.id)
        await io.reply(t(lang, "submit_failed_download"))
        await prompt(io, s)
        return
    draft = ReferralDraft(
        submission_key=s.submission_key, first_name=d["first_name"], last_name=d["last_name"],
        phone=d["phone"], email=d["email"], worked_before=d["worked_before"],
        referrer_tg_user_id=user.id, referrer_emplid=ref.emplid, referrer_name=ref.name,
        photo_file_id=d["photo"]["file_id"], photo_kind=d["photo"]["kind"],
    )
    next_session = Session(tg_user_id=s.tg_user_id, step=MENU, language=lang)
    try:
        result = await repo.create_referral(db, draft, photo, next_session)
    except repo.DuplicateCandidate as dup:
        await _already_referred(db, io, s, dup.existing_id)
        return
    s.step, s.data, s.submission_key = MENU, {}, None
    await io.reply(t(lang, "submitted", number=result.number))
    await show_menu(io, lang)
    io.kick_background()
