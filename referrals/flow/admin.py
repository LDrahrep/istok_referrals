"""Действия администраторов: подтверждение сотрудника из чата HR и /unbind."""
from __future__ import annotations

from referrals import repo
from referrals.db import Db
from referrals.flow.common import menu_buttons
from referrals.flow.io import Io
from referrals.flow.steps import AUTH_WAIT_ID, MENU
from referrals.i18n import t
from referrals.models import BindResult, Session
from referrals.validation import extract_emp_id

ALREADY_VERIFIED = "Неактуально: сотрудник уже подтверждён."


async def on_admin_button(db: Db, io: Io, admin_id: int, admin_ids: frozenset[int], data: str,
                          card: tuple[int, int]) -> None:
    if admin_id not in admin_ids:
        await io.answer_button("Нет прав")
        return
    await io.answer_button()
    kind, _, rest = data.partition(":")
    if kind == "v":
        tg_text, _, emplid = rest.partition(":")
        await _approve(db, io, int(tg_text), emplid, card)
    elif kind == "x":
        await _reject(db, io, int(rest), card)


async def _approve(db: Db, io: Io, tg_user_id: int, emplid: str, card: tuple[int, int]) -> None:
    if await repo.get_referrer(db, tg_user_id) is not None:
        await io.edit_admin(card, ALREADY_VERIFIED)
        return
    employee = await repo.find_employee(db, emplid)
    if employee is None or not employee.active:
        await io.edit_admin(card, f"Не подтверждено: {emplid} нет среди активных сотрудников.")
        return
    result = await repo.bind_referrer(db, tg_user_id, employee.emplid, None, "admin")
    if result is BindResult.EMPLID_TAKEN:
        await io.edit_admin(card, f"Не подтверждено: {employee.name} уже привязан к другому Telegram-аккаунту.")
        return
    s = await repo.load_session(db, tg_user_id) or Session(tg_user_id=tg_user_id, step=MENU)
    s.step, s.data, s.submission_key = MENU, {}, None
    await repo.save_session(db, s)
    await io.send_user(tg_user_id, t(s.language, "welcome", name=employee.name))
    await io.send_user(tg_user_id, t(s.language, "menu"), menu_buttons(s.language))
    await io.edit_admin(card, f"✅ Подтверждено: {employee.name} ({employee.emplid})")


async def _reject(db: Db, io: Io, tg_user_id: int, card: tuple[int, int]) -> None:
    if await repo.get_referrer(db, tg_user_id) is not None:
        await io.edit_admin(card, ALREADY_VERIFIED)
        return
    s = await repo.load_session(db, tg_user_id)
    if s is not None:
        s.data.pop("admin_card", None)
        await repo.save_session(db, s)
    await io.send_user(tg_user_id, t(s.language if s else None, "admin_rejected"))
    await io.edit_admin(card, "❌ Отклонено")


async def on_unbind(db: Db, io: Io, admin_id: int, admin_ids: frozenset[int], args: tuple[str, ...]) -> None:
    if admin_id not in admin_ids:
        return
    emplid = extract_emp_id(" ".join(args))
    if emplid is None:
        await io.reply("Формат: /unbind EMP-…")
        return
    tg_user_id = await repo.unbind_emplid(db, emplid)
    if tg_user_id is None:
        await io.reply(f"Привязки для {emplid} нет.")
        return
    s = await repo.load_session(db, tg_user_id)
    if s is not None:
        s.step, s.data, s.submission_key = AUTH_WAIT_ID, {}, None
        await repo.save_session(db, s)
    await io.reply(f"Привязка снята: {emplid} (Telegram id {tg_user_id}).")
