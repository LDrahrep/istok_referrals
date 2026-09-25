"""Сообщения в чат HR (только по-русски)."""
from __future__ import annotations

from collections.abc import Sequence

from referrals.flow.events import User
from referrals.flow.io import Buttons
from referrals.models import Employee

CARD_OBSOLETE = "Неактуально: сотрудник прошёл проверку сам."


def _who(user: User) -> str:
    name = user.full_name or "без имени"
    username = f" @{user.username}" if user.username else ""
    return f"{name}{username} (id {user.id})"


def verify_request_text(user: User, typed_name: str, matches: Sequence[Employee]) -> str:
    lines = [
        "🔐 Запрос на подтверждение сотрудника",
        f"Telegram: {_who(user)}",
        f"Написал: «{typed_name}»",
        "Совпадения в tabeli — выберите, кто это:" if matches else "Совпадений среди активных сотрудников нет.",
    ]
    return "\n".join(lines)


def verify_request_buttons(user_id: int, matches: Sequence[Employee]) -> Buttons:
    rows = [[(f"Это {m.name} ({m.emplid[:12]}…)", f"v:{user_id}:{m.emplid}")] for m in matches]
    rows.append([("Отклонить", f"x:{user_id}")])
    return rows


def id_taken_text(user: User, employee: Employee) -> str:
    return (f"⚠️ Попытка привязать {employee.name} ({employee.emplid}) с другого Telegram-аккаунта: "
            f"{_who(user)}. Если сотрудник сменил аккаунт — /unbind {employee.emplid}")
