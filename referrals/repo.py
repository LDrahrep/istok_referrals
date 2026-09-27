"""Все SQL-запросы бота. Функции принимают Db и возвращают модели из referrals.models."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from psycopg import errors
from psycopg.types.json import Jsonb

from referrals.db import Db
from referrals.models import (
    BindResult,
    CreateResult,
    Employee,
    PhotoBlob,
    Referral,
    ReferralDraft,
    Referrer,
    Session,
    TabeliEmployee,
    WithdrawResult,
    referral_number,
)
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


# ─── заявки ────────────────────────────────────────────────────

_REFERRAL_SELECT = (
    "SELECT id, first_name, last_name, phone, email, worked_before, referrer_tg_user_id, "
    "referrer_emplid, referrer_name, photo_file_id, photo_kind, photo_url, hr_data, created_at, withdrawn_at "
    "FROM referrals"
)


class DuplicateCandidate(Exception):
    """Кандидата с таким телефоном или почтой уже рекомендовали."""

    def __init__(self, existing_id: int) -> None:
        super().__init__(f"кандидат уже есть: {referral_number(existing_id)}")
        self.existing_id = existing_id

    @property
    def number(self) -> str:
        return referral_number(self.existing_id)


async def _referrals(db: Db, where: str = "", params: tuple = ()) -> list[Referral]:
    async with db.connection() as conn:
        cur = await conn.execute(f"{_REFERRAL_SELECT} {where}", params)
        return [Referral(**row) for row in await cur.fetchall()]


async def _find_id(db: Db, column: str, value: str) -> int | None:
    async with db.connection() as conn:
        cur = await conn.execute(f"SELECT id FROM referrals WHERE {column} = %s AND withdrawn_at IS NULL", (value,))
        row = await cur.fetchone()
    return row["id"] if row else None


async def find_referral_by_phone(db: Db, phone: str) -> int | None:
    return await _find_id(db, "phone", phone)


async def find_referral_by_email(db: Db, email: str) -> int | None:
    return await _find_id(db, "email", email)


async def create_referral(db: Db, draft: ReferralDraft, photo: PhotoBlob, next_session: Session) -> CreateResult:
    """Заявка, фото и новое состояние диалога пишутся одной транзакцией."""
    try:
        async with db.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    """INSERT INTO referrals (submission_key, first_name, last_name, phone, email,
                           worked_before, referrer_tg_user_id, referrer_emplid, referrer_name,
                           photo_file_id, photo_kind)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (submission_key) DO NOTHING
                       RETURNING id""",
                    (draft.submission_key, draft.first_name, draft.last_name, draft.phone,
                     draft.email, draft.worked_before, draft.referrer_tg_user_id,
                     draft.referrer_emplid, draft.referrer_name, draft.photo_file_id,
                     draft.photo_kind),
                )
                row = await cur.fetchone()
                if row is None:
                    cur = await conn.execute(
                        "SELECT id FROM referrals WHERE submission_key = %s", (draft.submission_key,)
                    )
                    existing = (await cur.fetchone())["id"]
                    await _save_session(conn, next_session)
                    return CreateResult(existing, created=False)
                await conn.execute(
                    "INSERT INTO referral_photos (referral_id, content, mime_type, size_bytes, sha256) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (row["id"], photo.content, photo.mime_type, len(photo.content), photo.sha256),
                )
                await _save_session(conn, next_session)
                return CreateResult(row["id"], created=True)
    except errors.UniqueViolation as exc:
        existing = await find_referral_by_phone(db, draft.phone) or await find_referral_by_email(db, draft.email)
        if existing is None:
            raise
        raise DuplicateCandidate(existing) from exc


async def all_referrals(db: Db) -> list[Referral]:
    return await _referrals(db, "ORDER BY id")


async def referrals_pending_sheet(db: Db, limit: int = 100) -> list[Referral]:
    return await _referrals(db, "WHERE sheet_synced_at IS NULL ORDER BY id LIMIT %s", (limit,))


async def mark_sheet_synced(db: Db, ids: Sequence[int]) -> None:
    if not ids:
        return
    async with db.connection() as conn:
        await conn.execute(
            "UPDATE referrals SET sheet_synced_at = now() WHERE id = ANY(%s) AND sheet_synced_at IS NULL",
            (list(ids),),
        )


async def apply_sheet_feedback(db: Db, feedback: dict[int, tuple[str | None, dict[str, str]]]) -> None:
    if not feedback:
        return
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(
                "UPDATE referrals SET photo_url = %s, hr_data = %s WHERE id = %s",
                [(url, Jsonb(hr), rid) for rid, (url, hr) in feedback.items()],
            )


async def referrals_pending_notify(db: Db, limit: int = 20) -> list[Referral]:
    return await _referrals(db, "WHERE hr_notified_at IS NULL ORDER BY id LIMIT %s", (limit,))


async def mark_notified(db: Db, referral_id: int) -> None:
    async with db.connection() as conn:
        await conn.execute("UPDATE referrals SET hr_notified_at = now() WHERE id = %s", (referral_id,))


async def stale_photo_referrals(db: Db, older_than: timedelta, limit: int = 20) -> list[Referral]:
    return await _referrals(
        db, "WHERE photo_url IS NULL AND withdrawn_at IS NULL AND created_at < now() - %s ORDER BY id LIMIT %s", (older_than, limit)
    )


async def get_photo(db: Db, referral_id: int) -> PhotoBlob:
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT content, mime_type, sha256 FROM referral_photos WHERE referral_id = %s", (referral_id,)
        )
        row = await cur.fetchone()
    return PhotoBlob(content=bytes(row["content"]), mime_type=row["mime_type"], sha256=row["sha256"])


async def update_photo_file_id(db: Db, referral_id: int, file_id: str) -> None:
    async with db.connection() as conn:
        await conn.execute("UPDATE referrals SET photo_file_id = %s WHERE id = %s", (file_id, referral_id))


async def list_referrals_by_referrer(db: Db, emplid: str, limit: int = 20) -> list[Referral]:
    return await _referrals(db, "WHERE referrer_emplid = %s ORDER BY id DESC LIMIT %s", (emplid, limit))


async def get_referral(db: Db, referral_id: int) -> Referral | None:
    found = await _referrals(db, "WHERE id = %s", (referral_id,))
    return found[0] if found else None


async def withdraw_referral(db: Db, referral_id: int, emplid: str) -> WithdrawResult:
    """Отзыв своей заявки: отметка времени и повторная выгрузка строки в таблицу."""
    async with db.connection() as conn:
        cur = await conn.execute(
            "UPDATE referrals SET withdrawn_at = now(), sheet_synced_at = NULL "
            "WHERE id = %s AND referrer_emplid = %s AND withdrawn_at IS NULL RETURNING id",
            (referral_id, emplid),
        )
        if await cur.fetchone():
            return WithdrawResult.WITHDRAWN
        cur = await conn.execute(
            "SELECT 1 FROM referrals WHERE id = %s AND referrer_emplid = %s", (referral_id, emplid)
        )
        return WithdrawResult.ALREADY if await cur.fetchone() else WithdrawResult.NOT_FOUND
