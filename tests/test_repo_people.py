from uuid import uuid4

from referrals import repo
from referrals.models import BindResult, Session, TabeliEmployee
from tests.factories import EMP_A, EMP_B, EMP_C
from tests.helpers import seed_employees


async def test_upsert_inserts_and_updates(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await seed_employees(db, (EMP_A, "Ivan Petrov-Sidorov"))
    employee = await repo.find_employee(db, EMP_A)
    assert (employee.name, employee.active) == ("Ivan Petrov-Sidorov", True)


async def test_deactivate_missing_and_reactivate(db):
    await seed_employees(db, (EMP_A, "A A"), (EMP_B, "B B"))
    assert await repo.count_active_employees(db) == 2
    assert await repo.deactivate_missing(db, [EMP_A]) == 1
    assert (await repo.find_employee(db, EMP_B)).active is False
    assert await repo.count_active_employees(db) == 1
    await seed_employees(db, (EMP_B, "B B"))
    assert (await repo.find_employee(db, EMP_B)).active is True


async def test_find_employee_by_qr_or_emplid(db):
    await repo.upsert_employees(db, [TabeliEmployee(emplid=EMP_A, qr_data="QR-A", name="A A")])
    assert (await repo.find_employee(db, "QR-A")).emplid == EMP_A
    assert (await repo.find_employee(db, EMP_A)).emplid == EMP_A
    assert await repo.find_employee(db, EMP_B) is None


async def test_search_active_employees_by_name(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"), (EMP_B, "Ivan Sidorov"), (EMP_C, "Petr Ivanov"))
    await repo.deactivate_missing(db, [EMP_A, EMP_B])
    assert [e.emplid for e in await repo.search_active_employees_by_name(db, "petrov  ivan")] == [EMP_A]
    assert [e.emplid for e in await repo.search_active_employees_by_name(db, "Ivan")] == [EMP_A, EMP_B]
    assert await repo.search_active_employees_by_name(db, "Petr Ivanov") == []


async def test_bind_referrer_outcomes(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"), (EMP_B, "B B"))
    assert await repo.bind_referrer(db, 111, EMP_A, "ivan", "qr") is BindResult.BOUND
    assert await repo.bind_referrer(db, 111, EMP_A, "ivan", "qr") is BindResult.ALREADY
    assert await repo.bind_referrer(db, 111, EMP_B, "ivan", "qr") is BindResult.ALREADY
    assert await repo.bind_referrer(db, 222, EMP_A, "other", "manual_id") is BindResult.EMPLID_TAKEN
    referrer = await repo.get_referrer(db, 111)
    assert (referrer.emplid, referrer.name, referrer.active) == (EMP_A, "Ivan Petrov", True)
    assert await repo.get_referrer(db, 222) is None


async def test_referrer_reflects_deactivation(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"), (EMP_B, "B B"))
    await repo.bind_referrer(db, 111, EMP_A, None, "admin")
    await repo.deactivate_missing(db, [EMP_B])
    assert (await repo.get_referrer(db, 111)).active is False


async def test_unbind(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await repo.bind_referrer(db, 111, EMP_A, "ivan", "qr")
    assert await repo.unbind_emplid(db, EMP_A) == 111
    assert await repo.get_referrer(db, 111) is None
    assert await repo.unbind_emplid(db, EMP_A) is None


async def test_session_roundtrip(db):
    assert await repo.load_session(db, 5) is None
    key = uuid4()
    session = Session(tg_user_id=5, step="ref_phone", language="en",
                      data={"first_name": "Aziz", "photo": {"size": 1}}, submission_key=key)
    await repo.save_session(db, session)
    assert await repo.load_session(db, 5) == session
    session.step, session.data, session.submission_key = "menu", {}, None
    await repo.save_session(db, session)
    assert await repo.load_session(db, 5) == Session(tg_user_id=5, step="menu", language="en")
