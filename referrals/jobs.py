"""Фоновые задачи. Не зависят от python-telegram-bot: всё внешнее передаётся аргументами."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Protocol

import httpx

from referrals import repo
from referrals.alerts import Alerter
from referrals.db import SHEET_LOCK_KEY, Db, advisory_lock
from referrals.models import PhotoBlob, Referral
from referrals.sheet_model import SheetLayoutError
from referrals.sheets import SheetSyncReport, sync_sheet
from referrals.tabeli import EmployeeSyncResult, fetch_employees, sync_employees


class Notifier(Protocol):
    async def send_referral(self, referral: Referral) -> None: ...

    async def reupload(self, referral: Referral, photo: PhotoBlob) -> str: ...


async def run_employee_sync(db: Db, http: httpx.AsyncClient, tabeli_url: str, alerter: Alerter) -> EmployeeSyncResult:
    employees = await fetch_employees(http, tabeli_url)
    result = await sync_employees(db, employees)
    if result.skipped_deactivation:
        await alerter.alert(
            "tabeli_shrink",
            f"tabeli вернул {result.fetched} сотрудников — меньше половины активных. Деактивация пропущена.",
        )
    return result


async def run_sheet_sync(db: Db, open_ws: Callable[[], object], alerter: Alerter, *, full: bool) -> SheetSyncReport | None:
    async with advisory_lock(db, SHEET_LOCK_KEY) as locked:
        if not locked:
            return None
        referrals = await (repo.all_referrals(db) if full else repo.referrals_pending_sheet(db))
        if not referrals and not full:
            return SheetSyncReport()
        ws = await asyncio.to_thread(open_ws)
        try:
            report = await sync_sheet(db, ws, referrals, full=full)
        except SheetLayoutError as exc:
            await alerter.alert("sheet_layout", f"Таблица «Заявки»: {exc}. Запись в таблицу остановлена.")
            raise
    if full and report.unknown_numbers:
        await alerter.alert(
            "sheet_unknown",
            "В таблице есть строки с номерами, которых нет в базе: " + ", ".join(report.unknown_numbers[:10]),
        )
    if report.duplicate_numbers:
        await alerter.alert(
            "sheet_duplicates",
            "В таблице повторяются номера: " + ", ".join(report.duplicate_numbers[:10]) + ". Эти строки бот не трогает.",
        )
    return report


async def run_notify(db: Db, notifier: Notifier) -> int:
    sent = 0
    for referral in await repo.referrals_pending_notify(db):
        await notifier.send_referral(referral)
        await repo.mark_notified(db, referral.id)
        sent += 1
    return sent


async def run_reupload(db: Db, notifier: Notifier, *, older_than: timedelta = timedelta(hours=24), limit: int = 20) -> int:
    count = 0
    for referral in await repo.stale_photo_referrals(db, older_than, limit):
        photo = await repo.get_photo(db, referral.id)
        new_file_id = await notifier.reupload(referral, photo)
        await repo.update_photo_file_id(db, referral.id, new_file_id)
        count += 1
    return count
