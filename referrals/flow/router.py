"""Точка входа диалога: загружает состояние и передаёт событие нужному шагу."""
from __future__ import annotations

from referrals import repo
from referrals.db import Db
from referrals.flow import auth, referral
from referrals.flow.common import prompt_language, show_menu
from referrals.flow.events import Button, Command, Event, User
from referrals.flow.io import Io
from referrals.flow.steps import AUTH_ADMIN_NAME, AUTH_STEPS, AUTH_WAIT_ID, FORM_STEPS, LANG, MENU
from referrals.i18n import t
from referrals.models import Referrer, Session


async def handle_event(db: Db, io: Io, user: User, event: Event) -> None:
    s = await repo.load_session(db, user.id) or Session(tg_user_id=user.id, step=LANG)
    ref = await repo.get_referrer(db, user.id)
    if isinstance(event, Button):
        await io.answer_button()
    if ref is not None and not ref.active:
        await io.reply(t(s.language, "access_closed"))
        return
    if isinstance(event, Command):
        if event.name == "cancel":
            await _on_cancel(db, io, s, ref)
        else:
            await _on_start(db, io, s, ref)
        return
    if isinstance(event, Button) and event.data.startswith("lang:"):
        await auth.on_language(db, io, s, ref, event.data.removeprefix("lang:"))
        return
    if s.step == LANG:
        await prompt_language(io)
        return
    # Шаг должен соответствовать факту привязки (её могли снять /unbind или выдать админом).
    if ref is None and s.step not in AUTH_STEPS:
        s.step = AUTH_WAIT_ID
    if ref is not None and s.step in AUTH_STEPS:
        s.step = MENU

    if s.step == AUTH_WAIT_ID:
        await auth.on_wait_id(db, io, user, s, event)
    elif s.step == AUTH_ADMIN_NAME:
        await auth.on_admin_name(db, io, user, s, event)
    elif s.step == MENU:
        await _on_menu(db, io, s, event)
    elif s.step in FORM_STEPS:
        await referral.on_form(db, io, user, s, ref, event)
    else:
        s.step, s.data, s.submission_key = MENU, {}, None
        await repo.save_session(db, s)
        await show_menu(io, s.language)


async def _on_start(db: Db, io: Io, s: Session, ref: Referrer | None) -> None:
    if s.language is None:
        s.step = LANG
        await repo.save_session(db, s)
        await prompt_language(io)
        return
    if ref is None:
        if s.step not in AUTH_STEPS:
            s.step = AUTH_WAIT_ID
            await repo.save_session(db, s)
        await auth.prompt_auth(io, s)
        return
    if s.step in FORM_STEPS:
        await referral.prompt(io, s)
        return
    s.step, s.data, s.submission_key = MENU, {}, None
    await repo.save_session(db, s)
    await show_menu(io, s.language)


async def _on_cancel(db: Db, io: Io, s: Session, ref: Referrer | None) -> None:
    if s.language is None:
        await _on_start(db, io, s, ref)
        return
    if ref is None:
        s.step = AUTH_WAIT_ID
        await repo.save_session(db, s)
        await auth.prompt_auth(io, s)
        return
    await referral.cancel_form(db, io, s)


async def _on_menu(db: Db, io: Io, s: Session, event: Event) -> None:
    if isinstance(event, Button):
        if event.data == "menu:refer":
            await referral.start_form(db, io, s)
            return
        if event.data == "menu:language":
            s.step = LANG
            await repo.save_session(db, s)
            await prompt_language(io)
            return
        await io.reply(t(s.language, "stale_button"))
    await show_menu(io, s.language)
