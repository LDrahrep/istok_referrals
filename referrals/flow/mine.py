"""«Мои рекомендации»: список своих заявок, карточка и отзыв. Работает на шаге MENU."""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from referrals import repo
from referrals.config import TZ
from referrals.db import Db
from referrals.flow import admin_texts
from referrals.flow.common import show_menu
from referrals.flow.io import Io, SheetReader
from referrals.i18n import t
from referrals.models import Referral, Referrer, Session, WithdrawResult
from referrals.sheet_model import HR_STATUS_HEADER

log = logging.getLogger(__name__)
LIST_LIMIT = 20


def _date(moment: datetime, fmt: str) -> str:
    return moment.astimezone(ZoneInfo(TZ)).strftime(fmt)


def _label(referral: Referral, lang: str | None) -> str:
    label = f"{referral.number} · {referral.first_name} {referral.last_name} · {_date(referral.created_at, '%d.%m')}"
    return f"{label} · {t(lang, 'withdrawn_mark')}" if referral.withdrawn_at else label


async def show_list(db: Db, io: Io, s: Session, ref: Referrer) -> None:
    lang = s.language
    items = await repo.list_referrals_by_referrer(db, ref.emplid, LIST_LIMIT)
    if not items:
        await io.reply(t(lang, "mine_empty"))
        await show_menu(io, lang)
        return
    buttons = [[(_label(r, lang), f"my:show:{r.id}")] for r in items]
    buttons.append([(t(lang, "btn_to_menu"), "my:menu")])
    await io.reply(t(lang, "mine_title"), buttons)


async def _show_card(io: Io, s: Session, referral: Referral) -> None:
    lang = s.language
    text = t(lang, "mine_card", number=referral.number, date=_date(referral.created_at, "%d.%m.%Y"),
             first_name=referral.first_name, last_name=referral.last_name, phone=referral.phone,
             email=referral.email, worked=t(lang, "btn_yes" if referral.worked_before else "btn_no"))
    buttons = []
    if referral.withdrawn_at:
        text += "\n\n" + t(lang, "mine_card_withdrawn", date=_date(referral.withdrawn_at, "%d.%m.%Y"))
    else:
        buttons.append([(t(lang, "btn_withdraw"), f"my:withdraw:{referral.id}")])
    buttons.append([(t(lang, "btn_back_to_list"), "my:list")])
    await io.reply(text, buttons)


async def _own_referral(db: Db, ref: Referrer, raw_id: str) -> Referral | None:
    if not raw_id.isdigit():
        return None
    referral = await repo.get_referral(db, int(raw_id))
    return referral if referral is not None and referral.referrer_emplid == ref.emplid else None


async def _hr_status(sheet: SheetReader | None, referral: Referral) -> str:
    status = None
    if sheet is not None:
        try:
            status = await sheet.hr_status(referral.number)
        except Exception:
            log.exception("не удалось прочитать «Статус» заявки %s из таблицы", referral.number)
    if status is None:
        status = referral.hr_data.get(HR_STATUS_HEADER, "")
    return status.strip()


async def on_button(db: Db, io: Io, s: Session, ref: Referrer, data: str, sheet: SheetReader | None) -> None:
    lang = s.language
    if data in ("menu:mine", "my:list"):
        await show_list(db, io, s, ref)
        return
    if data == "my:menu":
        await show_menu(io, lang)
        return
    action, _, raw_id = data.removeprefix("my:").partition(":")
    referral = await _own_referral(db, ref, raw_id)
    if referral is None or action not in ("show", "withdraw", "confirm"):
        await io.reply(t(lang, "stale_button"))
        await show_list(db, io, s, ref)
        return
    if action == "show":
        await _show_card(io, s, referral)
        return
    if referral.withdrawn_at is not None:
        await io.reply(t(lang, "already_withdrawn", number=referral.number))
        await _show_card(io, s, referral)
        return
    if action == "withdraw":
        await io.reply(t(lang, "withdraw_confirm", number=referral.number),
                       [[(t(lang, "btn_withdraw_yes"), f"my:confirm:{referral.id}")],
                        [(t(lang, "btn_withdraw_no"), f"my:show:{referral.id}")]])
        return
    if await _hr_status(sheet, referral):
        await io.reply(t(lang, "withdraw_blocked"))
        await _show_card(io, s, referral)
        return
    result = await repo.withdraw_referral(db, referral.id, ref.emplid)
    if result is WithdrawResult.WITHDRAWN:
        await io.reply(t(lang, "withdrawn_done", number=referral.number))
        await io.send_admin(admin_texts.withdrawn_text(referral, ref.name))
        io.kick_background()
    elif result is WithdrawResult.ALREADY:
        await io.reply(t(lang, "already_withdrawn", number=referral.number))
    else:
        await io.reply(t(lang, "stale_button"))
    await show_list(db, io, s, ref)
