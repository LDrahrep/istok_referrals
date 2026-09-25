"""Список активных сотрудников из tabeli (GET /api/attendance/bootstrap)."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from referrals import repo
from referrals.db import Db
from referrals.models import TabeliEmployee


class TabeliError(Exception):
    pass


def parse_bootstrap(payload: object) -> list[TabeliEmployee]:
    if not isinstance(payload, dict) or not isinstance(payload.get("employees"), list):
        raise TabeliError("ответ bootstrap без списка employees")
    result = []
    for item in payload["employees"]:
        if not isinstance(item, dict):
            continue
        emplid, qr_data, name = item.get("id"), item.get("qr_data"), item.get("name")
        if not all(isinstance(v, str) and v.strip() for v in (emplid, qr_data, name)):
            continue
        result.append(TabeliEmployee(emplid=emplid.strip(), qr_data=qr_data.strip(), name=" ".join(name.split())))
    return result


async def fetch_employees(client: httpx.AsyncClient, base_url: str) -> list[TabeliEmployee]:
    response = await client.get(f"{base_url}/api/attendance/bootstrap", timeout=20)
    response.raise_for_status()
    return parse_bootstrap(response.json())


def deactivation_allowed(fetched: int, active_now: int) -> bool:
    """Предохранитель: если tabeli вернул меньше половины активных — это сбой, а не увольнения."""
    return active_now == 0 or fetched * 2 >= active_now


@dataclass(frozen=True)
class EmployeeSyncResult:
    fetched: int
    deactivated: int
    skipped_deactivation: bool


async def sync_employees(db: Db, employees: Sequence[TabeliEmployee]) -> EmployeeSyncResult:
    active_now = await repo.count_active_employees(db)
    await repo.upsert_employees(db, employees)
    if not deactivation_allowed(len(employees), active_now):
        return EmployeeSyncResult(len(employees), 0, True)
    deactivated = await repo.deactivate_missing(db, [e.emplid for e in employees])
    return EmployeeSyncResult(len(employees), deactivated, False)
