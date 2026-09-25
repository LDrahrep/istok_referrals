"""Настройки из переменных окружения."""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

TZ = "America/Chicago"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    database_url: str
    tabeli_url: str
    google_credentials: dict
    spreadsheet_id: str
    sheet_name: str
    admin_chat_id: int
    admin_user_ids: frozenset[int]


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"не задана переменная окружения {name}")
    return value


def load_config(env: Mapping[str, str] = os.environ) -> Config:
    try:
        credentials = json.loads(_required(env, "GOOGLE_CREDENTIALS"))
    except json.JSONDecodeError as exc:
        raise ConfigError("GOOGLE_CREDENTIALS — не JSON") from exc

    chat = _required(env, "ADMIN_CHAT_ID")
    if not chat.lstrip("-").isdigit():
        raise ConfigError("ADMIN_CHAT_ID должен быть числом")

    admin_ids = []
    for part in _required(env, "ADMIN_USER_IDS").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ConfigError(f"ADMIN_USER_IDS: {part!r} — не число")
        admin_ids.append(int(part))

    return Config(
        telegram_bot_token=_required(env, "TELEGRAM_BOT_TOKEN"),
        database_url=_required(env, "DATABASE_URL"),
        tabeli_url=_required(env, "TABELI_URL").rstrip("/"),
        google_credentials=credentials,
        spreadsheet_id=_required(env, "SPREADSHEET_ID"),
        sheet_name=env.get("SHEET_NAME", "").strip() or "Заявки",
        admin_chat_id=int(chat),
        admin_user_ids=frozenset(admin_ids),
    )
