import httpx
import pytest

from referrals import repo
from referrals.models import TabeliEmployee
from referrals.tabeli import (
    TabeliError,
    deactivation_allowed,
    fetch_employees,
    parse_bootstrap,
    sync_employees,
)
from tests.factories import EMP_A, EMP_B, EMP_C
from tests.helpers import seed_employees

PAYLOAD = {
    "employees": [
        {"id": EMP_A, "name": " Ivan   Petrov ", "qr_data": EMP_A, "shift": "day"},
        {"id": "", "name": "No Id", "qr_data": "x"},
        "junk",
        {"id": EMP_B, "name": "No Qr"},
    ],
    "windows": {},
}


def test_parse_bootstrap_skips_malformed_entries():
    assert parse_bootstrap(PAYLOAD) == [TabeliEmployee(emplid=EMP_A, qr_data=EMP_A, name="Ivan Petrov")]


@pytest.mark.parametrize("payload", [[], {}, {"employees": None}, "text"])
def test_parse_bootstrap_rejects_bad_payload(payload):
    with pytest.raises(TabeliError):
        parse_bootstrap(payload)


async def test_fetch_employees_calls_bootstrap():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=PAYLOAD)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        employees = await fetch_employees(client, "http://tabeli.local")
    assert seen == ["/api/attendance/bootstrap"]
    assert [e.emplid for e in employees] == [EMP_A]


async def test_fetch_employees_raises_on_http_error():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_employees(client, "http://tabeli.local")


@pytest.mark.parametrize("fetched,active_now,expected", [
    (0, 0, True), (10, 10, True), (5, 10, True), (4, 10, False), (0, 10, False),
])
def test_deactivation_allowed(fetched, active_now, expected):
    assert deactivation_allowed(fetched, active_now) is expected


async def test_sync_deactivates_missing(db):
    await seed_employees(db, (EMP_A, "A A"), (EMP_B, "B B"))
    result = await sync_employees(db, [TabeliEmployee(EMP_A, EMP_A, "A A")])
    assert (result.fetched, result.deactivated, result.skipped_deactivation) == (1, 1, False)
    assert (await repo.find_employee(db, EMP_B)).active is False


async def test_sync_guard_keeps_employees_when_list_shrinks(db):
    await seed_employees(db, (EMP_A, "A A"), (EMP_B, "B B"), (EMP_C, "C C"))
    result = await sync_employees(db, [TabeliEmployee(EMP_A, EMP_A, "A A")])
    assert result.skipped_deactivation is True
    assert await repo.count_active_employees(db) == 3
