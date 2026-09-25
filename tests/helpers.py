"""Заполнение тестовой БД."""
from referrals import repo
from referrals.models import Referrer, TabeliEmployee
from tests.factories import EMP_A


async def seed_employees(db, *items: tuple[str, str]) -> None:
    await repo.upsert_employees(db, [TabeliEmployee(emplid=e, qr_data=e, name=n) for e, n in items])


async def seed_referrer(db, tg_user_id: int = 111, emplid: str = EMP_A, name: str = "Ivan Petrov") -> Referrer:
    await seed_employees(db, (emplid, name))
    await repo.bind_referrer(db, tg_user_id, emplid, "ivan", "qr")
    return await repo.get_referrer(db, tg_user_id)
