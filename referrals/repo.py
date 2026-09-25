"""Все SQL-запросы бота. Функции принимают Db и возвращают модели из referrals.models."""
from __future__ import annotations

from collections.abc import Sequence

from psycopg.types.json import Jsonb

from referrals.db import Db
from referrals.models import BindResult, Employee, Referrer, Session, TabeliEmployee
from referrals.validation import name_matches

# ─── сотрудники ────────────────────────────────────────────────


async def upsert_employees(db: Db, employees: Sequence[TabeliEmployee]) -> None:
    if not employees:
        return
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(
                """INSERT INTO employees (emplid, qr_data, name, active, synced_at)
                   VALUES (%s, %s, %s, true, now())
                   ON CONFLICT (emplid) DO UPDATE
                   SET qr_data = EXCLUDED.qr_data, name = EXCLUDED.name,
                       active = true, synced_at = now()""",
                [(e.emplid, e.qr_data, e.name) for e in employees],
            )


async def count_active_employees(db: Db) -> int:
    async with db.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM employees WHERE active")
        return (await cur.fetchone())["n"]


async def deactivate_missing(db: Db, keep: Sequence[str]) -> int:
    async with db.connection() as conn:
        cur = await conn.execute(
            "UPDATE employees SET active = false, synced_at = now() "
            "WHERE active AND NOT (emplid = ANY(%s))",
            (list(keep),),
        )
        return cur.rowcount


async def find_employee(db: Db, code: str) -> Employee | None:
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT emplid, qr_data, name, active FROM employees "
            "WHERE qr_data = %s OR emplid = %s LIMIT 1",
            (code, code),
        )
        row = await cur.fetchone()
    return Employee(**row) if row else None


async def search_active_employees_by_name(db: Db, query: str, limit: int = 5) -> list[Employee]:
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT emplid, qr_data, name, active FROM employees WHERE active ORDER BY name"
        )
        rows = await cur.fetchall()
    return [Employee(**row) for row in rows if name_matches(query, row["name"])][:limit]


# ─── привязки Telegram ↔ сотрудник ─────────────────────────────


async def get_referrer(db: Db, tg_user_id: int) -> Referrer | None:
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT r.tg_user_id, r.emplid, e.name, e.active "
            "FROM referrers r JOIN employees e USING (emplid) WHERE r.tg_user_id = %s",
            (tg_user_id,),
        )
        row = await cur.fetchone()
    return Referrer(**row) if row else None


async def bind_referrer(db: Db, tg_user_id: int, emplid: str, username: str | None, method: str) -> BindResult:
    async with db.connection() as conn:
        cur = await conn.execute(
            "INSERT INTO referrers (tg_user_id, emplid, tg_username, verify_method) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING tg_user_id",
            (tg_user_id, emplid, username, method),
        )
        if await cur.fetchone():
            return BindResult.BOUND
        cur = await conn.execute(
            "SELECT tg_user_id FROM referrers WHERE tg_user_id = %s", (tg_user_id,)
        )
        return BindResult.ALREADY if await cur.fetchone() else BindResult.EMPLID_TAKEN


async def unbind_emplid(db: Db, emplid: str) -> int | None:
    async with db.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM referrers WHERE emplid = %s RETURNING tg_user_id", (emplid,)
        )
        row = await cur.fetchone()
    return row["tg_user_id"] if row else None


# ─── состояние диалога ─────────────────────────────────────────


async def load_session(db: Db, tg_user_id: int) -> Session | None:
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT tg_user_id, step, language, data, submission_key FROM sessions WHERE tg_user_id = %s",
            (tg_user_id,),
        )
        row = await cur.fetchone()
    return Session(**row) if row else None


async def _save_session(conn, session: Session) -> None:
    await conn.execute(
        """INSERT INTO sessions (tg_user_id, language, step, data, submission_key, updated_at)
           VALUES (%s, %s, %s, %s, %s, now())
           ON CONFLICT (tg_user_id) DO UPDATE
           SET language = EXCLUDED.language, step = EXCLUDED.step, data = EXCLUDED.data,
               submission_key = EXCLUDED.submission_key, updated_at = now()""",
        (session.tg_user_id, session.language, session.step, Jsonb(session.data), session.submission_key),
    )


async def save_session(db: Db, session: Session) -> None:
    async with db.connection() as conn:
        await _save_session(conn, session)
