# Istok Referrals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Telegram-бот, который проверяет сотрудника по QR/ID из tabeli и принимает анкету кандидата, храня всё в Postgres и зеркаля в Google-таблицу для HR.

**Architecture:** Python-воркер на Railway (long polling) + Postgres на Railway как источник правды. Диалог — чистая логика в `referrals/flow/` поверх интерфейса `Io` (тестируется без Telegram); тонкий адаптер python-telegram-bot в `referrals/app.py`. Фоновые задачи (JobQueue) синхронизируют сотрудников из tabeli и заявки с Google Sheets; фото на Диск загружает отдельный GAS-скрипт.

**Tech Stack:** Python 3.14, python-telegram-bot 22 (+job-queue), psycopg 3 (async pool), gspread 6, httpx, phonenumbers, zxing-cpp + Pillow + numpy, pytest + pytest-asyncio, Postgres 16 (Docker для тестов).

**Spec:** `docs/superpowers/specs/2026-09-25-istok-referrals-design.md`

**Отступление от раздела 10 спецификации (только структура):** вместо `referrals/handlers/` логика диалога лежит в `referrals/flow/` (чистые функции над `Io`), а Telegram-обвязка — в `referrals/app.py`. Добавлены `models.py`, `sheet_model.py` (чистая логика таблицы), `alerts.py`.

## Global Constraints

- Python 3.14 (`.python-version`), зависимости закреплены точными версиями в `requirements.txt`.
- Часовой пояс отображения — `America/Chicago` (константа `referrals.config.TZ`).
- Номер заявки — `R-%06d` (`referral_number`).
- Все записи в Google-таблицу — с `value_input_option="RAW"`.
- Бот никогда не удаляет строки таблицы и не пишет в колонку `Фото` и колонки HR; в коде нет `DELETE FROM referrals`.
- Заголовки колонок бота ровно: `№`, `Дата`, `Имя`, `Фамилия`, `Телефон`, `Почта`, `Работал у нас`, `Рекомендатель`, `Emplid рекомендателя`, `file_id`; колонка GAS — `Фото`.
- Лимит файла — 20 МБ (`20 * 1024 * 1024`).
- Кнопка «попросить админа» — после 3 неудач; алерт повторяющегося сбоя — после 3 падений подряд, не чаще раза в час на тип.
- Advisory-ключи: миграции `7_401_001`, таблица `7_401_002`.
- `run_polling(drop_pending_updates=False)`.
- Тесты: `.venv/bin/pytest`; тесты с БД требуют контейнер `referrals-test-pg` на порту 55432.
- Каждый коммит заканчивается строкой `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` (второй `-m`).

## Review Focus

- Нажатие устаревшей inline-кнопки из старого сообщения (например «Да» на шаге телефона) → «кнопка неактуальна» + повтор вопроса; шаг и черновик не меняются. Тест: Task 10 `test_stale_button_keeps_step`.
- Файл больше 20 МБ на шаге QR и на шаге фото ворка → отклоняется без скачивания. Тесты: Task 10 `test_photo_step_validation`, Task 11 `test_oversized_document_not_downloaded`.
- Сессия старой версии: шаг подтверждения без фото в черновике → анкета начинается заново, без падения. Тест: Task 10 `test_incomplete_draft_restarts_form`.
- Альбом из нескольких фото на шаге фото ворка: второе фото приходит уже на шаге подтверждения → напоминание, в черновике остаётся первое. Тест: Task 10 `test_second_photo_at_confirm_is_ignored`.
- Уволенный сотрудник с привязкой → на любое сообщение «доступ закрыт». Тест: Task 11 `test_deactivated_referrer_gets_access_closed`.

## File Structure

```
referrals/
  __init__.py
  __main__.py            # python -m referrals
  config.py              # Config, load_config, TZ
  validation.py          # имена, телефон, почта, EMP-ID, поиск по имени
  qr.py                  # decode_emp_id
  models.py              # dataclass-модели и referral_number
  db.py                  # Db (пул), migrate, advisory_lock
  migrations/__init__.py
  migrations/001_init.sql
  repo.py                # все SQL-запросы
  tabeli.py              # загрузка bootstrap и sync_employees
  sheet_model.py         # раскладка таблицы и план сверки (без I/O)
  sheets.py              # open_worksheet, sync_sheet
  alerts.py              # Alerter, FailureTracker
  jobs.py                # фоновые задачи без привязки к PTB
  i18n/__init__.py, ru.py, en.py
  flow/__init__.py
  flow/events.py         # User и события
  flow/io.py             # протокол Io
  flow/steps.py          # имена шагов и константы
  flow/common.py         # меню, язык, кнопки навигации
  flow/referral.py       # анкета и отправка
  flow/admin_texts.py    # тексты для чата HR
  flow/auth.py           # язык и проверка сотрудника
  flow/router.py         # handle_event
  flow/admin.py          # кнопки v:/x:, /unbind
  app.py                 # адаптер python-telegram-bot, задачи, main
gas/photos.gs
tests/ (__init__.py, conftest.py, factories.py, helpers.py, fakes.py, qr_images.py, test_*.py)
docs/DEPLOY.md
requirements.txt, requirements-dev.txt, pyproject.toml, Procfile, .python-version, mise.toml
```

---

### Task 1: Скелет проекта, конфигурация, валидация ввода

**Files:**
- Create: `.python-version`, `mise.toml`, `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `Procfile`, `referrals/__init__.py`, `referrals/config.py`, `referrals/validation.py`, `tests/__init__.py`, `tests/test_config.py`, `tests/test_validation.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `referrals.config.TZ: str`, `Config` (поля `telegram_bot_token, database_url, tabeli_url, google_credentials: dict, spreadsheet_id, sheet_name, admin_chat_id: int, admin_user_ids: frozenset[int]`), `ConfigError`, `load_config(env: Mapping[str, str] = os.environ) -> Config`; `referrals.validation`: `clean_name(raw) -> str | None`, `normalize_phone(raw) -> str | None`, `normalize_email(raw) -> str | None`, `extract_emp_id(text) -> str | None`, `parse_emp_id(text) -> str | None`, `name_matches(query, full_name) -> bool`.

- [ ] **Step 1: Файлы окружения**

`.python-version`:
```
3.14
```

`mise.toml` (как в боте водителей — обход сбоя attestation на Railway):
```toml
[settings]
python.github_attestations = false
```

`requirements.txt` (диапазоны; на шаге 3 заменяются точными версиями):
```
python-telegram-bot[job-queue]>=22.5,<23
psycopg[binary,pool]>=3.2,<4
gspread>=6.2,<7
google-auth>=2.30,<3
httpx>=0.27,<1
phonenumbers>=8.13,<10
zxing-cpp>=3.1,<4
Pillow>=11,<13
numpy>=2,<3
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest>=8
pytest-asyncio>=0.24
qrcode>=8
```

`pyproject.toml`:
```toml
[project]
name = "istok-referrals"
version = "0.1.0"
requires-python = ">=3.12"

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
pythonpath = ["."]
```

`Procfile`:
```
worker: python -m referrals
```

Добавить в `.gitignore` строку:
```
.pytest_cache/
```

Создать пустые `referrals/__init__.py` и `tests/__init__.py`.

- [ ] **Step 2: Виртуальное окружение**

Run: `/opt/homebrew/bin/python3.14 -m venv .venv && .venv/bin/pip install -q -r requirements-dev.txt`
Expected: установка без ошибок.

- [ ] **Step 3: Закрепить версии**

Run: `.venv/bin/pip freeze | grep -i -E '^(python-telegram-bot|psycopg|psycopg-binary|psycopg-pool|gspread|google-auth|httpx|phonenumbers|zxing-cpp|pillow|numpy)=='`
Заменить диапазоны в `requirements.txt` на точные версии из вывода, сохранив extras: `python-telegram-bot[job-queue]==<версия>`, `psycopg[binary,pool]==<версия psycopg>`, остальные `name==<версия>`.

- [ ] **Step 4: Тесты конфигурации (падают)**

`tests/test_config.py`:
```python
import pytest

from referrals.config import ConfigError, load_config

BASE = {
    "TELEGRAM_BOT_TOKEN": "123:abc",
    "DATABASE_URL": "postgresql://user:pw@host/db",
    "TABELI_URL": "http://1.2.3.4/",
    "GOOGLE_CREDENTIALS": '{"type": "service_account"}',
    "SPREADSHEET_ID": "sheet-id",
    "ADMIN_CHAT_ID": "-1001",
    "ADMIN_USER_IDS": "11, 22",
}


def test_load_config_parses_values():
    cfg = load_config(BASE)
    assert cfg.telegram_bot_token == "123:abc"
    assert cfg.tabeli_url == "http://1.2.3.4"
    assert cfg.google_credentials == {"type": "service_account"}
    assert cfg.admin_chat_id == -1001
    assert cfg.admin_user_ids == frozenset({11, 22})
    assert cfg.sheet_name == "Заявки"


def test_custom_sheet_name():
    assert load_config({**BASE, "SHEET_NAME": "Test"}).sheet_name == "Test"


@pytest.mark.parametrize("name", sorted(BASE))
def test_missing_variable_is_reported(name):
    env = dict(BASE)
    del env[name]
    with pytest.raises(ConfigError, match=name):
        load_config(env)


def test_bad_admin_ids():
    with pytest.raises(ConfigError, match="ADMIN_USER_IDS"):
        load_config({**BASE, "ADMIN_USER_IDS": "11,abc"})


def test_bad_admin_chat():
    with pytest.raises(ConfigError, match="ADMIN_CHAT_ID"):
        load_config({**BASE, "ADMIN_CHAT_ID": "chat"})


def test_bad_credentials_json():
    with pytest.raises(ConfigError, match="GOOGLE_CREDENTIALS"):
        load_config({**BASE, "GOOGLE_CREDENTIALS": "{not json"})
```

- [ ] **Step 5: Тесты валидации (падают)**

`tests/test_validation.py`:
```python
import pytest

from referrals.validation import (
    clean_name,
    extract_emp_id,
    name_matches,
    normalize_email,
    normalize_phone,
    parse_emp_id,
)

EMP = "EMP-7b682ed0-2485-44fe-a727-d40f8d7e0f42"


@pytest.mark.parametrize("raw,expected", [
    ("Ivan", "Ivan"),
    ("  Иван  ", "Иван"),
    ("Mary-Jane", "Mary-Jane"),
    ("O'Brien", "O'Brien"),
    ("Abdukakhor   Abdugaforov", "Abdukakhor Abdugaforov"),
    ("Ғайратҷон", "Ғайратҷон"),
    ("Oʻgʻiloy", "Oʻgʻiloy"),
])
def test_clean_name_accepts(raw, expected):
    assert clean_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "Ivan2", "-Ivan", "Ivan-", "Iv--an", "Ivan!", "李雷", "a" * 51])
def test_clean_name_rejects(raw):
    assert clean_name(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("(650) 253-0000", "+16502530000"),
    ("650.253.0000", "+16502530000"),
    ("+1 650 253 0000", "+16502530000"),
    ("+7 912 345-67-89", "+79123456789"),
])
def test_normalize_phone_accepts(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "12345", "phone", "+1 000 000 0000", "650-253-000"])
def test_normalize_phone_rejects(raw):
    assert normalize_phone(raw) is None


def test_normalize_email():
    assert normalize_email(" Ivan.Petrov@Gmail.com ") == "ivan.petrov@gmail.com"


@pytest.mark.parametrize("raw", ["", "ivan", "ivan@", "ivan@gmail", "iv an@gmail.com", "@gmail.com"])
def test_normalize_email_rejects(raw):
    assert normalize_email(raw) is None


def test_extract_emp_id_finds_id_in_text():
    assert extract_emp_id(f"мой id {EMP.upper().replace('EMP-', 'emp-')} спасибо") == EMP
    assert extract_emp_id(f"  {EMP}\n") == EMP
    assert extract_emp_id("EMP-123") is None
    assert extract_emp_id("") is None


def test_parse_emp_id_requires_exact_value():
    assert parse_emp_id(f"  {EMP.upper()} ") == EMP
    assert parse_emp_id(f"id {EMP}") is None


@pytest.mark.parametrize("query,name,expected", [
    ("ivan petrov", "Ivan Petrov", True),
    ("Petrov  Ivan", "Ivan Petrov", True),
    ("Petrov", "Ivan Petrov", True),
    ("Ivan Sidorov", "Ivan Petrov", False),
    ("", "Ivan Petrov", False),
])
def test_name_matches(query, name, expected):
    assert name_matches(query, name) is expected
```

- [ ] **Step 6: Убедиться, что тесты падают**

Run: `.venv/bin/pytest tests/test_config.py tests/test_validation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'referrals.config'`.

- [ ] **Step 7: Реализация**

`referrals/config.py`:
```python
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
```

`referrals/validation.py`:
```python
"""Проверка и нормализация ввода: имена, телефоны, почта, ID сотрудника."""
from __future__ import annotations

import re
import unicodedata

import phonenumbers

NAME_MAX_LEN = 50
_NAME_SEPARATORS = frozenset(" -'’ʻ")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_EMP_RE = re.compile(rf"EMP-({_UUID})", re.IGNORECASE)


def _is_name_letter(ch: str) -> bool:
    return ch.isalpha() and unicodedata.name(ch, "").startswith(("LATIN", "CYRILLIC"))


def clean_name(raw: str) -> str | None:
    name = " ".join(raw.split())
    if not 1 <= len(name) <= NAME_MAX_LEN:
        return None
    if not (_is_name_letter(name[0]) and _is_name_letter(name[-1])):
        return None
    previous_was_separator = False
    for ch in name:
        if ch in _NAME_SEPARATORS:
            if previous_was_separator:
                return None
            previous_was_separator = True
        elif _is_name_letter(ch):
            previous_was_separator = False
        else:
            return None
    return name


def normalize_phone(raw: str) -> str | None:
    try:
        number = phonenumbers.parse(raw, "US")
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalize_email(raw: str) -> str | None:
    email = raw.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return None
    return email


def extract_emp_id(text: str) -> str | None:
    match = _EMP_RE.search(text)
    return f"EMP-{match.group(1).lower()}" if match else None


def parse_emp_id(text: str) -> str | None:
    match = _EMP_RE.fullmatch(text.strip())
    return f"EMP-{match.group(1).lower()}" if match else None


def _name_tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[\s\-]+", text.casefold()) if token]


def name_matches(query: str, full_name: str) -> bool:
    wanted = _name_tokens(query)
    have = set(_name_tokens(full_name))
    return bool(wanted) and all(token in have for token in wanted)
```

- [ ] **Step 8: Тесты проходят**

Run: `.venv/bin/pytest tests/test_config.py tests/test_validation.py -q`
Expected: PASS. Если какой-то номер телефона из параметров библиотека считает невалидным — заменить его на другой реальный номер того же формата, а не ослаблять проверку.

- [ ] **Step 9: Commit**

```bash
git add .python-version mise.toml requirements.txt requirements-dev.txt pyproject.toml Procfile .gitignore referrals tests
git commit -m "feat: скелет проекта, конфигурация и валидация ввода" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Чтение QR-кода с фото

**Files:**
- Create: `referrals/qr.py`, `tests/qr_images.py`, `tests/test_qr.py`

**Interfaces:**
- Consumes: `referrals.validation.parse_emp_id`.
- Produces: `referrals.qr.decode_emp_id(data: bytes) -> str | None`; тестовые помощники `tests.qr_images`: `qr_image(text, size=300)`, `in_scene(img)`, `to_bytes(img, fmt="JPEG")`, `qr_photo_jpeg(text) -> bytes`, `blank_photo_jpeg() -> bytes`.

- [ ] **Step 1: Помощники для генерации тестовых фото**

`tests/qr_images.py`:
```python
"""Синтетические «фото бейджа» для тестов QR."""
import io

import numpy as np
import qrcode
from PIL import Image


def qr_image(text: str, size: int = 300) -> Image.Image:
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=10)
    code.add_data(text)
    code.make(fit=True)
    img = code.make_image(fill_color="black", back_color="white").convert("L")
    return img.resize((size, size), Image.NEAREST)


def in_scene(img: Image.Image, width: int = 1280, height: int = 960) -> Image.Image:
    rng = np.random.default_rng(1)
    background = Image.fromarray(np.clip(rng.normal(150, 35, (height, width)), 0, 255).astype("uint8"))
    background.paste(img, ((width - img.width) // 2, (height - img.height) // 2))
    return background


def to_bytes(img: Image.Image, fmt: str = "JPEG") -> bytes:
    buffer = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buffer, fmt, quality=80)
    else:
        img.save(buffer, fmt)
    return buffer.getvalue()


def qr_photo_jpeg(text: str) -> bytes:
    return to_bytes(in_scene(qr_image(text)))


def blank_photo_jpeg() -> bytes:
    return to_bytes(in_scene(Image.new("L", (300, 300), 235)))
```

- [ ] **Step 2: Тесты (падают)**

`tests/test_qr.py`:
```python
from PIL import Image, ImageFilter

from referrals.qr import decode_emp_id
from tests.qr_images import blank_photo_jpeg, in_scene, qr_image, qr_photo_jpeg, to_bytes

EMP = "EMP-7b682ed0-2485-44fe-a727-d40f8d7e0f42"


def test_decodes_clean_png():
    assert decode_emp_id(to_bytes(qr_image(EMP), "PNG")) == EMP


def test_decodes_phone_photo():
    assert decode_emp_id(qr_photo_jpeg(EMP)) == EMP


def test_decodes_small_qr_in_big_frame():
    assert decode_emp_id(to_bytes(in_scene(qr_image(EMP, 150)))) == EMP


def test_decodes_rotated():
    assert decode_emp_id(to_bytes(in_scene(qr_image(EMP)).rotate(35, fillcolor=150))) == EMP


def test_decodes_blurred():
    assert decode_emp_id(to_bytes(in_scene(qr_image(EMP)).filter(ImageFilter.GaussianBlur(2)))) == EMP


def test_normalizes_uppercase_id():
    assert decode_emp_id(qr_photo_jpeg(EMP.upper())) == EMP


def test_ignores_qr_with_other_text():
    assert decode_emp_id(qr_photo_jpeg("https://example.com")) is None


def test_photo_without_qr():
    assert decode_emp_id(blank_photo_jpeg()) is None


def test_garbage_bytes():
    assert decode_emp_id(b"not an image") is None


def test_empty_bytes():
    assert decode_emp_id(b"") is None
```

- [ ] **Step 3: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_qr.py -q`
Expected: FAIL — `No module named 'referrals.qr'`.

- [ ] **Step 4: Реализация**

`referrals/qr.py`:
```python
"""Чтение ID сотрудника (EMP-<uuid>) с фото QR-кода на бейдже."""
from __future__ import annotations

import io

import numpy as np
import zxingcpp
from PIL import Image, ImageOps, UnidentifiedImageError

from referrals.validation import parse_emp_id


def decode_emp_id(data: bytes) -> str | None:
    try:
        image = Image.open(io.BytesIO(data))
        gray = ImageOps.exif_transpose(image).convert("L")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None
    for attempt in (gray, ImageOps.autocontrast(gray, cutoff=2)):
        for code in zxingcpp.read_barcodes(np.asarray(attempt), formats=zxingcpp.BarcodeFormat.QRCode):
            emplid = parse_emp_id(code.text)
            if emplid:
                return emplid
    return None
```

- [ ] **Step 5: Тесты проходят**

Run: `.venv/bin/pytest tests/test_qr.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add referrals/qr.py tests/qr_images.py tests/test_qr.py
git commit -m "feat: чтение EMP-ID из QR на фото (zxing-cpp)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: База данных — миграции, пул, advisory-блокировки, тестовая инфраструктура

**Files:**
- Create: `referrals/migrations/__init__.py` (пустой), `referrals/migrations/001_init.sql`, `referrals/db.py`, `tests/conftest.py`, `tests/factories.py`, `tests/test_db.py`

**Interfaces:**
- Produces: `referrals.db.Db` (`await Db.connect(url, *, max_size=5)`, `await db.close()`, `db.connection()` — async context manager пула), `migrate(url) -> list[str]` (применённые версии), `advisory_lock(db, key)` — async context manager, отдаёт `bool`; константы `MIGRATION_LOCK_KEY = 7_401_001`, `SHEET_LOCK_KEY = 7_401_002`. Фикстуры: `migrated_url` (session), `db` (function, пустые таблицы). `tests.factories`: `EMP_A`, `EMP_B`, `EMP_C`.

- [ ] **Step 1: Запустить Postgres для тестов**

Run: `docker run -d --name referrals-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16-alpine || docker start referrals-test-pg`
Expected: контейнер запущен (`docker ps` показывает `referrals-test-pg`).

- [ ] **Step 2: Миграция**

`referrals/migrations/001_init.sql`:
```sql
CREATE TABLE employees (
  emplid     text PRIMARY KEY,
  qr_data    text NOT NULL UNIQUE,
  name       text NOT NULL,
  active     boolean NOT NULL DEFAULT true,
  synced_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE referrers (
  tg_user_id     bigint PRIMARY KEY,
  emplid         text NOT NULL UNIQUE REFERENCES employees(emplid),
  tg_username    text,
  verify_method  text NOT NULL CHECK (verify_method IN ('qr', 'manual_id', 'admin')),
  verified_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  tg_user_id      bigint PRIMARY KEY,
  language        text CHECK (language IN ('ru', 'en')),
  step            text NOT NULL,
  data            jsonb NOT NULL DEFAULT '{}',
  submission_key  uuid,
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE referrals (
  id                   bigserial PRIMARY KEY,
  submission_key       uuid NOT NULL UNIQUE,
  first_name           text NOT NULL,
  last_name            text NOT NULL,
  phone                text NOT NULL UNIQUE CHECK (phone ~ '^\+[1-9][0-9]{6,14}$'),
  email                text NOT NULL UNIQUE CHECK (email = lower(email)),
  worked_before        boolean NOT NULL,
  referrer_tg_user_id  bigint NOT NULL,
  referrer_emplid      text NOT NULL REFERENCES employees(emplid),
  referrer_name        text NOT NULL,
  photo_file_id        text NOT NULL,
  photo_kind           text NOT NULL CHECK (photo_kind IN ('photo', 'document')),
  photo_url            text,
  hr_data              jsonb NOT NULL DEFAULT '{}',
  created_at           timestamptz NOT NULL DEFAULT now(),
  sheet_synced_at      timestamptz,
  hr_notified_at       timestamptz
);

CREATE INDEX referrals_sheet_pending ON referrals (id) WHERE sheet_synced_at IS NULL;
CREATE INDEX referrals_notify_pending ON referrals (id) WHERE hr_notified_at IS NULL;

CREATE TABLE referral_photos (
  referral_id  bigint PRIMARY KEY REFERENCES referrals(id),
  content      bytea NOT NULL,
  mime_type    text NOT NULL,
  size_bytes   integer NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 20971520),
  sha256       text NOT NULL
);
```

- [ ] **Step 3: Фикстуры и фабрики**

`tests/factories.py`:
```python
"""Фабрики тестовых данных без обращения к БД."""
from datetime import datetime, timezone
from uuid import uuid4

from referrals.models import PhotoBlob, Referral, ReferralDraft

EMP_A = "EMP-00000000-0000-4000-8000-00000000000a"
EMP_B = "EMP-00000000-0000-4000-8000-00000000000b"
EMP_C = "EMP-00000000-0000-4000-8000-00000000000c"


def make_draft(**overrides) -> ReferralDraft:
    values = dict(
        submission_key=uuid4(), first_name="Aziz", last_name="Karimov",
        phone="+16502530000", email="aziz@example.com", worked_before=False,
        referrer_tg_user_id=111, referrer_emplid=EMP_A, referrer_name="Ivan Petrov",
        photo_file_id="file-1", photo_kind="photo",
    )
    values.update(overrides)
    return ReferralDraft(**values)


def make_photo(content: bytes = b"\xff\xd8photo-bytes", mime: str = "image/jpeg") -> PhotoBlob:
    return PhotoBlob.from_bytes(content, mime)


def make_referral(id: int = 1, **overrides) -> Referral:
    values = dict(
        id=id, first_name="Aziz", last_name="Karimov", phone="+16502530000",
        email="aziz@example.com", worked_before=True, referrer_tg_user_id=111,
        referrer_emplid=EMP_A, referrer_name="Ivan Petrov", photo_file_id="file-1",
        photo_kind="photo", photo_url=None, hr_data={},
        created_at=datetime(2026, 9, 25, 19, 3, tzinfo=timezone.utc),
    )
    values.update(overrides)
    return Referral(**values)
```

`tests/factories.py` импортирует `referrals.models` — модели создаются в этой же задаче (шаг 5), до запуска тестов.

`tests/conftest.py`:
```python
import asyncio
import os

import psycopg
import pytest
import pytest_asyncio

from referrals.db import Db, migrate

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:test@localhost:55432/postgres"
)
TABLES = "referral_photos, referrals, sessions, referrers, employees"


@pytest.fixture(scope="session")
def migrated_url() -> str:
    try:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute("DROP SCHEMA public CASCADE")
            conn.execute("CREATE SCHEMA public")
    except psycopg.OperationalError as exc:
        pytest.fail(
            f"Postgres для тестов недоступен ({exc}). Запустите: docker run -d --name "
            "referrals-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16-alpine"
        )
    asyncio.run(migrate(TEST_DATABASE_URL))
    return TEST_DATABASE_URL


@pytest_asyncio.fixture
async def db(migrated_url):
    database = await Db.connect(migrated_url, max_size=3)
    async with database.connection() as conn:
        await conn.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
    yield database
    await database.close()
```

- [ ] **Step 4: Тесты (падают)**

`tests/test_db.py`:
```python
import psycopg
import pytest

from referrals.db import SHEET_LOCK_KEY, advisory_lock, migrate
from tests.factories import EMP_A

INSERT_REFERRAL = """
INSERT INTO referrals (submission_key, first_name, last_name, phone, email, worked_before,
    referrer_tg_user_id, referrer_emplid, referrer_name, photo_file_id, photo_kind)
VALUES (gen_random_uuid(), 'A', 'B', %s, %s, false, 1, %s, 'R', 'f', %s)
"""


async def test_migrate_is_idempotent(migrated_url):
    assert await migrate(migrated_url) == []


@pytest.mark.parametrize("phone,email,kind", [
    ("6502530000", "a@b.co", "photo"),
    ("+16502530000", "A@b.co", "photo"),
    ("+16502530000", "a@b.co", "video"),
])
async def test_referral_check_constraints(db, phone, email, kind):
    async with db.connection() as conn:
        await conn.execute("INSERT INTO employees (emplid, qr_data, name) VALUES (%s, %s, 'A')", (EMP_A, EMP_A))
    with pytest.raises(psycopg.errors.CheckViolation):
        async with db.connection() as conn:
            await conn.execute(INSERT_REFERRAL, (phone, email, EMP_A, kind))


async def test_advisory_lock_is_exclusive(db):
    async with advisory_lock(db, SHEET_LOCK_KEY) as first:
        async with advisory_lock(db, SHEET_LOCK_KEY) as second:
            assert first is True
            assert second is False
    async with advisory_lock(db, SHEET_LOCK_KEY) as again:
        assert again is True
```

- [ ] **Step 5: Модели (нужны фабрикам)**

`referrals/models.py`:
```python
"""Модели данных, общие для всех модулей."""
from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


def referral_number(referral_id: int) -> str:
    return f"R-{referral_id:06d}"


@dataclass(frozen=True)
class TabeliEmployee:
    emplid: str
    qr_data: str
    name: str


@dataclass(frozen=True)
class Employee:
    emplid: str
    qr_data: str
    name: str
    active: bool


@dataclass(frozen=True)
class Referrer:
    tg_user_id: int
    emplid: str
    name: str
    active: bool


class BindResult(enum.Enum):
    BOUND = "bound"
    ALREADY = "already"
    EMPLID_TAKEN = "emplid_taken"


@dataclass
class Session:
    tg_user_id: int
    step: str
    language: str | None = None
    data: dict = field(default_factory=dict)
    submission_key: UUID | None = None


@dataclass(frozen=True)
class PhotoBlob:
    content: bytes
    mime_type: str
    sha256: str

    @classmethod
    def from_bytes(cls, content: bytes, mime_type: str) -> PhotoBlob:
        if not content:
            raise ValueError("пустой файл фото")
        data = bytes(content)
        return cls(data, mime_type, hashlib.sha256(data).hexdigest())


@dataclass(frozen=True)
class ReferralDraft:
    submission_key: UUID
    first_name: str
    last_name: str
    phone: str
    email: str
    worked_before: bool
    referrer_tg_user_id: int
    referrer_emplid: str
    referrer_name: str
    photo_file_id: str
    photo_kind: str


@dataclass(frozen=True)
class Referral:
    id: int
    first_name: str
    last_name: str
    phone: str
    email: str
    worked_before: bool
    referrer_tg_user_id: int
    referrer_emplid: str
    referrer_name: str
    photo_file_id: str
    photo_kind: str
    photo_url: str | None
    hr_data: dict
    created_at: datetime

    @property
    def number(self) -> str:
        return referral_number(self.id)


@dataclass(frozen=True)
class CreateResult:
    id: int
    created: bool

    @property
    def number(self) -> str:
        return referral_number(self.id)
```

- [ ] **Step 6: Убедиться, что тесты падают**

Run: `.venv/bin/pytest tests/test_db.py -q`
Expected: FAIL — `No module named 'referrals.db'`.

- [ ] **Step 7: Реализация db.py**

`referrals/db.py`:
```python
"""Подключение к Postgres, миграции и advisory-блокировки."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import resources

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

MIGRATION_LOCK_KEY = 7_401_001
SHEET_LOCK_KEY = 7_401_002


class Db:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, url: str, *, max_size: int = 5) -> Db:
        pool = AsyncConnectionPool(
            url, min_size=1, max_size=max_size, open=False, kwargs={"row_factory": dict_row}
        )
        await pool.open(wait=True, timeout=30)
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    def connection(self):
        return self.pool.connection()


def migration_files() -> list[tuple[str, str]]:
    folder = resources.files("referrals.migrations")
    files = sorted((f for f in folder.iterdir() if f.name.endswith(".sql")), key=lambda f: f.name)
    return [(f.name.removesuffix(".sql"), f.read_text(encoding="utf-8")) for f in files]


async def migrate(url: str) -> list[str]:
    """Применяет новые SQL-файлы из referrals/migrations по порядку, каждый в своей транзакции."""
    applied: list[str] = []
    async with await psycopg.AsyncConnection.connect(url, autocommit=True, row_factory=dict_row) as conn:
        await conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
        try:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            cur = await conn.execute("SELECT version FROM schema_migrations")
            done = {row["version"] for row in await cur.fetchall()}
            for version, sql in migration_files():
                if version in done:
                    continue
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                applied.append(version)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
    return applied


@asynccontextmanager
async def advisory_lock(db: Db, key: int) -> AsyncIterator[bool]:
    """Неблокирующая сессионная блокировка Postgres: True — взяли, False — держит кто-то другой."""
    async with db.connection() as conn:
        cur = await conn.execute("SELECT pg_try_advisory_lock(%s) AS locked", (key,))
        locked = (await cur.fetchone())["locked"]
        await conn.commit()
        try:
            yield locked
        finally:
            if locked:
                await conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
                await conn.commit()
```

- [ ] **Step 8: Тесты проходят**

Run: `.venv/bin/pytest tests/test_db.py -q`
Expected: PASS (5 тестов).

- [ ] **Step 9: Commit**

```bash
git add referrals/models.py referrals/db.py referrals/migrations tests/conftest.py tests/factories.py tests/test_db.py
git commit -m "feat: схема Postgres, миграции и advisory-блокировки" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Репозиторий — сотрудники, привязки, сессии

**Files:**
- Create: `referrals/repo.py`, `tests/helpers.py`, `tests/test_repo_people.py`

**Interfaces:**
- Consumes: `Db`, модели из `referrals.models`, `referrals.validation.name_matches`.
- Produces (`referrals.repo`, все `async`, первый аргумент `db: Db`): `upsert_employees(db, employees: Sequence[TabeliEmployee]) -> None`, `count_active_employees(db) -> int`, `deactivate_missing(db, keep: Sequence[str]) -> int`, `find_employee(db, code: str) -> Employee | None` (по `qr_data` или `emplid`), `search_active_employees_by_name(db, query, limit=5) -> list[Employee]`, `get_referrer(db, tg_user_id) -> Referrer | None`, `bind_referrer(db, tg_user_id, emplid, username, method) -> BindResult`, `unbind_emplid(db, emplid) -> int | None`, `load_session(db, tg_user_id) -> Session | None`, `save_session(db, session) -> None`. Помощники тестов: `tests.helpers.seed_employees(db, *items: tuple[str, str])`, `seed_referrer(db, tg_user_id=111, emplid=EMP_A, name="Ivan Petrov") -> Referrer`.

- [ ] **Step 1: Помощники тестов**

`tests/helpers.py`:
```python
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
```

- [ ] **Step 2: Тесты (падают)**

`tests/test_repo_people.py`:
```python
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
```

- [ ] **Step 3: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_repo_people.py -q`
Expected: FAIL — `cannot import name 'repo'`.

- [ ] **Step 4: Реализация (первая часть repo.py)**

`referrals/repo.py`:
```python
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
```

- [ ] **Step 5: Тесты проходят**

Run: `.venv/bin/pytest tests/test_repo_people.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add referrals/repo.py tests/helpers.py tests/test_repo_people.py
git commit -m "feat: репозиторий — сотрудники, привязки, сессии" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Репозиторий — заявки

**Files:**
- Modify: `referrals/repo.py` (добавить в конец), `tests/helpers.py` (не меняется)
- Create: `tests/test_repo_referrals.py`

**Interfaces:**
- Consumes: `Session`, `ReferralDraft`, `PhotoBlob`, `Referral`, `CreateResult`, `referral_number`.
- Produces (`referrals.repo`): `DuplicateCandidate(Exception)` с `.existing_id: int` и `.number: str`; `find_referral_by_phone(db, phone) -> int | None`; `find_referral_by_email(db, email) -> int | None`; `create_referral(db, draft, photo, next_session) -> CreateResult` (атомарно: заявка + фото + сохранение `next_session`; повтор `submission_key` → `created=False`; дубль телефона/почты → `DuplicateCandidate`, всё откатывается); `all_referrals(db) -> list[Referral]`; `referrals_pending_sheet(db, limit=100) -> list[Referral]`; `mark_sheet_synced(db, ids) -> None`; `apply_sheet_feedback(db, feedback: dict[int, tuple[str | None, dict[str, str]]]) -> None`; `referrals_pending_notify(db, limit=20) -> list[Referral]`; `mark_notified(db, referral_id) -> None`; `stale_photo_referrals(db, older_than: timedelta, limit=20) -> list[Referral]`; `get_photo(db, referral_id) -> PhotoBlob`; `update_photo_file_id(db, referral_id, file_id) -> None`.

- [ ] **Step 1: Тесты (падают)**

`tests/test_repo_referrals.py`:
```python
from datetime import timedelta

import pytest

from referrals import repo
from referrals.models import PhotoBlob, Session
from tests.factories import EMP_A, make_draft, make_photo
from tests.helpers import seed_referrer


def menu_session(tg_user_id: int = 111) -> Session:
    return Session(tg_user_id=tg_user_id, step="menu", language="ru")


async def count(db, table: str) -> int:
    async with db.connection() as conn:
        cur = await conn.execute(f"SELECT count(*) AS n FROM {table}")
        return (await cur.fetchone())["n"]


async def test_create_referral_stores_referral_photo_and_session(db):
    await seed_referrer(db)
    await repo.save_session(db, Session(tg_user_id=111, step="ref_confirm", data={"x": 1}))
    photo = make_photo()
    result = await repo.create_referral(db, make_draft(), photo, menu_session())
    assert result.created and result.number == "R-000001"
    assert await repo.get_photo(db, result.id) == photo
    assert (await repo.load_session(db, 111)).step == "menu"
    [referral] = await repo.all_referrals(db)
    assert (referral.phone, referral.referrer_emplid, referral.photo_kind, referral.hr_data) == (
        "+16502530000", EMP_A, "photo", {})


async def test_same_submission_key_creates_one_referral(db):
    await seed_referrer(db)
    draft = make_draft()
    first = await repo.create_referral(db, draft, make_photo(), menu_session())
    second = await repo.create_referral(db, draft, make_photo(), menu_session())
    assert (second.id, second.created) == (first.id, False)
    assert await count(db, "referrals") == 1
    assert await count(db, "referral_photos") == 1


async def test_duplicate_phone_rolls_back_everything(db):
    await seed_referrer(db)
    first = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    await repo.save_session(db, Session(tg_user_id=111, step="ref_confirm", data={"keep": True}))
    with pytest.raises(repo.DuplicateCandidate) as err:
        await repo.create_referral(db, make_draft(email="other@example.com"), make_photo(), menu_session())
    assert err.value.existing_id == first.id
    assert err.value.number == "R-000001"
    assert await count(db, "referrals") == 1
    assert await count(db, "referral_photos") == 1
    assert (await repo.load_session(db, 111)).data == {"keep": True}


async def test_duplicate_email_detected(db):
    await seed_referrer(db)
    first = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    with pytest.raises(repo.DuplicateCandidate) as err:
        await repo.create_referral(db, make_draft(phone="+16502530001"), make_photo(), menu_session())
    assert err.value.existing_id == first.id


async def test_find_by_phone_and_email(db):
    await seed_referrer(db)
    created = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    assert await repo.find_referral_by_phone(db, "+16502530000") == created.id
    assert await repo.find_referral_by_email(db, "aziz@example.com") == created.id
    assert await repo.find_referral_by_phone(db, "+16502530009") is None
    assert await repo.find_referral_by_email(db, "nobody@example.com") is None


async def test_sheet_sync_bookkeeping(db):
    await seed_referrer(db)
    a = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    b = await repo.create_referral(db, make_draft(phone="+16502530001", email="b@example.com"), make_photo(), menu_session())
    assert [r.id for r in await repo.referrals_pending_sheet(db)] == [a.id, b.id]
    await repo.mark_sheet_synced(db, [a.id])
    await repo.mark_sheet_synced(db, [])
    assert [r.id for r in await repo.referrals_pending_sheet(db)] == [b.id]


async def test_apply_sheet_feedback(db):
    await seed_referrer(db)
    created = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    await repo.apply_sheet_feedback(db, {created.id: ("https://drive/x", {"Статус": "Позвонили"})})
    [referral] = await repo.all_referrals(db)
    assert (referral.photo_url, referral.hr_data) == ("https://drive/x", {"Статус": "Позвонили"})


async def test_notify_bookkeeping(db):
    await seed_referrer(db)
    created = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    assert [r.id for r in await repo.referrals_pending_notify(db)] == [created.id]
    await repo.mark_notified(db, created.id)
    assert await repo.referrals_pending_notify(db) == []


async def test_stale_photos_and_file_id_update(db):
    await seed_referrer(db)
    a = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    b = await repo.create_referral(db, make_draft(phone="+16502530001", email="b@example.com"), make_photo(), menu_session())
    async with db.connection() as conn:
        await conn.execute("UPDATE referrals SET created_at = now() - interval '2 days'")
    await repo.apply_sheet_feedback(db, {b.id: ("https://drive/b", {})})
    assert [r.id for r in await repo.stale_photo_referrals(db, timedelta(hours=24))] == [a.id]
    await repo.update_photo_file_id(db, a.id, "new-file")
    assert (await repo.all_referrals(db))[0].photo_file_id == "new-file"


def test_photo_blob_rejects_empty():
    with pytest.raises(ValueError):
        PhotoBlob.from_bytes(b"", "image/jpeg")
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_repo_referrals.py -q`
Expected: FAIL — `AttributeError: module 'referrals.repo' has no attribute 'create_referral'` (и аналогичные).

- [ ] **Step 3: Реализация**

В `referrals/repo.py` дополнить импорты:
```python
from datetime import timedelta

from psycopg import errors

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
    referral_number,
)
```
(заменить прежнюю строку импорта моделей) и добавить в конец файла:
```python
# ─── заявки ────────────────────────────────────────────────────

_REFERRAL_SELECT = (
    "SELECT id, first_name, last_name, phone, email, worked_before, referrer_tg_user_id, "
    "referrer_emplid, referrer_name, photo_file_id, photo_kind, photo_url, hr_data, created_at "
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
        cur = await conn.execute(f"SELECT id FROM referrals WHERE {column} = %s", (value,))
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
        db, "WHERE photo_url IS NULL AND created_at < now() - %s ORDER BY id LIMIT %s", (older_than, limit)
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
```

- [ ] **Step 4: Тесты проходят**

Run: `.venv/bin/pytest tests/test_repo_referrals.py tests/test_repo_people.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add referrals/repo.py tests/test_repo_referrals.py
git commit -m "feat: репозиторий — атомарное создание заявок и служебные выборки" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: tabeli — загрузка и синхронизация сотрудников

**Files:**
- Create: `referrals/tabeli.py`, `tests/test_tabeli.py`

**Interfaces:**
- Consumes: `repo.upsert_employees`, `repo.count_active_employees`, `repo.deactivate_missing`, `TabeliEmployee`.
- Produces: `TabeliError`, `parse_bootstrap(payload) -> list[TabeliEmployee]`, `async fetch_employees(client: httpx.AsyncClient, base_url: str) -> list[TabeliEmployee]`, `deactivation_allowed(fetched: int, active_now: int) -> bool`, `EmployeeSyncResult(fetched: int, deactivated: int, skipped_deactivation: bool)`, `async sync_employees(db, employees) -> EmployeeSyncResult`.

- [ ] **Step 1: Тесты (падают)**

`tests/test_tabeli.py`:
```python
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
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_tabeli.py -q`
Expected: FAIL — `No module named 'referrals.tabeli'`.

- [ ] **Step 3: Реализация**

`referrals/tabeli.py`:
```python
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
```

- [ ] **Step 4: Тесты проходят**

Run: `.venv/bin/pytest tests/test_tabeli.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add referrals/tabeli.py tests/test_tabeli.py
git commit -m "feat: загрузка сотрудников из tabeli с предохранителем деактивации" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Модель таблицы «Заявки» (чистая логика)

**Files:**
- Create: `referrals/sheet_model.py`, `tests/test_sheet_model.py`

**Interfaces:**
- Consumes: `Referral`, `referral_number`, `TZ`.
- Produces: константы `ID_HEADER = "№"`, `FILE_ID_HEADER = "file_id"`, `PHOTO_HEADER = "Фото"`, `BOT_HEADERS: tuple[str, ...]`, `REQUIRED_HEADERS`; `SheetLayoutError`; `Layout(columns: dict[str, int], hr_columns: dict[str, int], width: int)`; `CellUpdate(row: int, col: int, value: str)` (0-based индексы в `values`, строка 0 — заголовок); `ReconcilePlan(appends: list[Referral], cell_updates: list[CellUpdate], feedback: dict[int, tuple[str | None, dict[str, str]]], unknown_numbers: list[str], duplicate_ids: list[int])`; функции `parse_layout(header_row) -> Layout`, `format_created(dt) -> str`, `bot_cells(referral) -> dict[str, str]` (в порядке `BOT_HEADERS`), `build_row(layout, referral) -> list[str]`, `parse_number(cell) -> int | None`, `plan_reconcile(values, referrals) -> tuple[Layout, ReconcilePlan]`.

- [ ] **Step 1: Тесты (падают)**

`tests/test_sheet_model.py`:
```python
from datetime import datetime, timezone

import pytest

from referrals.sheet_model import (
    BOT_HEADERS,
    PHOTO_HEADER,
    CellUpdate,
    SheetLayoutError,
    bot_cells,
    build_row,
    format_created,
    parse_layout,
    parse_number,
    plan_reconcile,
)
from tests.factories import make_referral

HEADER = [*BOT_HEADERS, PHOTO_HEADER, "Статус", "Заметки"]
PHONE_COL = BOT_HEADERS.index("Телефон")


def sheet_row(referral, photo="", status="", notes=""):
    return [*bot_cells(referral).values(), photo, status, notes]


def test_parse_layout_standard():
    layout = parse_layout(HEADER)
    assert layout.columns["№"] == 0
    assert layout.columns[PHOTO_HEADER] == 10
    assert layout.hr_columns == {"Статус": 11, "Заметки": 12}
    assert layout.width == 13


def test_parse_layout_any_order_and_spaces():
    layout = parse_layout(["Заметки", f" {PHOTO_HEADER} ", *reversed(BOT_HEADERS)])
    assert layout.columns["№"] == 11
    assert layout.columns[PHOTO_HEADER] == 1
    assert layout.hr_columns == {"Заметки": 0}


def test_missing_header_is_error():
    with pytest.raises(SheetLayoutError, match="Почта"):
        parse_layout([h for h in HEADER if h != "Почта"])


def test_duplicate_bot_header_is_error():
    with pytest.raises(SheetLayoutError, match="Телефон"):
        parse_layout([*HEADER, "Телефон"])


def test_duplicate_hr_header_is_ignored():
    assert "Статус" not in parse_layout([*HEADER, "Статус"]).hr_columns


def test_format_created_uses_chicago_time():
    assert format_created(datetime(2026, 9, 25, 19, 3, tzinfo=timezone.utc)) == "2026-09-25 14:03"
    assert format_created(datetime(2026, 1, 15, 19, 3, tzinfo=timezone.utc)) == "2026-01-15 13:03"


def test_bot_cells():
    cells = bot_cells(make_referral(worked_before=False))
    assert list(cells) == list(BOT_HEADERS)
    assert cells["№"] == "R-000001"
    assert cells["Работал у нас"] == "Нет"
    assert cells["Дата"] == "2026-09-25 14:03"


def test_build_row_follows_layout():
    layout = parse_layout(["Заметки", *reversed(BOT_HEADERS), PHOTO_HEADER])
    row = build_row(layout, make_referral())
    assert len(row) == layout.width
    assert row[layout.columns["Телефон"]] == "+16502530000"
    assert row[0] == "" and row[layout.columns[PHOTO_HEADER]] == ""


@pytest.mark.parametrize("cell,expected", [
    ("R-000123", 123), (" R-000007 ", 7), ("R-0001234", 1234), ("R-12", None), ("123", None), ("", None),
])
def test_parse_number(cell, expected):
    assert parse_number(cell) == expected


def test_plan_appends_missing_rows():
    r1, r2 = make_referral(1), make_referral(2, phone="+16502530001")
    _, plan = plan_reconcile([HEADER], [r1, r2])
    assert plan.appends == [r1, r2]
    assert plan.cell_updates == [] and plan.feedback == {}


def test_plan_is_empty_when_in_sync():
    r1 = make_referral(1)
    _, plan = plan_reconcile([HEADER, sheet_row(r1)], [r1])
    assert (plan.appends, plan.cell_updates, plan.feedback) == ([], [], {})


def test_plan_repairs_changed_cell():
    r1 = make_referral(1)
    row = sheet_row(r1)
    row[PHONE_COL] = "6502530000"
    _, plan = plan_reconcile([HEADER, row], [r1])
    assert plan.cell_updates == [CellUpdate(1, PHONE_COL, "+16502530000")]


def test_plan_reads_photo_and_hr_columns():
    r1 = make_referral(1)
    _, plan = plan_reconcile([HEADER, sheet_row(r1, photo="https://drive/x", status="Позвонили")], [r1])
    assert plan.feedback == {1: ("https://drive/x", {"Статус": "Позвонили"})}


def test_plan_reports_unknown_and_duplicate_rows():
    r1 = make_referral(1)
    values = [HEADER, sheet_row(r1), sheet_row(r1), ["R-000099"], ["мусор"]]
    _, plan = plan_reconcile(values, [r1])
    assert plan.duplicate_ids == [1]
    assert plan.unknown_numbers == ["R-000099", "мусор"]
    assert plan.appends == [] and plan.cell_updates == []


def test_plan_handles_blank_and_short_rows():
    r1, r2 = make_referral(1), make_referral(2, phone="+16502530001")
    values = [HEADER, [], ["", ""], sheet_row(r2)[:3]]
    _, plan = plan_reconcile(values, [r1, r2])
    assert plan.appends == [r1]
    assert {u.col for u in plan.cell_updates} == set(range(3, len(BOT_HEADERS)))
    assert all(u.row == 3 for u in plan.cell_updates)
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_sheet_model.py -q`
Expected: FAIL — `No module named 'referrals.sheet_model'`.

- [ ] **Step 3: Реализация**

`referrals/sheet_model.py`:
```python
"""Раскладка таблицы «Заявки» и расчёт расхождений с базой. Без ввода-вывода."""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from referrals.config import TZ
from referrals.models import Referral, referral_number

ID_HEADER = "№"
FILE_ID_HEADER = "file_id"
PHOTO_HEADER = "Фото"
BOT_HEADERS = (
    ID_HEADER, "Дата", "Имя", "Фамилия", "Телефон", "Почта",
    "Работал у нас", "Рекомендатель", "Emplid рекомендателя", FILE_ID_HEADER,
)
REQUIRED_HEADERS = (*BOT_HEADERS, PHOTO_HEADER)
_NUMBER_RE = re.compile(r"R-(\d{6,})")


class SheetLayoutError(Exception):
    pass


@dataclass(frozen=True)
class Layout:
    columns: dict[str, int]
    hr_columns: dict[str, int]
    width: int


@dataclass(frozen=True)
class CellUpdate:
    row: int
    col: int
    value: str


@dataclass
class ReconcilePlan:
    appends: list[Referral] = field(default_factory=list)
    cell_updates: list[CellUpdate] = field(default_factory=list)
    feedback: dict[int, tuple[str | None, dict[str, str]]] = field(default_factory=dict)
    unknown_numbers: list[str] = field(default_factory=list)
    duplicate_ids: list[int] = field(default_factory=list)


def parse_layout(header_row: Sequence[str]) -> Layout:
    positions: dict[str, int] = {}
    duplicates: set[str] = set()
    for index, raw in enumerate(header_row):
        header = str(raw).strip()
        if not header:
            continue
        if header in positions:
            duplicates.add(header)
        else:
            positions[header] = index
    missing = [h for h in REQUIRED_HEADERS if h not in positions]
    if missing:
        raise SheetLayoutError("нет заголовков: " + ", ".join(missing))
    doubled = [h for h in REQUIRED_HEADERS if h in duplicates]
    if doubled:
        raise SheetLayoutError("заголовки повторяются: " + ", ".join(doubled))
    columns = {h: positions[h] for h in REQUIRED_HEADERS}
    hr_columns = {h: i for h, i in positions.items() if h not in columns and h not in duplicates}
    return Layout(columns, hr_columns, len(header_row))


def format_created(created_at: datetime) -> str:
    return created_at.astimezone(ZoneInfo(TZ)).strftime("%Y-%m-%d %H:%M")


def bot_cells(referral: Referral) -> dict[str, str]:
    return {
        ID_HEADER: referral_number(referral.id),
        "Дата": format_created(referral.created_at),
        "Имя": referral.first_name,
        "Фамилия": referral.last_name,
        "Телефон": referral.phone,
        "Почта": referral.email,
        "Работал у нас": "Да" if referral.worked_before else "Нет",
        "Рекомендатель": referral.referrer_name,
        "Emplid рекомендателя": referral.referrer_emplid,
        FILE_ID_HEADER: referral.photo_file_id,
    }


def build_row(layout: Layout, referral: Referral) -> list[str]:
    row = [""] * layout.width
    for header, value in bot_cells(referral).items():
        row[layout.columns[header]] = value
    return row


def parse_number(cell: str) -> int | None:
    match = _NUMBER_RE.fullmatch(cell.strip())
    return int(match.group(1)) if match else None


def _cell(row: Sequence[str], index: int) -> str:
    return str(row[index]) if index < len(row) else ""


def plan_reconcile(values: Sequence[Sequence[str]], referrals: Sequence[Referral]) -> tuple[Layout, ReconcilePlan]:
    """Что нужно дописать/исправить в таблице и что забрать из колонок «Фото» и HR."""
    layout = parse_layout(values[0] if values else [])
    id_col = layout.columns[ID_HEADER]
    photo_col = layout.columns[PHOTO_HEADER]
    known = {r.id for r in referrals}
    row_of: dict[int, int] = {}
    duplicates: set[int] = set()
    plan = ReconcilePlan()

    for index in range(1, len(values)):
        cell = _cell(values[index], id_col).strip()
        if not cell:
            continue
        number = parse_number(cell)
        if number is None or number not in known:
            plan.unknown_numbers.append(cell)
        elif number in row_of:
            duplicates.add(number)
        else:
            row_of[number] = index
    plan.duplicate_ids = sorted(duplicates)

    for referral in referrals:
        if referral.id in duplicates:
            continue
        index = row_of.get(referral.id)
        if index is None:
            plan.appends.append(referral)
            continue
        row = values[index]
        for header, value in bot_cells(referral).items():
            col = layout.columns[header]
            if _cell(row, col) != value:
                plan.cell_updates.append(CellUpdate(index, col, value))
        photo = _cell(row, photo_col).strip() or None
        hr = {h: _cell(row, c) for h, c in layout.hr_columns.items() if _cell(row, c).strip()}
        if photo != referral.photo_url or hr != referral.hr_data:
            plan.feedback[referral.id] = (photo, hr)
    return layout, plan
```

- [ ] **Step 4: Тесты проходят**

Run: `.venv/bin/pytest tests/test_sheet_model.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add referrals/sheet_model.py tests/test_sheet_model.py
git commit -m "feat: раскладка таблицы «Заявки» и план сверки с базой" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Синхронизация с Google Sheets

**Files:**
- Create: `referrals/sheets.py`, `tests/fakes.py`, `tests/test_sheets.py`

**Interfaces:**
- Consumes: `plan_reconcile`, `build_row`, `SheetLayoutError`, `repo.mark_sheet_synced`, `repo.apply_sheet_feedback`, `referral_number`.
- Produces: `open_worksheet(credentials: dict, spreadsheet_id: str, sheet_name: str) -> gspread.Worksheet`; `SheetSyncReport(appended=0, updated_cells=0, feedback=0, unknown_numbers=[], duplicate_numbers=[])`; `async sync_sheet(db, ws, referrals) -> SheetSyncReport` — `ws` любой объект с `get_all_values()`, `batch_update(data, value_input_option=...)`, `update(values=..., range_name=..., value_input_option=...)`, `row_count`, `add_rows(n)`. Бросает `SheetLayoutError` до любой записи. `tests.fakes.FakeSheet(rows, row_count=1000)` с полями `grid`, `row_count`, `writes: list[tuple[str, str | None]]` и методом `column(header) -> list[str]`.

- [ ] **Step 1: Фейковый лист**

`tests/fakes.py`:
```python
"""Фейки внешних систем для тестов."""
from gspread.utils import a1_to_rowcol


class FakeSheet:
    """Имитация gspread.Worksheet: сетка строк, лимит строк как у настоящего листа."""

    def __init__(self, rows, row_count: int = 1000):
        self.grid = [list(r) for r in rows]
        self.row_count = row_count
        self.writes: list[tuple[str, str | None]] = []

    def get_all_values(self):
        rows = [list(r) for r in self.grid]
        while rows and not any(str(c).strip() for c in rows[-1]):
            rows.pop()
        width = max((len(r) for r in rows), default=0)
        return [r + [""] * (width - len(r)) for r in rows]

    def _write(self, row: int, col: int, value: str) -> None:
        if row > self.row_count:
            raise ValueError(f"row {row} exceeds grid limits ({self.row_count})")
        while len(self.grid) < row:
            self.grid.append([])
        line = self.grid[row - 1]
        while len(line) < col:
            line.append("")
        line[col - 1] = value

    def _write_block(self, top_left: str, values) -> None:
        row, col = a1_to_rowcol(top_left)
        for i, line in enumerate(values):
            for j, value in enumerate(line):
                self._write(row + i, col + j, value)

    def batch_update(self, data, value_input_option=None):
        self.writes.append(("batch_update", value_input_option))
        for item in data:
            self._write_block(item["range"], item["values"])

    def update(self, values=None, range_name=None, value_input_option=None):
        self.writes.append(("update", value_input_option))
        self._write_block(range_name, values)

    def add_rows(self, count: int) -> None:
        self.row_count += count

    def column(self, header: str) -> list[str]:
        values = self.get_all_values()
        index = values[0].index(header)
        return [row[index] for row in values[1:]]
```

- [ ] **Step 2: Тесты (падают)**

`tests/test_sheets.py`:
```python
import pytest

from referrals import repo
from referrals.models import Session
from referrals.sheet_model import BOT_HEADERS, PHOTO_HEADER, SheetLayoutError
from referrals.sheets import sync_sheet
from tests.factories import make_draft, make_photo
from tests.fakes import FakeSheet
from tests.helpers import seed_referrer

HEADER = [*BOT_HEADERS, PHOTO_HEADER, "Статус"]


async def create_referrals(db, n: int):
    await seed_referrer(db)
    for i in range(n):
        draft = make_draft(phone=f"+1650253000{i}", email=f"c{i}@example.com")
        await repo.create_referral(db, draft, make_photo(), Session(tg_user_id=111, step="menu"))
    return await repo.all_referrals(db)


async def test_appends_below_existing_rows_as_raw(db):
    referrals = await create_referrals(db, 2)
    hr_only = [""] * len(BOT_HEADERS) + ["", "заметка без номера"]
    sheet = FakeSheet([HEADER, hr_only])
    report = await sync_sheet(db, sheet, referrals)
    assert report.appended == 2
    assert sheet.column("№") == ["", "R-000001", "R-000002"]
    assert sheet.writes and all(option == "RAW" for _, option in sheet.writes)
    assert await repo.referrals_pending_sheet(db) == []


async def test_grows_grid_when_needed(db):
    referrals = await create_referrals(db, 3)
    sheet = FakeSheet([HEADER], row_count=2)
    await sync_sheet(db, sheet, referrals)
    assert sheet.row_count >= 4
    assert sheet.column("№") == ["R-000001", "R-000002", "R-000003"]


async def test_repairs_deleted_row_and_overwritten_cell(db):
    referrals = await create_referrals(db, 2)
    sheet = FakeSheet([HEADER])
    await sync_sheet(db, sheet, referrals)
    sheet.grid[1][HEADER.index("Телефон")] = "испорчено"
    del sheet.grid[2]
    report = await sync_sheet(db, sheet, referrals)
    assert (report.updated_cells, report.appended) == (1, 1)
    assert sheet.column("Телефон") == ["+16502530000", "+16502530001"]


async def test_reads_back_photo_and_hr_columns(db):
    referrals = await create_referrals(db, 1)
    sheet = FakeSheet([HEADER])
    await sync_sheet(db, sheet, referrals)
    sheet.grid[1][HEADER.index(PHOTO_HEADER)] = "https://drive/1"
    sheet.grid[1][HEADER.index("Статус")] = "Позвонили"
    report = await sync_sheet(db, sheet, await repo.all_referrals(db))
    [referral] = await repo.all_referrals(db)
    assert report.feedback == 1
    assert (referral.photo_url, referral.hr_data) == ("https://drive/1", {"Статус": "Позвонили"})
    assert (await sync_sheet(db, sheet, await repo.all_referrals(db))).feedback == 0


async def test_second_sync_writes_nothing(db):
    referrals = await create_referrals(db, 2)
    sheet = FakeSheet([HEADER])
    await sync_sheet(db, sheet, referrals)
    writes = len(sheet.writes)
    report = await sync_sheet(db, sheet, referrals)
    assert len(sheet.writes) == writes
    assert (report.appended, report.updated_cells) == (0, 0)


async def test_layout_error_writes_and_marks_nothing(db):
    referrals = await create_referrals(db, 1)
    sheet = FakeSheet([["№", "Дата"]])
    with pytest.raises(SheetLayoutError):
        await sync_sheet(db, sheet, referrals)
    assert sheet.writes == []
    assert len(await repo.referrals_pending_sheet(db)) == 1


async def test_duplicate_rows_are_left_alone(db):
    referrals = await create_referrals(db, 1)
    sheet = FakeSheet([HEADER])
    await sync_sheet(db, sheet, referrals)
    sheet.grid.append(list(sheet.grid[1]))
    sheet.grid[2][HEADER.index("Телефон")] = "x"
    report = await sync_sheet(db, sheet, referrals)
    assert report.duplicate_numbers == ["R-000001"]
    assert report.updated_cells == 0
```

- [ ] **Step 3: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_sheets.py -q`
Expected: FAIL — `No module named 'referrals.sheets'`.

- [ ] **Step 4: Реализация**

`referrals/sheets.py`:
```python
"""Запись заявок в Google-таблицу «Заявки» и обратное чтение колонок GAS/HR."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

import gspread
from gspread.utils import rowcol_to_a1

from referrals import repo
from referrals.db import Db
from referrals.models import Referral, referral_number
from referrals.sheet_model import build_row, plan_reconcile


@dataclass
class SheetSyncReport:
    appended: int = 0
    updated_cells: int = 0
    feedback: int = 0
    unknown_numbers: list[str] = field(default_factory=list)
    duplicate_numbers: list[str] = field(default_factory=list)


def open_worksheet(credentials: dict, spreadsheet_id: str, sheet_name: str) -> gspread.Worksheet:
    client = gspread.service_account_from_dict(credentials)
    return client.open_by_key(spreadsheet_id).worksheet(sheet_name)


async def sync_sheet(db: Db, ws, referrals: Sequence[Referral]) -> SheetSyncReport:
    """Приводит колонки бота к базе, дописывает недостающие строки, забирает «Фото» и колонки HR."""
    values = await asyncio.to_thread(ws.get_all_values)
    layout, plan = plan_reconcile(values, referrals)

    if plan.cell_updates:
        data = [{"range": rowcol_to_a1(u.row + 1, u.col + 1), "values": [[u.value]]} for u in plan.cell_updates]
        await asyncio.to_thread(ws.batch_update, data, value_input_option="RAW")

    if plan.appends:
        start = len(values) + 1
        rows = [build_row(layout, r) for r in plan.appends]
        last = start + len(rows) - 1
        if last > ws.row_count:
            await asyncio.to_thread(ws.add_rows, last - ws.row_count)
        await asyncio.to_thread(ws.update, values=rows, range_name=f"A{start}", value_input_option="RAW")

    duplicates = set(plan.duplicate_ids)
    await repo.mark_sheet_synced(db, [r.id for r in referrals if r.id not in duplicates])
    await repo.apply_sheet_feedback(db, plan.feedback)
    return SheetSyncReport(
        appended=len(plan.appends),
        updated_cells=len(plan.cell_updates),
        feedback=len(plan.feedback),
        unknown_numbers=plan.unknown_numbers,
        duplicate_numbers=[referral_number(i) for i in plan.duplicate_ids],
    )
```

- [ ] **Step 5: Тесты проходят**

Run: `.venv/bin/pytest tests/test_sheets.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add referrals/sheets.py tests/fakes.py tests/test_sheets.py
git commit -m "feat: синхронизация заявок с Google-таблицей (RAW, upsert по №, сверка)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Тексты RU/EN

**Files:**
- Create: `referrals/i18n/__init__.py`, `referrals/i18n/ru.py`, `referrals/i18n/en.py`, `tests/test_i18n.py`

**Interfaces:**
- Produces: `referrals.i18n.LANGS = ("ru", "en")`, `t(lang: str | None, key: str, **kwargs) -> str` (`None` и неизвестный язык → русский). Ключи: `choose_language, ask_id, qr_not_read, not_an_id, send_photo_or_id, not_found, id_taken, btn_ask_admin, ask_full_name_for_admin, admin_request_sent, admin_rejected, welcome{name}, menu, btn_refer, btn_language, access_closed, ask_first_name, ask_last_name, bad_name, ask_phone, bad_phone, ask_email, bad_email, already_referred{number}, ask_worked, btn_yes, btn_no, ask_photo, bad_photo, confirm{first_name,last_name,phone,email,worked}, btn_submit, btn_restart, btn_cancel, btn_back, submitted{number}, submit_failed_download, stale_button, cancelled, use_buttons`.

- [ ] **Step 1: Тесты (падают)**

`tests/test_i18n.py`:
```python
from string import Formatter

from referrals.i18n import LANGS, en, ru, t


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(template) if name}


def test_languages_have_same_keys_and_placeholders():
    assert set(ru.TEXTS) == set(en.TEXTS)
    for key in ru.TEXTS:
        assert placeholders(ru.TEXTS[key]) == placeholders(en.TEXTS[key]), key


def test_t_formats_and_falls_back_to_russian():
    assert LANGS == ("ru", "en")
    assert t("en", "welcome", name="Ivan") == en.TEXTS["welcome"].format(name="Ivan")
    assert t(None, "menu") == ru.TEXTS["menu"]
    assert t("de", "menu") == ru.TEXTS["menu"]
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_i18n.py -q`
Expected: FAIL — `No module named 'referrals.i18n'`.

- [ ] **Step 3: Реализация**

`referrals/i18n/ru.py`:
```python
TEXTS = {
    "choose_language": "Выберите язык / Choose language",
    "ask_id": "Чтобы рекомендовать кандидата, подтвердите, что вы сотрудник Istok.\n\nПришлите фото QR-кода с вашего бейджа или вставьте ваш ID текстом (вида EMP-…).",
    "qr_not_read": "Не удалось прочитать QR-код. Наклоните бейдж, чтобы не было блика, и снимите ближе. Можно прислать фото файлом — без сжатия. Или вставьте ID текстом.",
    "not_an_id": "Это не похоже на ID. Пришлите фото QR-кода с бейджа или ID вида EMP-…",
    "send_photo_or_id": "Пришлите фото QR-кода с бейджа или ID текстом.",
    "not_found": "Не нашли вас среди активных сотрудников. Проверьте QR-код или ID и попробуйте ещё раз.",
    "id_taken": "Этот ID уже привязан к другому Telegram-аккаунту. Администратор получил уведомление.",
    "btn_ask_admin": "Не получается — попросить админа",
    "ask_full_name_for_admin": "Напишите ваши имя и фамилию, как в табеле. Администратор проверит и подтвердит.",
    "admin_request_sent": "Запрос отправлен администратору. Пока ждёте, можно снова прислать фото QR-кода или ID.",
    "admin_rejected": "Администратор не подтвердил запрос. Попробуйте ещё раз прислать фото QR-кода или ID.",
    "welcome": "Здравствуйте, {name}! Вы подтверждены как сотрудник.",
    "menu": "Что сделать?",
    "btn_refer": "📝 Рекомендовать кандидата",
    "btn_language": "🌐 Язык / Language",
    "access_closed": "Доступ закрыт: вы не числитесь среди активных сотрудников.",
    "ask_first_name": "Имя кандидата:",
    "ask_last_name": "Фамилия кандидата:",
    "bad_name": "Можно только буквы (латиница или кириллица), пробел, дефис и апостроф, до 50 символов. Попробуйте ещё раз.",
    "ask_phone": "Телефон кандидата (например, +1 650 253 0000):",
    "bad_phone": "Не получилось распознать номер. Напишите его полностью; для номеров не из США — с кодом страны (+…).",
    "ask_email": "Почта кандидата:",
    "bad_email": "Это не похоже на адрес почты. Попробуйте ещё раз.",
    "already_referred": "Этого кандидата уже рекомендовали (заявка {number}). Анкета закрыта.",
    "ask_worked": "Кандидат раньше работал у нас?",
    "btn_yes": "Да",
    "btn_no": "Нет",
    "ask_photo": "Пришлите фото ворка (разрешения на работу). Подойдёт фото или картинка файлом до 20 МБ.",
    "bad_photo": "Нужна картинка: фото или файл-изображение до 20 МБ.",
    "confirm": "Проверьте анкету:\n\nИмя: {first_name}\nФамилия: {last_name}\nТелефон: {phone}\nПочта: {email}\nРаботал у нас: {worked}\nФото ворка: приложено\n\nВсё верно?",
    "btn_submit": "✅ Отправить",
    "btn_restart": "🔄 Начать заново",
    "btn_cancel": "✖️ Отмена",
    "btn_back": "⬅️ Назад",
    "submitted": "Спасибо! Заявка {number} принята.",
    "submit_failed_download": "Не удалось получить фото из Telegram. Нажмите «Отправить» ещё раз.",
    "stale_button": "Эта кнопка уже неактуальна.",
    "cancelled": "Анкета отменена.",
    "use_buttons": "Выберите вариант кнопкой.",
}
```

`referrals/i18n/en.py`:
```python
TEXTS = {
    "choose_language": "Выберите язык / Choose language",
    "ask_id": "To refer a candidate, please confirm you work at Istok.\n\nSend a photo of the QR code on your badge or paste your ID as text (EMP-…).",
    "qr_not_read": "Couldn't read the QR code. Tilt the badge to avoid glare and take the photo closer. You can also send the photo as a file (uncompressed) or paste the ID as text.",
    "not_an_id": "That doesn't look like an ID. Send a photo of your badge QR code or an ID like EMP-…",
    "send_photo_or_id": "Send a photo of your badge QR code or your ID as text.",
    "not_found": "We couldn't find you among active employees. Check the QR code or ID and try again.",
    "id_taken": "This ID is already linked to another Telegram account. The administrator has been notified.",
    "btn_ask_admin": "Not working — ask an admin",
    "ask_full_name_for_admin": "Type your first and last name as on the timesheet. An administrator will check and confirm.",
    "admin_request_sent": "Request sent to the administrator. While you wait, you can send the QR photo or ID again.",
    "admin_rejected": "The administrator did not confirm the request. Try sending the QR photo or ID again.",
    "welcome": "Hello, {name}! You are confirmed as an employee.",
    "menu": "What would you like to do?",
    "btn_refer": "📝 Refer a candidate",
    "btn_language": "🌐 Язык / Language",
    "access_closed": "Access closed: you are not listed as an active employee.",
    "ask_first_name": "Candidate's first name:",
    "ask_last_name": "Candidate's last name:",
    "bad_name": "Only letters (Latin or Cyrillic), spaces, hyphens and apostrophes, up to 50 characters. Please try again.",
    "ask_phone": "Candidate's phone (for example, +1 650 253 0000):",
    "bad_phone": "Couldn't recognise the number. Type it in full; for non-US numbers include the country code (+…).",
    "ask_email": "Candidate's email:",
    "bad_email": "That doesn't look like an email address. Please try again.",
    "already_referred": "This candidate has already been referred (application {number}). The form is closed.",
    "ask_worked": "Has the candidate worked with us before?",
    "btn_yes": "Yes",
    "btn_no": "No",
    "ask_photo": "Send a photo of the work permit. A photo or an image file up to 20 MB works.",
    "bad_photo": "Please send an image: a photo or an image file up to 20 MB.",
    "confirm": "Please check the form:\n\nFirst name: {first_name}\nLast name: {last_name}\nPhone: {phone}\nEmail: {email}\nWorked with us: {worked}\nWork permit photo: attached\n\nIs everything correct?",
    "btn_submit": "✅ Submit",
    "btn_restart": "🔄 Start over",
    "btn_cancel": "✖️ Cancel",
    "btn_back": "⬅️ Back",
    "submitted": "Thank you! Application {number} has been received.",
    "submit_failed_download": "Couldn't get the photo from Telegram. Please press “Submit” again.",
    "stale_button": "This button is no longer active.",
    "cancelled": "The form has been cancelled.",
    "use_buttons": "Please choose an option using the buttons.",
}
```

`referrals/i18n/__init__.py`:
```python
"""Тексты бота на русском и английском."""
from referrals.i18n import en, ru

LANGS = ("ru", "en")
_TEXTS = {"ru": ru.TEXTS, "en": en.TEXTS}


def t(lang: str | None, key: str, **kwargs) -> str:
    template = _TEXTS.get(lang or "ru", ru.TEXTS)[key]
    return template.format(**kwargs) if kwargs else template
```

- [ ] **Step 4: Тесты проходят**

Run: `.venv/bin/pytest tests/test_i18n.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add referrals/i18n tests/test_i18n.py
git commit -m "feat: тексты бота на русском и английском" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Диалог — каркас и анкета кандидата

**Files:**
- Create: `referrals/flow/__init__.py` (пустой), `referrals/flow/events.py`, `referrals/flow/io.py`, `referrals/flow/steps.py`, `referrals/flow/common.py`, `referrals/flow/referral.py`, `tests/test_flow_referral.py`
- Modify: `tests/fakes.py` (добавить `FakeIo`)

**Interfaces:**
- Consumes: `repo` (сессии, `find_referral_by_phone/email`, `create_referral`, `DuplicateCandidate`), `validation`, `t`, модели.
- Produces:
  - `flow.events`: `User(id: int, username: str | None = None, full_name: str = "")`, события `Text(text)`, `Photo(file_id, size=None)`, `Document(file_id, mime_type=None, size=None)`, `Button(data)`, `Command(name, args=())`, `Other()`; `Event` (union); `is_image_document(doc) -> bool`; `too_big(size) -> bool`.
  - `flow.io`: `Buttons = list[list[tuple[str, str]]]`; протокол `Io` с методами `reply(text, buttons=None)`, `download(file_id) -> bytes`, `send_admin(text, buttons=None) -> tuple[int, int]`, `edit_admin(ref, text)`, `send_user(tg_user_id, text, buttons=None)`, `answer_button(text=None)` (все async) и синхронный `kick_background()`.
  - `flow.steps`: `LANG, AUTH_WAIT_ID, AUTH_ADMIN_NAME, MENU, REF_FIRST_NAME, REF_LAST_NAME, REF_PHONE, REF_EMAIL, REF_WORKED, REF_PHOTO, REF_CONFIRM`, `AUTH_STEPS`, `FORM_STEPS`, `ADMIN_BUTTON_AFTER_FAILS = 3`, `MAX_FILE_BYTES = 20 * 1024 * 1024`.
  - `flow.common`: `LANGUAGE_BUTTONS`, `menu_buttons(lang)`, `nav_row(lang)`, `async show_menu(io, lang)`, `async prompt_language(io)`.
  - `flow.referral`: `async start_form(db, io, s)`, `async prompt(io, s)`, `async cancel_form(db, io, s)`, `async on_form(db, io, user, s, ref, event)`, `draft_complete(data) -> bool`.
  - `tests.fakes.FakeIo(files=None)`: списки `replies`, `admin_messages`, `admin_edits`, `user_messages`, `answered`; счётчик `kicks`; свойство `last_text`; методы `texts()`, `button_data(index=-1)`; `send_admin` возвращает `(-100, 101)`, `(-100, 102)`, …; `download` бросает `RuntimeError`, если `file_id` нет в `files`.

- [ ] **Step 1: FakeIo**

Добавить в `tests/fakes.py`:
```python
class FakeIo:
    """Имитация Telegram для логики диалога: всё, что бот «сказал», складывается в списки."""

    def __init__(self, files: dict[str, bytes] | None = None):
        self.files = dict(files or {})
        self.replies: list[tuple[str, list | None]] = []
        self.admin_messages: list[tuple[str, list | None]] = []
        self.admin_edits: list[tuple[tuple[int, int], str]] = []
        self.user_messages: list[tuple[int, str, list | None]] = []
        self.answered: list[str | None] = []
        self.kicks = 0
        self._next_message_id = 100

    async def reply(self, text, buttons=None):
        self.replies.append((text, buttons))

    async def download(self, file_id):
        if file_id not in self.files:
            raise RuntimeError(f"download failed: {file_id}")
        return self.files[file_id]

    async def send_admin(self, text, buttons=None):
        self.admin_messages.append((text, buttons))
        self._next_message_id += 1
        return (-100, self._next_message_id)

    async def edit_admin(self, ref, text):
        self.admin_edits.append((tuple(ref), text))

    async def send_user(self, tg_user_id, text, buttons=None):
        self.user_messages.append((tg_user_id, text, buttons))

    async def answer_button(self, text=None):
        self.answered.append(text)

    def kick_background(self):
        self.kicks += 1

    @property
    def last_text(self) -> str:
        return self.replies[-1][0]

    def texts(self) -> list[str]:
        return [text for text, _ in self.replies]

    def button_data(self, index: int = -1) -> list[str]:
        buttons = self.replies[index][1] or []
        return [data for row in buttons for _, data in row]
```

- [ ] **Step 2: Тесты анкеты (падают)**

`tests/test_flow_referral.py`:
```python
import copy
from uuid import uuid4

from referrals import repo
from referrals.flow import referral
from referrals.flow.events import Button, Document, Photo, Text, User
from referrals.flow.steps import MENU, REF_CONFIRM, REF_FIRST_NAME, REF_PHONE, REF_PHOTO
from referrals.i18n import t
from referrals.models import Session
from tests.factories import EMP_A, EMP_B, make_draft, make_photo
from tests.fakes import FakeIo
from tests.helpers import seed_employees, seed_referrer

USER = User(id=111, username="ivan", full_name="Ivan P")
FORM_INPUTS = [
    Text("Aziz"), Text("Karimov"), Text("(650) 253-0000"), Text("Aziz@Example.com"),
    Button("yn:yes"), Photo("photo-1", 90_000),
]
CONFIRM_BUTTONS = ["form:submit", "form:restart", "nav:cancel"]


async def verified(db):
    ref = await seed_referrer(db)
    s = Session(tg_user_id=111, step=MENU, language="ru")
    await repo.save_session(db, s)
    return s, ref


async def fill(db, io, s, ref, inputs=FORM_INPUTS):
    await referral.start_form(db, io, s)
    for event in inputs:
        await referral.on_form(db, io, USER, s, ref, event)


async def test_start_form_issues_key_and_prompts(db):
    s, ref = await verified(db)
    io = FakeIo()
    await referral.start_form(db, io, s)
    assert s.step == REF_FIRST_NAME and s.submission_key is not None
    assert io.last_text == t("ru", "ask_first_name")
    assert io.button_data() == ["nav:back", "nav:cancel"]
    assert (await repo.load_session(db, 111)).submission_key == s.submission_key


async def test_happy_path_creates_referral(db):
    s, ref = await verified(db)
    io = FakeIo(files={"photo-1": b"\xff\xd8work-permit"})
    await fill(db, io, s, ref)
    assert s.step == REF_CONFIRM
    assert io.last_text == t("ru", "confirm", first_name="Aziz", last_name="Karimov",
                             phone="+16502530000", email="aziz@example.com", worked="Да")
    assert io.button_data() == CONFIRM_BUTTONS
    await referral.on_form(db, io, USER, s, ref, Button("form:submit"))
    [created] = await repo.all_referrals(db)
    assert (created.first_name, created.phone, created.email, created.worked_before, created.referrer_emplid) == (
        "Aziz", "+16502530000", "aziz@example.com", True, EMP_A)
    assert (await repo.get_photo(db, created.id)).content == b"\xff\xd8work-permit"
    assert t("ru", "submitted", number="R-000001") in io.texts()
    assert io.last_text == t("ru", "menu") and io.kicks == 1
    stored = await repo.load_session(db, 111)
    assert (stored.step, stored.data, stored.submission_key) == (MENU, {}, None)


async def test_bad_name_is_rejected(db):
    s, ref = await verified(db)
    io = FakeIo()
    await referral.start_form(db, io, s)
    await referral.on_form(db, io, USER, s, ref, Text("Aziz2"))
    assert io.last_text == t("ru", "bad_name") and s.step == REF_FIRST_NAME


async def test_phone_already_referred_ends_form(db):
    s, ref = await verified(db)
    await repo.create_referral(db, make_draft(), make_photo(), Session(tg_user_id=111, step=MENU))
    io = FakeIo()
    await fill(db, io, s, ref, FORM_INPUTS[:3])
    assert t("ru", "already_referred", number="R-000001") in io.texts()
    assert s.step == MENU and io.last_text == t("ru", "menu")


async def test_email_already_referred_ends_form(db):
    s, ref = await verified(db)
    await repo.create_referral(db, make_draft(phone="+16502530001"), make_photo(), Session(tg_user_id=111, step=MENU))
    io = FakeIo()
    await fill(db, io, s, ref, FORM_INPUTS[:4])
    assert t("ru", "already_referred", number="R-000001") in io.texts()
    assert s.step == MENU


async def test_back_and_cancel(db):
    s, ref = await verified(db)
    io = FakeIo()
    await fill(db, io, s, ref, FORM_INPUTS[:1])
    await referral.on_form(db, io, USER, s, ref, Button("nav:back"))
    assert s.step == REF_FIRST_NAME and io.last_text == t("ru", "ask_first_name")
    await referral.on_form(db, io, USER, s, ref, Button("nav:back"))
    assert s.step == MENU and t("ru", "cancelled") in io.texts()
    await referral.start_form(db, io, s)
    await referral.on_form(db, io, USER, s, ref, Text("Aziz"))
    await referral.on_form(db, io, USER, s, ref, Button("nav:cancel"))
    stored = await repo.load_session(db, 111)
    assert (stored.step, stored.data, stored.submission_key) == (MENU, {}, None)


async def test_worked_step_requires_buttons(db):
    s, ref = await verified(db)
    io = FakeIo()
    await fill(db, io, s, ref, FORM_INPUTS[:4])
    await referral.on_form(db, io, USER, s, ref, Text("да"))
    assert io.replies[-2][0] == t("ru", "use_buttons")
    assert io.last_text == t("ru", "ask_worked")
    assert io.button_data() == ["yn:yes", "yn:no", "nav:back", "nav:cancel"]


async def test_photo_step_validation(db):
    s, ref = await verified(db)
    io = FakeIo()
    await fill(db, io, s, ref, FORM_INPUTS[:5])
    for bad in (Document("pdf", "application/pdf", 1000), Photo("big", 21 * 1024 * 1024), Text("вот")):
        await referral.on_form(db, io, USER, s, ref, bad)
        assert io.last_text == t("ru", "bad_photo") and s.step == REF_PHOTO
    await referral.on_form(db, io, USER, s, ref, Document("scan", "image/png", 5000))
    assert s.data["photo"] == {"file_id": "scan", "kind": "document", "mime": "image/png", "size": 5000}
    assert s.step == REF_CONFIRM


async def test_stale_button_keeps_step(db):
    s, ref = await verified(db)
    io = FakeIo()
    await fill(db, io, s, ref, FORM_INPUTS[:2])
    await referral.on_form(db, io, USER, s, ref, Button("yn:yes"))
    assert io.replies[-2][0] == t("ru", "stale_button")
    assert io.last_text == t("ru", "ask_phone")
    assert s.step == REF_PHONE and s.data == {"first_name": "Aziz", "last_name": "Karimov"}


async def test_second_photo_at_confirm_is_ignored(db):
    s, ref = await verified(db)
    io = FakeIo()
    await fill(db, io, s, ref)
    await referral.on_form(db, io, USER, s, ref, Photo("photo-2", 1000))
    assert s.step == REF_CONFIRM and s.data["photo"]["file_id"] == "photo-1"
    assert io.replies[-2][0] == t("ru", "use_buttons")
    assert io.button_data() == CONFIRM_BUTTONS


async def test_incomplete_draft_restarts_form(db):
    s, ref = await verified(db)
    s.step, s.data, s.submission_key = REF_CONFIRM, {"first_name": "Aziz"}, uuid4()
    await repo.save_session(db, s)
    io = FakeIo()
    await referral.on_form(db, io, USER, s, ref, Button("form:submit"))
    assert (s.step, s.data) == (REF_FIRST_NAME, {})
    assert io.last_text == t("ru", "ask_first_name")
    assert await repo.all_referrals(db) == []


async def test_photo_download_failure_keeps_draft(db):
    s, ref = await verified(db)
    io = FakeIo()
    await fill(db, io, s, ref)
    await referral.on_form(db, io, USER, s, ref, Button("form:submit"))
    assert t("ru", "submit_failed_download") in io.texts()
    assert io.button_data() == CONFIRM_BUTTONS
    assert await repo.all_referrals(db) == []
    assert (await repo.load_session(db, 111)).step == REF_CONFIRM


async def test_replayed_submit_does_not_duplicate(db):
    s, ref = await verified(db)
    io = FakeIo(files={"photo-1": b"x"})
    await fill(db, io, s, ref)
    replay = copy.deepcopy(s)
    await referral.on_form(db, io, USER, s, ref, Button("form:submit"))
    await referral.on_form(db, io, USER, replay, ref, Button("form:submit"))
    assert len(await repo.all_referrals(db)) == 1
    assert io.texts().count(t("ru", "submitted", number="R-000001")) == 2


async def test_candidate_referred_by_someone_else_meanwhile(db):
    s, ref = await verified(db)
    io = FakeIo(files={"photo-1": b"x"})
    await fill(db, io, s, ref)
    await seed_employees(db, (EMP_B, "Other Person"))
    await repo.bind_referrer(db, 222, EMP_B, None, "qr")
    other = make_draft(referrer_tg_user_id=222, referrer_emplid=EMP_B, referrer_name="Other Person")
    await repo.create_referral(db, other, make_photo(), Session(tg_user_id=222, step=MENU))
    await referral.on_form(db, io, USER, s, ref, Button("form:submit"))
    assert t("ru", "already_referred", number="R-000001") in io.texts()
    assert (await repo.load_session(db, 111)).step == MENU
    assert len(await repo.all_referrals(db)) == 1


async def test_english_prompts(db):
    s, ref = await verified(db)
    s.language = "en"
    io = FakeIo()
    await referral.start_form(db, io, s)
    assert io.last_text == t("en", "ask_first_name")
```

- [ ] **Step 3: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_flow_referral.py -q`
Expected: FAIL — `No module named 'referrals.flow'`.

- [ ] **Step 4: Каркас диалога**

`referrals/flow/__init__.py` — пустой файл.

`referrals/flow/steps.py`:
```python
"""Имена шагов диалога (хранятся в sessions.step) и общие константы."""
LANG = "lang"
AUTH_WAIT_ID = "auth_wait_id"
AUTH_ADMIN_NAME = "auth_admin_name"
MENU = "menu"
REF_FIRST_NAME = "ref_first_name"
REF_LAST_NAME = "ref_last_name"
REF_PHONE = "ref_phone"
REF_EMAIL = "ref_email"
REF_WORKED = "ref_worked"
REF_PHOTO = "ref_photo"
REF_CONFIRM = "ref_confirm"

AUTH_STEPS = frozenset({AUTH_WAIT_ID, AUTH_ADMIN_NAME})
FORM_STEPS = (REF_FIRST_NAME, REF_LAST_NAME, REF_PHONE, REF_EMAIL, REF_WORKED, REF_PHOTO, REF_CONFIRM)

ADMIN_BUTTON_AFTER_FAILS = 3
MAX_FILE_BYTES = 20 * 1024 * 1024
```

`referrals/flow/events.py`:
```python
"""Входящие события диалога, не зависящие от Telegram-библиотеки."""
from __future__ import annotations

from dataclasses import dataclass

from referrals.flow.steps import MAX_FILE_BYTES


@dataclass(frozen=True)
class User:
    id: int
    username: str | None = None
    full_name: str = ""


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Photo:
    file_id: str
    size: int | None = None


@dataclass(frozen=True)
class Document:
    file_id: str
    mime_type: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class Button:
    data: str


@dataclass(frozen=True)
class Command:
    name: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class Other:
    pass


Event = Text | Photo | Document | Button | Command | Other


def is_image_document(document: Document) -> bool:
    return (document.mime_type or "").startswith("image/")


def too_big(size: int | None) -> bool:
    return size is not None and size > MAX_FILE_BYTES
```

`referrals/flow/io.py`:
```python
"""Что логике диалога нужно от Telegram. Реализации: app.TelegramIo и tests.fakes.FakeIo."""
from __future__ import annotations

from typing import Protocol

Buttons = list[list[tuple[str, str]]]  # строки кнопок: (надпись, callback_data)


class Io(Protocol):
    async def reply(self, text: str, buttons: Buttons | None = None) -> None: ...

    async def download(self, file_id: str) -> bytes: ...

    async def send_admin(self, text: str, buttons: Buttons | None = None) -> tuple[int, int]: ...

    async def edit_admin(self, ref: tuple[int, int], text: str) -> None: ...

    async def send_user(self, tg_user_id: int, text: str, buttons: Buttons | None = None) -> None: ...

    async def answer_button(self, text: str | None = None) -> None: ...

    def kick_background(self) -> None: ...
```

`referrals/flow/common.py`:
```python
"""Общие элементы диалога: меню, выбор языка, навигация."""
from __future__ import annotations

from referrals.flow.io import Buttons, Io
from referrals.i18n import t

LANGUAGE_BUTTONS: Buttons = [[("Русский", "lang:ru"), ("English", "lang:en")]]


def menu_buttons(lang: str | None) -> Buttons:
    return [[(t(lang, "btn_refer"), "menu:refer")], [(t(lang, "btn_language"), "menu:language")]]


def nav_row(lang: str | None) -> list[tuple[str, str]]:
    return [(t(lang, "btn_back"), "nav:back"), (t(lang, "btn_cancel"), "nav:cancel")]


async def show_menu(io: Io, lang: str | None) -> None:
    await io.reply(t(lang, "menu"), menu_buttons(lang))


async def prompt_language(io: Io) -> None:
    await io.reply(t(None, "choose_language"), LANGUAGE_BUTTONS)
```

- [ ] **Step 5: Анкета**

`referrals/flow/referral.py`:
```python
"""Анкета кандидата: шаги, проверки, отправка."""
from __future__ import annotations

import logging
from uuid import uuid4

from referrals import repo
from referrals.db import Db
from referrals.flow.common import nav_row, show_menu
from referrals.flow.events import Button, Document, Event, Photo, Text, User, is_image_document, too_big
from referrals.flow.io import Io
from referrals.flow.steps import (
    FORM_STEPS, MENU, REF_CONFIRM, REF_EMAIL, REF_FIRST_NAME, REF_LAST_NAME, REF_PHONE, REF_PHOTO, REF_WORKED,
)
from referrals.i18n import t
from referrals.models import PhotoBlob, ReferralDraft, Referrer, Session, referral_number
from referrals.validation import clean_name, normalize_email, normalize_phone

log = logging.getLogger(__name__)

PROMPT_KEYS = {
    REF_FIRST_NAME: "ask_first_name",
    REF_LAST_NAME: "ask_last_name",
    REF_PHONE: "ask_phone",
    REF_EMAIL: "ask_email",
    REF_PHOTO: "ask_photo",
}
REQUIRED_KEYS = ("first_name", "last_name", "phone", "email", "worked_before", "photo")


def draft_complete(data: dict) -> bool:
    return all(key in data for key in REQUIRED_KEYS)


async def prompt(io: Io, s: Session) -> None:
    lang = s.language
    if s.step == REF_WORKED:
        await io.reply(t(lang, "ask_worked"),
                       [[(t(lang, "btn_yes"), "yn:yes"), (t(lang, "btn_no"), "yn:no")], nav_row(lang)])
    elif s.step == REF_CONFIRM:
        d = s.data
        worked = t(lang, "btn_yes") if d.get("worked_before") else t(lang, "btn_no")
        text = t(lang, "confirm", first_name=d.get("first_name", "—"), last_name=d.get("last_name", "—"),
                 phone=d.get("phone", "—"), email=d.get("email", "—"), worked=worked)
        await io.reply(text, [[(t(lang, "btn_submit"), "form:submit")],
                              [(t(lang, "btn_restart"), "form:restart")],
                              [(t(lang, "btn_cancel"), "nav:cancel")]])
    else:
        await io.reply(t(lang, PROMPT_KEYS[s.step]), [nav_row(lang)])


async def start_form(db: Db, io: Io, s: Session) -> None:
    s.step, s.data, s.submission_key = REF_FIRST_NAME, {}, uuid4()
    await repo.save_session(db, s)
    await prompt(io, s)


async def _end_form(db: Db, s: Session) -> None:
    s.step, s.data, s.submission_key = MENU, {}, None
    await repo.save_session(db, s)


async def cancel_form(db: Db, io: Io, s: Session) -> None:
    await _end_form(db, s)
    await io.reply(t(s.language, "cancelled"))
    await show_menu(io, s.language)


async def _already_referred(db: Db, io: Io, s: Session, referral_id: int) -> None:
    await _end_form(db, s)
    await io.reply(t(s.language, "already_referred", number=referral_number(referral_id)))
    await show_menu(io, s.language)


async def _advance(db: Db, io: Io, s: Session) -> None:
    s.step = FORM_STEPS[FORM_STEPS.index(s.step) + 1]
    await repo.save_session(db, s)
    await prompt(io, s)


async def _go_back(db: Db, io: Io, s: Session) -> None:
    index = FORM_STEPS.index(s.step)
    if index == 0:
        await cancel_form(db, io, s)
        return
    s.step = FORM_STEPS[index - 1]
    await repo.save_session(db, s)
    await prompt(io, s)


async def _remind(io: Io, s: Session, event: Event) -> None:
    if isinstance(event, Button):
        await io.reply(t(s.language, "stale_button"))
    elif s.step in (REF_WORKED, REF_CONFIRM):
        await io.reply(t(s.language, "use_buttons"))
    await prompt(io, s)


def _photo_from_event(event: Event) -> dict | None:
    if isinstance(event, Photo) and not too_big(event.size):
        return {"file_id": event.file_id, "kind": "photo", "mime": "image/jpeg", "size": event.size}
    if isinstance(event, Document) and is_image_document(event) and not too_big(event.size):
        return {"file_id": event.file_id, "kind": "document", "mime": event.mime_type, "size": event.size}
    return None


async def on_form(db: Db, io: Io, user: User, s: Session, ref: Referrer, event: Event) -> None:
    lang = s.language
    if isinstance(event, Button) and event.data == "nav:cancel":
        await cancel_form(db, io, s)
        return
    if isinstance(event, Button) and event.data == "nav:back":
        await _go_back(db, io, s)
        return
    if s.submission_key is None or (s.step == REF_CONFIRM and not draft_complete(s.data)):
        await start_form(db, io, s)
        return

    step = s.step
    if step in (REF_FIRST_NAME, REF_LAST_NAME):
        if not isinstance(event, Text):
            await _remind(io, s, event)
            return
        name = clean_name(event.text)
        if name is None:
            await io.reply(t(lang, "bad_name"))
            return
        s.data["first_name" if step == REF_FIRST_NAME else "last_name"] = name
        await _advance(db, io, s)
    elif step == REF_PHONE:
        if not isinstance(event, Text):
            await _remind(io, s, event)
            return
        phone = normalize_phone(event.text)
        if phone is None:
            await io.reply(t(lang, "bad_phone"))
            return
        existing = await repo.find_referral_by_phone(db, phone)
        if existing is not None:
            await _already_referred(db, io, s, existing)
            return
        s.data["phone"] = phone
        await _advance(db, io, s)
    elif step == REF_EMAIL:
        if not isinstance(event, Text):
            await _remind(io, s, event)
            return
        email = normalize_email(event.text)
        if email is None:
            await io.reply(t(lang, "bad_email"))
            return
        existing = await repo.find_referral_by_email(db, email)
        if existing is not None:
            await _already_referred(db, io, s, existing)
            return
        s.data["email"] = email
        await _advance(db, io, s)
    elif step == REF_WORKED:
        if isinstance(event, Button) and event.data in ("yn:yes", "yn:no"):
            s.data["worked_before"] = event.data == "yn:yes"
            await _advance(db, io, s)
        else:
            await _remind(io, s, event)
    elif step == REF_PHOTO:
        if isinstance(event, Button):
            await _remind(io, s, event)
            return
        photo = _photo_from_event(event)
        if photo is None:
            await io.reply(t(lang, "bad_photo"))
            return
        s.data["photo"] = photo
        await _advance(db, io, s)
    elif step == REF_CONFIRM:
        if isinstance(event, Button) and event.data == "form:submit":
            await _submit(db, io, user, s, ref)
        elif isinstance(event, Button) and event.data == "form:restart":
            await start_form(db, io, s)
        else:
            await _remind(io, s, event)


async def _submit(db: Db, io: Io, user: User, s: Session, ref: Referrer) -> None:
    lang, d = s.language, s.data
    try:
        content = await io.download(d["photo"]["file_id"])
        photo = PhotoBlob.from_bytes(content, d["photo"]["mime"] or "image/jpeg")
    except Exception:
        log.exception("не удалось скачать фото заявки tg=%s", user.id)
        await io.reply(t(lang, "submit_failed_download"))
        await prompt(io, s)
        return
    draft = ReferralDraft(
        submission_key=s.submission_key, first_name=d["first_name"], last_name=d["last_name"],
        phone=d["phone"], email=d["email"], worked_before=d["worked_before"],
        referrer_tg_user_id=user.id, referrer_emplid=ref.emplid, referrer_name=ref.name,
        photo_file_id=d["photo"]["file_id"], photo_kind=d["photo"]["kind"],
    )
    next_session = Session(tg_user_id=s.tg_user_id, step=MENU, language=lang)
    try:
        result = await repo.create_referral(db, draft, photo, next_session)
    except repo.DuplicateCandidate as dup:
        await _already_referred(db, io, s, dup.existing_id)
        return
    s.step, s.data, s.submission_key = MENU, {}, None
    await io.reply(t(lang, "submitted", number=result.number))
    await show_menu(io, lang)
    io.kick_background()
```

- [ ] **Step 6: Тесты проходят**

Run: `.venv/bin/pytest tests/test_flow_referral.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add referrals/flow tests/fakes.py tests/test_flow_referral.py
git commit -m "feat: анкета кандидата — шаги, проверки, атомарная отправка" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Диалог — проверка сотрудника и роутер

**Files:**
- Create: `referrals/flow/admin_texts.py`, `referrals/flow/auth.py`, `referrals/flow/router.py`, `tests/test_flow_auth.py`

**Interfaces:**
- Consumes: всё из Task 10, `decode_emp_id`, `extract_emp_id`, `repo.find_employee`, `repo.bind_referrer`, `repo.get_referrer`, `repo.search_active_employees_by_name`.
- Produces:
  - `flow.admin_texts`: `CARD_OBSOLETE: str`, `verify_request_text(user, typed_name, matches) -> str`, `verify_request_buttons(user_id, matches) -> Buttons` (кнопки `v:<tg_user_id>:<emplid>` для каждого совпадения и `x:<tg_user_id>`), `id_taken_text(user, employee) -> str`.
  - `flow.auth`: `async prompt_auth(io, s)`, `async on_language(db, io, s, ref, lang)`, `async on_wait_id(db, io, user, s, event)`, `async on_admin_name(db, io, user, s, event)`. В `s.data` хранятся `fails: int` и `admin_card: [chat_id, message_id]`.
  - `flow.router`: `async handle_event(db, io, user, event) -> None` — единственная точка входа для личных сообщений и кнопок.

- [ ] **Step 1: Тесты (падают)**

`tests/test_flow_auth.py`:
```python
from referrals import repo
from referrals.flow.admin_texts import CARD_OBSOLETE
from referrals.flow.events import Button, Command, Document, Other, Photo, Text, User
from referrals.flow.router import handle_event
from referrals.flow.steps import AUTH_WAIT_ID, MENU, REF_LAST_NAME
from referrals.i18n import t
from tests.factories import EMP_A, EMP_B
from tests.fakes import FakeIo
from tests.helpers import seed_employees
from tests.qr_images import blank_photo_jpeg, qr_photo_jpeg

USER = User(id=111, username="ivan", full_name="Ivan P")


async def start_ru(db, io, user=USER):
    await handle_event(db, io, user, Command("start"))
    await handle_event(db, io, user, Button("lang:ru"))


async def verify_method(db, tg_user_id: int) -> str:
    async with db.connection() as conn:
        cur = await conn.execute("SELECT verify_method FROM referrers WHERE tg_user_id = %s", (tg_user_id,))
        return (await cur.fetchone())["verify_method"]


async def test_new_user_gets_language_then_id_prompt(db):
    io = FakeIo()
    await handle_event(db, io, USER, Command("start"))
    assert io.last_text == t(None, "choose_language")
    assert io.button_data() == ["lang:ru", "lang:en"]
    await handle_event(db, io, USER, Text("привет"))
    assert io.last_text == t(None, "choose_language")
    await handle_event(db, io, USER, Button("lang:ru"))
    assert io.last_text == t("ru", "ask_id")
    assert (await repo.load_session(db, 111)).step == AUTH_WAIT_ID


async def test_text_id_verifies(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(f"мой id {EMP_A.upper()}"))
    assert t("ru", "welcome", name="Ivan Petrov") in io.texts()
    assert io.last_text == t("ru", "menu")
    assert (await repo.get_referrer(db, 111)).emplid == EMP_A
    assert await verify_method(db, 111) == "manual_id"


async def test_qr_photo_verifies(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo(files={"qr": qr_photo_jpeg(EMP_A)})
    await start_ru(db, io)
    await handle_event(db, io, USER, Photo("qr", 80_000))
    assert (await repo.get_referrer(db, 111)).emplid == EMP_A
    assert await verify_method(db, 111) == "qr"


async def test_admin_button_appears_after_third_failure(db):
    io = FakeIo(files={"blank": blank_photo_jpeg()})
    await start_ru(db, io)
    for attempt in range(3):
        await handle_event(db, io, USER, Photo("blank", 50_000))
        assert io.last_text == t("ru", "qr_not_read")
        assert io.button_data() == ([] if attempt < 2 else ["auth:admin"])
    assert (await repo.load_session(db, 111)).step == AUTH_WAIT_ID


async def test_not_an_id_text_does_not_count_as_failure(db):
    io = FakeIo()
    await start_ru(db, io)
    for _ in range(3):
        await handle_event(db, io, USER, Text("привет"))
    assert io.last_text == t("ru", "not_an_id")
    assert (await repo.load_session(db, 111)).data.get("fails", 0) == 0


async def test_unknown_and_inactive_ids_are_not_found(db):
    await seed_employees(db, (EMP_A, "A A"), (EMP_B, "B B"))
    await repo.deactivate_missing(db, [EMP_A])
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(EMP_B))
    assert io.last_text == t("ru", "not_found")
    await handle_event(db, io, USER, Text("EMP-00000000-0000-4000-8000-0000000000ff"))
    assert io.last_text == t("ru", "not_found")
    assert (await repo.load_session(db, 111)).data["fails"] == 2


async def test_id_bound_to_other_account_alerts_admin(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await repo.bind_referrer(db, 999, EMP_A, "other", "qr")
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(EMP_A))
    assert io.last_text == t("ru", "id_taken")
    assert "Ivan Petrov" in io.admin_messages[-1][0]
    assert await repo.get_referrer(db, 111) is None


async def test_oversized_document_not_downloaded(db):
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Document("huge", "image/jpeg", 25 * 1024 * 1024))
    assert io.last_text == t("ru", "qr_not_read")


async def test_sticker_and_non_image_file_get_reminder(db):
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Other())
    assert io.last_text == t("ru", "send_photo_or_id")
    await handle_event(db, io, USER, Document("doc", "application/pdf", 1000))
    assert io.last_text == t("ru", "send_photo_or_id")


async def test_admin_request_flow(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo(files={"blank": blank_photo_jpeg()})
    await start_ru(db, io)
    await handle_event(db, io, USER, Button("auth:admin"))
    assert io.last_text == t("ru", "stale_button")
    for _ in range(3):
        await handle_event(db, io, USER, Photo("blank", 50_000))
    await handle_event(db, io, USER, Button("auth:admin"))
    assert io.last_text == t("ru", "ask_full_name_for_admin")
    await handle_event(db, io, USER, Text("petrov   ivan"))
    card_text, card_buttons = io.admin_messages[-1]
    assert "petrov ivan" in card_text
    assert [data for row in card_buttons for _, data in row] == [f"v:111:{EMP_A}", "x:111"]
    assert io.last_text == t("ru", "admin_request_sent")
    session = await repo.load_session(db, 111)
    assert session.step == AUTH_WAIT_ID and session.data["admin_card"] == [-100, 101]
    await handle_event(db, io, USER, Text(EMP_A))
    assert io.admin_edits[-1] == ((-100, 101), CARD_OBSOLETE)
    assert (await repo.get_referrer(db, 111)).emplid == EMP_A


async def test_photo_while_typing_name_goes_to_qr_check(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo(files={"blank": blank_photo_jpeg(), "qr": qr_photo_jpeg(EMP_A)})
    await start_ru(db, io)
    for _ in range(3):
        await handle_event(db, io, USER, Photo("blank", 50_000))
    await handle_event(db, io, USER, Button("auth:admin"))
    await handle_event(db, io, USER, Photo("qr", 80_000))
    assert (await repo.get_referrer(db, 111)).emplid == EMP_A
    assert io.admin_messages == []


async def test_deactivated_referrer_gets_access_closed(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"), (EMP_B, "B B"))
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(EMP_A))
    await repo.deactivate_missing(db, [EMP_B])
    for event in (Text("hi"), Button("menu:refer"), Command("start")):
        await handle_event(db, io, USER, event)
        assert io.last_text == t("ru", "access_closed")


async def test_menu_and_language_switch(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(EMP_A))
    await handle_event(db, io, USER, Button("menu:language"))
    assert io.last_text == t(None, "choose_language")
    await handle_event(db, io, USER, Button("lang:en"))
    assert io.last_text == t("en", "menu")
    assert io.button_data() == ["menu:refer", "menu:language"]


async def test_start_mid_form_reprompts_and_cancel_returns_to_menu(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(EMP_A))
    await handle_event(db, io, USER, Button("menu:refer"))
    await handle_event(db, io, USER, Text("Aziz"))
    assert (await repo.load_session(db, 111)).step == REF_LAST_NAME
    await handle_event(db, io, USER, Command("start"))
    assert io.last_text == t("ru", "ask_last_name")
    await handle_event(db, io, USER, Command("cancel"))
    assert t("ru", "cancelled") in io.texts() and io.last_text == t("ru", "menu")
    assert (await repo.load_session(db, 111)).step == MENU


async def test_buttons_are_acknowledged(db):
    io = FakeIo()
    await start_ru(db, io)
    assert io.answered == [None]


async def test_unbound_user_in_menu_is_sent_back_to_auth(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    io = FakeIo()
    await start_ru(db, io)
    await handle_event(db, io, USER, Text(EMP_A))
    await repo.unbind_emplid(db, EMP_A)
    await handle_event(db, io, USER, Text("hi"))
    assert io.last_text == t("ru", "not_an_id")
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_flow_auth.py -q`
Expected: FAIL — `No module named 'referrals.flow.admin_texts'`.

- [ ] **Step 3: Тексты для чата HR**

`referrals/flow/admin_texts.py`:
```python
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
```

- [ ] **Step 4: Проверка сотрудника**

`referrals/flow/auth.py`:
```python
"""Выбор языка и проверка, что пользователь — сотрудник Istok."""
from __future__ import annotations

import asyncio

from referrals import repo
from referrals.db import Db
from referrals.flow import admin_texts
from referrals.flow.common import show_menu
from referrals.flow.events import Button, Document, Event, Photo, Text, User, is_image_document, too_big
from referrals.flow.io import Io
from referrals.flow.steps import ADMIN_BUTTON_AFTER_FAILS, AUTH_ADMIN_NAME, AUTH_WAIT_ID, MENU
from referrals.i18n import LANGS, t
from referrals.models import BindResult, Referrer, Session
from referrals.qr import decode_emp_id
from referrals.validation import extract_emp_id


async def prompt_auth(io: Io, s: Session) -> None:
    if s.step == AUTH_ADMIN_NAME:
        await io.reply(t(s.language, "ask_full_name_for_admin"), [[(t(s.language, "btn_cancel"), "nav:cancel")]])
    else:
        await io.reply(t(s.language, "ask_id"))


async def on_language(db: Db, io: Io, s: Session, ref: Referrer | None, lang: str) -> None:
    if lang not in LANGS:
        await io.reply(t(s.language, "stale_button"))
        return
    s.language = lang
    if ref is not None:
        s.step, s.data, s.submission_key = MENU, {}, None
        await repo.save_session(db, s)
        await show_menu(io, lang)
        return
    s.step = AUTH_WAIT_ID
    await repo.save_session(db, s)
    await prompt_auth(io, s)


def _admin_button_allowed(s: Session) -> bool:
    return s.data.get("fails", 0) >= ADMIN_BUTTON_AFTER_FAILS and not s.data.get("admin_card")


async def _fail(db: Db, io: Io, s: Session, key: str) -> None:
    s.data["fails"] = s.data.get("fails", 0) + 1
    await repo.save_session(db, s)
    buttons = [[(t(s.language, "btn_ask_admin"), "auth:admin")]] if _admin_button_allowed(s) else None
    await io.reply(t(s.language, key), buttons)


async def _verify(db: Db, io: Io, user: User, s: Session, emplid: str, method: str) -> None:
    employee = await repo.find_employee(db, emplid)
    if employee is None or not employee.active:
        await _fail(db, io, s, "not_found")
        return
    result = await repo.bind_referrer(db, user.id, employee.emplid, user.username, method)
    if result is BindResult.EMPLID_TAKEN:
        await io.send_admin(admin_texts.id_taken_text(user, employee))
        await _fail(db, io, s, "id_taken")
        return
    name = employee.name
    if result is BindResult.ALREADY:
        existing = await repo.get_referrer(db, user.id)
        name = existing.name if existing else name
    card = s.data.get("admin_card")
    if card:
        await io.edit_admin((card[0], card[1]), admin_texts.CARD_OBSOLETE)
    s.step, s.data, s.submission_key = MENU, {}, None
    await repo.save_session(db, s)
    await io.reply(t(s.language, "welcome", name=name))
    await show_menu(io, s.language)


async def on_wait_id(db: Db, io: Io, user: User, s: Session, event: Event) -> None:
    lang = s.language
    if isinstance(event, Photo) or (isinstance(event, Document) and is_image_document(event)):
        if too_big(event.size):
            await _fail(db, io, s, "qr_not_read")
            return
        data = await io.download(event.file_id)
        emplid = await asyncio.to_thread(decode_emp_id, data)
        if emplid is None:
            await _fail(db, io, s, "qr_not_read")
            return
        await _verify(db, io, user, s, emplid, "qr")
    elif isinstance(event, Text):
        emplid = extract_emp_id(event.text)
        if emplid is None:
            await io.reply(t(lang, "not_an_id"))
            return
        await _verify(db, io, user, s, emplid, "manual_id")
    elif isinstance(event, Button):
        if event.data == "auth:admin" and _admin_button_allowed(s):
            s.step = AUTH_ADMIN_NAME
            await repo.save_session(db, s)
            await prompt_auth(io, s)
        else:
            await io.reply(t(lang, "stale_button"))
    else:
        await io.reply(t(lang, "send_photo_or_id"))


async def on_admin_name(db: Db, io: Io, user: User, s: Session, event: Event) -> None:
    if isinstance(event, Button) and event.data == "nav:cancel":
        s.step = AUTH_WAIT_ID
        await repo.save_session(db, s)
        await prompt_auth(io, s)
        return
    if isinstance(event, (Photo, Document)) or (isinstance(event, Text) and extract_emp_id(event.text)):
        s.step = AUTH_WAIT_ID
        await on_wait_id(db, io, user, s, event)
        return
    if not isinstance(event, Text):
        await prompt_auth(io, s)
        return
    typed = " ".join(event.text.split())
    if not typed or len(typed) > 100:
        await prompt_auth(io, s)
        return
    matches = await repo.search_active_employees_by_name(db, typed)
    card = await io.send_admin(
        admin_texts.verify_request_text(user, typed, matches),
        admin_texts.verify_request_buttons(user.id, matches),
    )
    s.data["admin_card"] = [card[0], card[1]]
    s.step = AUTH_WAIT_ID
    await repo.save_session(db, s)
    await io.reply(t(s.language, "admin_request_sent"))
```

- [ ] **Step 5: Роутер**

`referrals/flow/router.py`:
```python
"""Точка входа диалога: загружает состояние и передаёт событие нужному шагу."""
from __future__ import annotations

from referrals import repo
from referrals.db import Db
from referrals.flow import auth, referral
from referrals.flow.common import prompt_language, show_menu
from referrals.flow.events import Button, Command, Event, User
from referrals.flow.io import Io
from referrals.flow.steps import AUTH_ADMIN_NAME, AUTH_STEPS, AUTH_WAIT_ID, FORM_STEPS, LANG, MENU
from referrals.i18n import t
from referrals.models import Referrer, Session


async def handle_event(db: Db, io: Io, user: User, event: Event) -> None:
    s = await repo.load_session(db, user.id) or Session(tg_user_id=user.id, step=LANG)
    ref = await repo.get_referrer(db, user.id)
    if isinstance(event, Button):
        await io.answer_button()
    if ref is not None and not ref.active:
        await io.reply(t(s.language, "access_closed"))
        return
    if isinstance(event, Command):
        if event.name == "cancel":
            await _on_cancel(db, io, s, ref)
        else:
            await _on_start(db, io, s, ref)
        return
    if isinstance(event, Button) and event.data.startswith("lang:"):
        await auth.on_language(db, io, s, ref, event.data.removeprefix("lang:"))
        return
    if s.step == LANG:
        await prompt_language(io)
        return
    # Шаг должен соответствовать факту привязки (её могли снять /unbind или выдать админом).
    if ref is None and s.step not in AUTH_STEPS:
        s.step = AUTH_WAIT_ID
    if ref is not None and s.step in AUTH_STEPS:
        s.step = MENU

    if s.step == AUTH_WAIT_ID:
        await auth.on_wait_id(db, io, user, s, event)
    elif s.step == AUTH_ADMIN_NAME:
        await auth.on_admin_name(db, io, user, s, event)
    elif s.step == MENU:
        await _on_menu(db, io, s, event)
    elif s.step in FORM_STEPS:
        await referral.on_form(db, io, user, s, ref, event)
    else:
        s.step, s.data, s.submission_key = MENU, {}, None
        await repo.save_session(db, s)
        await show_menu(io, s.language)


async def _on_start(db: Db, io: Io, s: Session, ref: Referrer | None) -> None:
    if s.language is None:
        s.step = LANG
        await repo.save_session(db, s)
        await prompt_language(io)
        return
    if ref is None:
        if s.step not in AUTH_STEPS:
            s.step = AUTH_WAIT_ID
            await repo.save_session(db, s)
        await auth.prompt_auth(io, s)
        return
    if s.step in FORM_STEPS:
        await referral.prompt(io, s)
        return
    s.step, s.data, s.submission_key = MENU, {}, None
    await repo.save_session(db, s)
    await show_menu(io, s.language)


async def _on_cancel(db: Db, io: Io, s: Session, ref: Referrer | None) -> None:
    if s.language is None:
        await _on_start(db, io, s, ref)
        return
    if ref is None:
        s.step = AUTH_WAIT_ID
        await repo.save_session(db, s)
        await auth.prompt_auth(io, s)
        return
    await referral.cancel_form(db, io, s)


async def _on_menu(db: Db, io: Io, s: Session, event: Event) -> None:
    if isinstance(event, Button):
        if event.data == "menu:refer":
            await referral.start_form(db, io, s)
            return
        if event.data == "menu:language":
            s.step = LANG
            await repo.save_session(db, s)
            await prompt_language(io)
            return
        await io.reply(t(s.language, "stale_button"))
    await show_menu(io, s.language)
```

- [ ] **Step 6: Тесты проходят**

Run: `.venv/bin/pytest tests/test_flow_auth.py tests/test_flow_referral.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add referrals/flow tests/test_flow_auth.py
git commit -m "feat: проверка сотрудника по QR/ID и роутер диалога" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Админ — подтверждение сотрудника, /unbind, подпись заявки

**Files:**
- Create: `referrals/flow/admin.py`, `tests/test_flow_admin.py`
- Modify: `referrals/flow/admin_texts.py` (добавить `referral_caption`)

**Interfaces:**
- Consumes: `repo`, `menu_buttons`, `t`, `extract_emp_id`, шаги.
- Produces: `flow.admin.on_admin_button(db, io, admin_id: int, admin_ids: frozenset[int], data: str, card: tuple[int, int])`, `flow.admin.on_unbind(db, io, admin_id, admin_ids, args: tuple[str, ...])`, `flow.admin_texts.referral_caption(referral) -> str`.

- [ ] **Step 1: Тесты (падают)**

`tests/test_flow_admin.py`:
```python
from referrals import repo
from referrals.flow.admin import on_admin_button, on_unbind
from referrals.flow.admin_texts import referral_caption
from referrals.flow.steps import AUTH_WAIT_ID, MENU
from referrals.i18n import t
from referrals.models import Session
from tests.factories import EMP_A, EMP_B, make_referral
from tests.fakes import FakeIo
from tests.helpers import seed_employees

ADMINS = frozenset({7})
CARD = (-100, 555)


async def waiting_user(db, tg_user_id=111, language="en"):
    await repo.save_session(db, Session(tg_user_id=tg_user_id, step=AUTH_WAIT_ID, language=language,
                                        data={"fails": 3, "admin_card": [-100, 555]}))


async def test_non_admin_cannot_approve(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await waiting_user(db)
    io = FakeIo()
    await on_admin_button(db, io, 8, ADMINS, f"v:111:{EMP_A}", CARD)
    assert io.answered == ["Нет прав"]
    assert await repo.get_referrer(db, 111) is None


async def test_approve_binds_and_notifies_user(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await waiting_user(db)
    io = FakeIo()
    await on_admin_button(db, io, 7, ADMINS, f"v:111:{EMP_A}", CARD)
    assert (await repo.get_referrer(db, 111)).emplid == EMP_A
    assert [(tg, text) for tg, text, _ in io.user_messages] == [
        (111, t("en", "welcome", name="Ivan Petrov")), (111, t("en", "menu"))]
    assert io.admin_edits == [(CARD, f"✅ Подтверждено: Ivan Petrov ({EMP_A})")]
    session = await repo.load_session(db, 111)
    assert (session.step, session.data) == (MENU, {})


async def test_approve_when_already_verified(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await repo.bind_referrer(db, 111, EMP_A, None, "qr")
    io = FakeIo()
    await on_admin_button(db, io, 7, ADMINS, f"v:111:{EMP_A}", CARD)
    assert io.admin_edits == [(CARD, "Неактуально: сотрудник уже подтверждён.")]
    assert io.user_messages == []


async def test_approve_when_emplid_taken(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await repo.bind_referrer(db, 999, EMP_A, None, "qr")
    await waiting_user(db)
    io = FakeIo()
    await on_admin_button(db, io, 7, ADMINS, f"v:111:{EMP_A}", CARD)
    assert "уже привязан" in io.admin_edits[-1][1]
    assert await repo.get_referrer(db, 111) is None


async def test_reject_notifies_user_and_clears_card(db):
    await waiting_user(db)
    io = FakeIo()
    await on_admin_button(db, io, 7, ADMINS, "x:111", CARD)
    assert io.user_messages[-1][:2] == (111, t("en", "admin_rejected"))
    assert io.admin_edits == [(CARD, "❌ Отклонено")]
    assert "admin_card" not in (await repo.load_session(db, 111)).data


async def test_unbind(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await repo.bind_referrer(db, 111, EMP_A, None, "qr")
    await repo.save_session(db, Session(tg_user_id=111, step=MENU, language="ru"))
    io = FakeIo()
    await on_unbind(db, io, 8, ADMINS, (EMP_A,))
    assert io.replies == [] and await repo.get_referrer(db, 111) is not None
    await on_unbind(db, io, 7, ADMINS, ())
    assert io.last_text == "Формат: /unbind EMP-…"
    await on_unbind(db, io, 7, ADMINS, (EMP_B,))
    assert io.last_text == f"Привязки для {EMP_B} нет."
    await on_unbind(db, io, 7, ADMINS, (EMP_A,))
    assert io.last_text == f"Привязка снята: {EMP_A} (Telegram id 111)."
    assert await repo.get_referrer(db, 111) is None
    assert (await repo.load_session(db, 111)).step == AUTH_WAIT_ID


def test_referral_caption():
    caption = referral_caption(make_referral(7, worked_before=False))
    assert caption.splitlines() == [
        "🆕 Заявка R-000007",
        "Кандидат: Aziz Karimov",
        "Телефон: +16502530000",
        "Почта: aziz@example.com",
        "Работал у нас: Нет",
        f"Рекомендовал: Ivan Petrov ({EMP_A})",
    ]
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_flow_admin.py -q`
Expected: FAIL — `No module named 'referrals.flow.admin'`.

- [ ] **Step 3: Реализация**

Добавить в `referrals/flow/admin_texts.py` импорт `from referrals.models import Employee, Referral` (заменив прежний импорт `Employee`) и функцию:
```python
def referral_caption(referral: Referral) -> str:
    return "\n".join([
        f"🆕 Заявка {referral.number}",
        f"Кандидат: {referral.first_name} {referral.last_name}",
        f"Телефон: {referral.phone}",
        f"Почта: {referral.email}",
        f"Работал у нас: {'Да' if referral.worked_before else 'Нет'}",
        f"Рекомендовал: {referral.referrer_name} ({referral.referrer_emplid})",
    ])
```

`referrals/flow/admin.py`:
```python
"""Действия администраторов: подтверждение сотрудника из чата HR и /unbind."""
from __future__ import annotations

from referrals import repo
from referrals.db import Db
from referrals.flow.common import menu_buttons
from referrals.flow.io import Io
from referrals.flow.steps import AUTH_WAIT_ID, MENU
from referrals.i18n import t
from referrals.models import BindResult, Session
from referrals.validation import extract_emp_id

ALREADY_VERIFIED = "Неактуально: сотрудник уже подтверждён."


async def on_admin_button(db: Db, io: Io, admin_id: int, admin_ids: frozenset[int], data: str,
                          card: tuple[int, int]) -> None:
    if admin_id not in admin_ids:
        await io.answer_button("Нет прав")
        return
    await io.answer_button()
    kind, _, rest = data.partition(":")
    if kind == "v":
        tg_text, _, emplid = rest.partition(":")
        await _approve(db, io, int(tg_text), emplid, card)
    elif kind == "x":
        await _reject(db, io, int(rest), card)


async def _approve(db: Db, io: Io, tg_user_id: int, emplid: str, card: tuple[int, int]) -> None:
    if await repo.get_referrer(db, tg_user_id) is not None:
        await io.edit_admin(card, ALREADY_VERIFIED)
        return
    employee = await repo.find_employee(db, emplid)
    if employee is None or not employee.active:
        await io.edit_admin(card, f"Не подтверждено: {emplid} нет среди активных сотрудников.")
        return
    result = await repo.bind_referrer(db, tg_user_id, employee.emplid, None, "admin")
    if result is BindResult.EMPLID_TAKEN:
        await io.edit_admin(card, f"Не подтверждено: {employee.name} уже привязан к другому Telegram-аккаунту.")
        return
    s = await repo.load_session(db, tg_user_id) or Session(tg_user_id=tg_user_id, step=MENU)
    s.step, s.data, s.submission_key = MENU, {}, None
    await repo.save_session(db, s)
    await io.send_user(tg_user_id, t(s.language, "welcome", name=employee.name))
    await io.send_user(tg_user_id, t(s.language, "menu"), menu_buttons(s.language))
    await io.edit_admin(card, f"✅ Подтверждено: {employee.name} ({employee.emplid})")


async def _reject(db: Db, io: Io, tg_user_id: int, card: tuple[int, int]) -> None:
    if await repo.get_referrer(db, tg_user_id) is not None:
        await io.edit_admin(card, ALREADY_VERIFIED)
        return
    s = await repo.load_session(db, tg_user_id)
    if s is not None:
        s.data.pop("admin_card", None)
        await repo.save_session(db, s)
    await io.send_user(tg_user_id, t(s.language if s else None, "admin_rejected"))
    await io.edit_admin(card, "❌ Отклонено")


async def on_unbind(db: Db, io: Io, admin_id: int, admin_ids: frozenset[int], args: tuple[str, ...]) -> None:
    if admin_id not in admin_ids:
        return
    emplid = extract_emp_id(" ".join(args))
    if emplid is None:
        await io.reply("Формат: /unbind EMP-…")
        return
    tg_user_id = await repo.unbind_emplid(db, emplid)
    if tg_user_id is None:
        await io.reply(f"Привязки для {emplid} нет.")
        return
    s = await repo.load_session(db, tg_user_id)
    if s is not None:
        s.step, s.data, s.submission_key = AUTH_WAIT_ID, {}, None
        await repo.save_session(db, s)
    await io.reply(f"Привязка снята: {emplid} (Telegram id {tg_user_id}).")
```

- [ ] **Step 4: Тесты проходят**

Run: `.venv/bin/pytest tests/test_flow_admin.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add referrals/flow/admin.py referrals/flow/admin_texts.py tests/test_flow_admin.py
git commit -m "feat: подтверждение сотрудника админом, /unbind, подпись заявки для HR" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Алерты и фоновые задачи

**Files:**
- Create: `referrals/alerts.py`, `referrals/jobs.py`, `tests/test_alerts.py`, `tests/test_jobs.py`

**Interfaces:**
- Consumes: `fetch_employees`, `sync_employees`, `sync_sheet`, `SheetSyncReport`, `SheetLayoutError`, `advisory_lock`, `SHEET_LOCK_KEY`, `repo`.
- Produces:
  - `alerts.Alerter(send: Callable[[str], Awaitable[object]], *, min_interval=3600.0, clock=time.monotonic)` с `async alert(kind, text) -> bool` (текст отправляется с префиксом `"⚠️ "`; не чаще `min_interval` на `kind`; ошибка отправки глотается и возвращает `False`); `alerts.FailureTracker(threshold=3)` с `record(name, ok) -> bool` (True, когда подряд неудач ≥ threshold) и полем `threshold`.
  - `jobs.Notifier` (протокол): `async send_referral(referral)`, `async reupload(referral, photo) -> str` (новый file_id).
  - `jobs.run_employee_sync(db, http, tabeli_url, alerter) -> EmployeeSyncResult`; `jobs.run_sheet_sync(db, open_ws: Callable[[], object], alerter, *, full: bool) -> SheetSyncReport | None` (None — блокировка занята); `jobs.run_notify(db, notifier) -> int`; `jobs.run_reupload(db, notifier, *, older_than=timedelta(hours=24), limit=20) -> int`.

- [ ] **Step 1: Тесты алертов (падают)**

`tests/test_alerts.py`:
```python
from referrals.alerts import Alerter, FailureTracker


def collector(bucket):
    async def send(text):
        bucket.append(text)
    return send


async def test_alerter_rate_limits_per_kind():
    sent, now = [], [0.0]
    alerter = Alerter(collector(sent), min_interval=3600, clock=lambda: now[0])
    assert await alerter.alert("a", "one") is True
    assert await alerter.alert("a", "two") is False
    assert await alerter.alert("b", "three") is True
    now[0] = 3601
    assert await alerter.alert("a", "four") is True
    assert sent == ["⚠️ one", "⚠️ three", "⚠️ four"]


async def test_alerter_swallows_send_errors_and_retries_later():
    calls = []

    async def flaky(text):
        calls.append(text)
        if len(calls) == 1:
            raise RuntimeError("telegram down")

    alerter = Alerter(flaky)
    assert await alerter.alert("a", "x") is False
    assert await alerter.alert("a", "x") is True


def test_failure_tracker():
    tracker = FailureTracker(threshold=3)
    assert [tracker.record("job", ok=False) for _ in range(4)] == [False, False, True, True]
    assert tracker.record("job", ok=True) is False
    assert tracker.record("job", ok=False) is False
```

- [ ] **Step 2: Тесты задач (падают)**

`tests/test_jobs.py`:
```python
import httpx
import pytest

from referrals import jobs, repo
from referrals.alerts import Alerter
from referrals.db import SHEET_LOCK_KEY, advisory_lock
from referrals.models import Session
from referrals.sheet_model import BOT_HEADERS, PHOTO_HEADER, SheetLayoutError
from tests.factories import EMP_A, EMP_B, EMP_C, make_draft, make_photo
from tests.fakes import FakeSheet
from tests.helpers import seed_employees, seed_referrer

HEADER = [*BOT_HEADERS, PHOTO_HEADER]


def collecting_alerter():
    sent = []

    async def send(text):
        sent.append(text)

    return Alerter(send), sent


async def create_referral(db, i=0):
    if await repo.get_referrer(db, 111) is None:
        await seed_referrer(db)
    draft = make_draft(phone=f"+1650253000{i}", email=f"c{i}@example.com")
    return await repo.create_referral(db, draft, make_photo(), Session(tg_user_id=111, step="menu"))


class FakeNotifier:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.sent = []
        self.reuploaded = []

    async def send_referral(self, referral):
        if referral.id == self.fail_on:
            raise RuntimeError("telegram down")
        self.sent.append(referral.id)

    async def reupload(self, referral, photo):
        self.reuploaded.append((referral.id, photo.sha256))
        return f"new-{referral.id}"


async def test_employee_sync_alerts_when_list_shrinks(db):
    await seed_employees(db, (EMP_A, "A A"), (EMP_B, "B B"), (EMP_C, "C C"))
    payload = {"employees": [{"id": EMP_A, "qr_data": EMP_A, "name": "A A"}]}
    alerter, sent = collecting_alerter()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as http:
        result = await jobs.run_employee_sync(db, http, "http://tabeli", alerter)
    assert result.skipped_deactivation
    assert len(sent) == 1 and "tabeli" in sent[0]


async def test_push_skips_when_locked_and_writes_pending(db):
    await create_referral(db)
    sheet = FakeSheet([HEADER])
    alerter, sent = collecting_alerter()
    async with advisory_lock(db, SHEET_LOCK_KEY):
        assert await jobs.run_sheet_sync(db, lambda: sheet, alerter, full=False) is None
    report = await jobs.run_sheet_sync(db, lambda: sheet, alerter, full=False)
    assert report.appended == 1

    def must_not_open():
        raise AssertionError("лист не должен открываться, если нечего писать")

    assert (await jobs.run_sheet_sync(db, must_not_open, alerter, full=False)).appended == 0
    assert sent == []


async def test_reconcile_alerts_about_unknown_rows(db):
    await create_referral(db)
    sheet = FakeSheet([HEADER, ["R-000777"]])
    alerter, sent = collecting_alerter()
    report = await jobs.run_sheet_sync(db, lambda: sheet, alerter, full=True)
    assert report.unknown_numbers == ["R-000777"]
    assert len(sent) == 1 and "R-000777" in sent[0]


async def test_push_does_not_alert_about_other_rows(db):
    await create_referral(db)
    sheet = FakeSheet([HEADER, ["R-000777"]])
    alerter, sent = collecting_alerter()
    await jobs.run_sheet_sync(db, lambda: sheet, alerter, full=False)
    assert sent == []


async def test_layout_error_alerts_and_raises(db):
    await create_referral(db)
    alerter, sent = collecting_alerter()
    with pytest.raises(SheetLayoutError):
        await jobs.run_sheet_sync(db, lambda: FakeSheet([["№"]]), alerter, full=True)
    assert any("Запись в таблицу остановлена" in m for m in sent)


async def test_notify_marks_sent_and_stops_on_failure(db):
    a = await create_referral(db, 0)
    b = await create_referral(db, 1)
    notifier = FakeNotifier(fail_on=b.id)
    with pytest.raises(RuntimeError):
        await jobs.run_notify(db, notifier)
    assert notifier.sent == [a.id]
    assert [r.id for r in await repo.referrals_pending_notify(db)] == [b.id]
    assert await jobs.run_notify(db, FakeNotifier()) == 1


async def test_reupload_replaces_file_id(db):
    created = await create_referral(db)
    async with db.connection() as conn:
        await conn.execute("UPDATE referrals SET created_at = now() - interval '2 days'")
    notifier = FakeNotifier()
    assert await jobs.run_reupload(db, notifier) == 1
    assert notifier.reuploaded == [(created.id, make_photo().sha256)]
    assert (await repo.all_referrals(db))[0].photo_file_id == f"new-{created.id}"
```

- [ ] **Step 3: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_alerts.py tests/test_jobs.py -q`
Expected: FAIL — `No module named 'referrals.alerts'`.

- [ ] **Step 4: Реализация**

`referrals/alerts.py`:
```python
"""Алерты в чат HR с ограничением частоты и счётчик подряд идущих сбоев."""
from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)


class Alerter:
    def __init__(self, send: Callable[[str], Awaitable[object]], *, min_interval: float = 3600.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._send = send
        self._min_interval = min_interval
        self._clock = clock
        self._last_sent: dict[str, float] = {}

    async def alert(self, kind: str, text: str) -> bool:
        now = self._clock()
        last = self._last_sent.get(kind)
        if last is not None and now - last < self._min_interval:
            return False
        try:
            await self._send(f"⚠️ {text}")
        except Exception:
            log.exception("не удалось отправить алерт %s", kind)
            return False
        self._last_sent[kind] = now
        return True


class FailureTracker:
    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self._consecutive: dict[str, int] = {}

    def record(self, name: str, ok: bool) -> bool:
        if ok:
            self._consecutive[name] = 0
            return False
        self._consecutive[name] = self._consecutive.get(name, 0) + 1
        return self._consecutive[name] >= self.threshold
```

`referrals/jobs.py`:
```python
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
            report = await sync_sheet(db, ws, referrals)
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
```

- [ ] **Step 5: Тесты проходят**

Run: `.venv/bin/pytest tests/test_alerts.py tests/test_jobs.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add referrals/alerts.py referrals/jobs.py tests/test_alerts.py tests/test_jobs.py
git commit -m "feat: фоновые задачи (tabeli, таблица, уведомления, перезаливка фото) и алерты" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Telegram-адаптер, расписание задач, точка входа

**Files:**
- Create: `referrals/app.py`, `referrals/__main__.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: `handle_event`, `admin.on_admin_button`, `admin.on_unbind`, `admin_texts.referral_caption`, `jobs.*`, `Alerter`, `FailureTracker`, `Db`, `migrate`, `open_worksheet`, `load_config`.
- Produces: `to_user(update) -> User`, `to_event(update) -> Event`, `to_markup(buttons) -> InlineKeyboardMarkup | None`, `TelegramIo`, `TelegramNotifier`, `Deps`, `build_application(cfg) -> Application`, `main()`.

- [ ] **Step 1: Тесты (падают)**

`tests/test_app.py`:
```python
from telegram import Bot, InlineKeyboardMarkup, Update

from referrals.app import build_application, to_event, to_markup, to_user
from referrals.config import Config
from referrals.flow.events import Button, Command, Document, Other, Photo, Text, User

BOT = Bot("123456:TEST_TOKEN")
FROM = {"id": 111, "is_bot": False, "first_name": "Ivan", "last_name": "P", "username": "ivan"}
MSG = {"message_id": 1, "date": 0, "chat": {"id": 111, "type": "private"}, "from": FROM}
CFG = Config(
    telegram_bot_token="123456:TEST_TOKEN", database_url="postgresql://x", tabeli_url="http://t",
    google_credentials={}, spreadsheet_id="s", sheet_name="Заявки", admin_chat_id=-100,
    admin_user_ids=frozenset({7}),
)


def update_from(payload: dict) -> Update:
    return Update.de_json({"update_id": 1, **payload}, BOT)


def test_photo_uses_largest_size_and_user_is_mapped():
    update = update_from({"message": {**MSG, "photo": [
        {"file_id": "small", "file_unique_id": "s", "width": 90, "height": 90, "file_size": 1000},
        {"file_id": "big", "file_unique_id": "b", "width": 1280, "height": 960, "file_size": 90000},
    ]}})
    assert to_event(update) == Photo("big", 90000)
    assert to_user(update) == User(111, "ivan", "Ivan P")


def test_document():
    update = update_from({"message": {**MSG, "document": {
        "file_id": "d", "file_unique_id": "du", "mime_type": "image/png", "file_size": 5000}}})
    assert to_event(update) == Document("d", "image/png", 5000)


def test_text_and_commands():
    assert to_event(update_from({"message": {**MSG, "text": "Aziz"}})) == Text("Aziz")
    assert to_event(update_from({"message": {**MSG, "text": "/start@istok_referrals_bot"}})) == Command("start")
    assert to_event(update_from({"message": {**MSG, "text": "/cancel now"}})) == Command("cancel", ("now",))


def test_callback_query():
    update = update_from({"callback_query": {"id": "q", "from": FROM, "chat_instance": "ci",
                                             "data": "yn:yes", "message": MSG}})
    assert to_event(update) == Button("yn:yes")


def test_sticker_is_other():
    update = update_from({"message": {**MSG, "sticker": {
        "file_id": "st", "file_unique_id": "stu", "width": 512, "height": 512,
        "is_animated": False, "is_video": False, "type": "regular"}}})
    assert to_event(update) == Other()


def test_to_markup():
    assert to_markup(None) is None
    markup = to_markup([[("Да", "yn:yes"), ("Нет", "yn:no")]])
    assert isinstance(markup, InlineKeyboardMarkup)
    assert [(b.text, b.callback_data) for b in markup.inline_keyboard[0]] == [("Да", "yn:yes"), ("Нет", "yn:no")]


def test_build_application_registers_handlers():
    app = build_application(CFG)
    assert app.job_queue is not None
    assert len(app.handlers[0]) == 5
    assert app.error_handlers
    assert app.bot_data["cfg"] is CFG
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_app.py -q`
Expected: FAIL — `No module named 'referrals.app'`.

- [ ] **Step 3: Реализация адаптера**

`referrals/app.py`:
```python
"""Обвязка python-telegram-bot: перевод апдейтов в события, отправка сообщений, расписание задач."""
from __future__ import annotations

import logging
import mimetypes
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from referrals import jobs
from referrals.alerts import Alerter, FailureTracker
from referrals.config import Config, load_config
from referrals.db import Db, migrate
from referrals.flow import admin as admin_flow
from referrals.flow.admin_texts import referral_caption
from referrals.flow.events import Button, Command, Document, Event, Other, Photo, Text, User
from referrals.flow.io import Buttons
from referrals.flow.router import handle_event
from referrals.models import PhotoBlob, Referral
from referrals.sheets import open_worksheet

log = logging.getLogger("referrals")

SOMETHING_WRONG = "Что-то пошло не так. Попробуйте ещё раз. / Something went wrong, please try again."


# ─── перевод апдейтов ──────────────────────────────────────────

def to_user(update: Update) -> User:
    user = update.effective_user
    return User(id=user.id, username=user.username, full_name=user.full_name)


def to_event(update: Update) -> Event:
    if update.callback_query is not None:
        return Button(update.callback_query.data or "")
    message = update.message
    if message is None:
        return Other()
    if message.photo:
        largest = message.photo[-1]
        return Photo(largest.file_id, largest.file_size)
    if message.document:
        doc = message.document
        return Document(doc.file_id, doc.mime_type, doc.file_size)
    if message.text:
        if message.text.startswith("/"):
            parts = message.text[1:].split()
            name = parts[0].split("@")[0].lower() if parts else ""
            return Command(name, tuple(parts[1:]))
        return Text(message.text)
    return Other()


def to_markup(buttons: Buttons | None) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in buttons]
    )


# ─── зависимости и реализации Io/Notifier ──────────────────────

@dataclass
class Deps:
    cfg: Config
    db: Db
    http: httpx.AsyncClient
    alerter: Alerter
    failures: FailureTracker


def _deps(context: ContextTypes.DEFAULT_TYPE) -> Deps:
    return context.application.bot_data["deps"]


class TelegramIo:
    def __init__(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, query=None) -> None:
        self._context = context
        self._bot = context.bot
        self._chat_id = chat_id
        self._query = query

    async def reply(self, text: str, buttons: Buttons | None = None) -> None:
        await self._bot.send_message(self._chat_id, text, reply_markup=to_markup(buttons))

    async def download(self, file_id: str) -> bytes:
        file = await self._bot.get_file(file_id)
        return bytes(await file.download_as_bytearray())

    async def send_admin(self, text: str, buttons: Buttons | None = None) -> tuple[int, int]:
        message = await self._bot.send_message(_deps(self._context).cfg.admin_chat_id, text,
                                                reply_markup=to_markup(buttons))
        return message.chat_id, message.message_id

    async def edit_admin(self, ref: tuple[int, int], text: str) -> None:
        try:
            await self._bot.edit_message_text(text, chat_id=ref[0], message_id=ref[1])
        except BadRequest as exc:
            log.warning("не удалось изменить сообщение %s: %s", ref, exc)

    async def send_user(self, tg_user_id: int, text: str, buttons: Buttons | None = None) -> None:
        await self._bot.send_message(tg_user_id, text, reply_markup=to_markup(buttons))

    async def answer_button(self, text: str | None = None) -> None:
        if self._query is None:
            return
        await self._query.answer(text)
        try:
            await self._query.edit_message_reply_markup(None)
        except BadRequest:
            pass

    def kick_background(self) -> None:
        self._context.application.job_queue.run_once(job_push, 1)
        self._context.application.job_queue.run_once(job_notify, 2)


class TelegramNotifier:
    def __init__(self, bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def send_referral(self, referral: Referral) -> None:
        caption = referral_caption(referral)
        if referral.photo_kind == "photo":
            await self._bot.send_photo(self._chat_id, referral.photo_file_id, caption=caption)
        else:
            await self._bot.send_document(self._chat_id, referral.photo_file_id, caption=caption)

    async def reupload(self, referral: Referral, photo: PhotoBlob) -> str:
        caption = f"♻️ Перезаливка фото {referral.number}: на Диске его нет больше суток."
        if referral.photo_kind == "photo":
            message = await self._bot.send_photo(self._chat_id, photo.content, caption=caption)
            return message.photo[-1].file_id
        extension = mimetypes.guess_extension(photo.mime_type) or ".jpg"
        message = await self._bot.send_document(self._chat_id, photo.content, caption=caption,
                                                filename=f"{referral.number}{extension}")
        return message.document.file_id


# ─── обработчики ───────────────────────────────────────────────

async def on_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    io = TelegramIo(context, update.effective_chat.id, update.callback_query)
    await handle_event(_deps(context).db, io, to_user(update), to_event(update))


async def on_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    deps = _deps(context)
    io = TelegramIo(context, query.message.chat_id, query)
    await admin_flow.on_admin_button(deps.db, io, query.from_user.id, deps.cfg.admin_user_ids, query.data,
                                     (query.message.chat_id, query.message.message_id))


async def on_unbind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    deps = _deps(context)
    io = TelegramIo(context, update.effective_chat.id)
    await admin_flow.on_unbind(deps.db, io, update.effective_user.id, deps.cfg.admin_user_ids,
                               tuple(context.args or ()))


async def on_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in _deps(context).cfg.admin_user_ids:
        return
    for job in (job_employees, job_push, job_reconcile):
        context.job_queue.run_once(job, 0)
    await update.effective_message.reply_text("Синхронизация запущена.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("ошибка обработки апдейта", exc_info=context.error)
    deps = context.application.bot_data.get("deps")
    if deps is not None:
        await deps.alerter.alert("handler_error", f"Ошибка обработки сообщения: {context.error!r}")
    if isinstance(update, Update) and update.effective_chat and update.effective_chat.type == "private":
        try:
            await context.bot.send_message(update.effective_chat.id, SOMETHING_WRONG)
        except Exception:
            log.exception("не удалось сообщить пользователю об ошибке")


# ─── фоновые задачи ────────────────────────────────────────────

async def _run_job(context: ContextTypes.DEFAULT_TYPE, name: str,
                   work: Callable[[Deps, ContextTypes.DEFAULT_TYPE], Awaitable[object]]) -> None:
    deps = _deps(context)
    try:
        await work(deps, context)
    except Exception as exc:
        log.exception("задача %s упала", name)
        if deps.failures.record(name, ok=False):
            await deps.alerter.alert(f"job:{name}",
                                     f"Задача {name} падает {deps.failures.threshold}+ раз подряд: {exc!r}")
    else:
        deps.failures.record(name, ok=True)


def _open_ws(deps: Deps) -> Callable[[], object]:
    cfg = deps.cfg
    return lambda: open_worksheet(cfg.google_credentials, cfg.spreadsheet_id, cfg.sheet_name)


async def job_employees(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_job(context, "employees",
                   lambda d, c: jobs.run_employee_sync(d.db, d.http, d.cfg.tabeli_url, d.alerter))


async def job_push(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_job(context, "sheet_push",
                   lambda d, c: jobs.run_sheet_sync(d.db, _open_ws(d), d.alerter, full=False))


async def job_reconcile(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_job(context, "sheet_reconcile",
                   lambda d, c: jobs.run_sheet_sync(d.db, _open_ws(d), d.alerter, full=True))


async def job_notify(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_job(context, "notify_hr",
                   lambda d, c: jobs.run_notify(d.db, TelegramNotifier(c.bot, d.cfg.admin_chat_id)))


async def job_reupload(context: ContextTypes.DEFAULT_TYPE) -> None:
    async def work(d: Deps, c: ContextTypes.DEFAULT_TYPE) -> None:
        if await jobs.run_reupload(d.db, TelegramNotifier(c.bot, d.cfg.admin_chat_id)):
            c.job_queue.run_once(job_reconcile, 5)

    await _run_job(context, "reupload_photos", work)


# ─── жизненный цикл ────────────────────────────────────────────

async def post_init(app: Application) -> None:
    cfg: Config = app.bot_data["cfg"]
    applied = await migrate(cfg.database_url)
    if applied:
        log.info("применены миграции: %s", ", ".join(applied))
    db = await Db.connect(cfg.database_url)
    alerter = Alerter(lambda text: app.bot.send_message(cfg.admin_chat_id, text))
    app.bot_data["deps"] = Deps(cfg, db, httpx.AsyncClient(), alerter, FailureTracker())

    queue = app.job_queue
    queue.run_repeating(job_employees, interval=15 * 60, first=1)
    queue.run_repeating(job_push, interval=60, first=20)
    queue.run_repeating(job_notify, interval=60, first=30)
    queue.run_repeating(job_reconcile, interval=15 * 60, first=60)
    queue.run_repeating(job_reupload, interval=24 * 3600, first=10 * 60)
    await app.bot.set_my_commands([BotCommand("start", "Начать / меню"), BotCommand("cancel", "Отменить анкету")])


async def post_shutdown(app: Application) -> None:
    deps: Deps | None = app.bot_data.get("deps")
    if deps is not None:
        await deps.http.aclose()
        await deps.db.close()


def build_application(cfg: Config) -> Application:
    app = (ApplicationBuilder().token(cfg.telegram_bot_token)
           .post_init(post_init).post_shutdown(post_shutdown).build())
    app.bot_data["cfg"] = cfg
    app.add_handler(CommandHandler("unbind", on_unbind))
    app.add_handler(CommandHandler("sync", on_sync))
    app.add_handler(CallbackQueryHandler(on_admin_callback, pattern=r"^[vx]:"))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE, on_private))
    app.add_handler(CallbackQueryHandler(on_private))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = build_application(load_config())
    app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)
```

`referrals/__main__.py`:
```python
from referrals.app import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Тесты проходят**

Run: `.venv/bin/pytest tests/test_app.py -q`
Expected: PASS. Если `Update.de_json` в установленной версии PTB требует другой формат поля `date`, передать целое число секунд — как в тесте — и проверить сообщение об ошибке.

- [ ] **Step 5: Весь набор тестов**

Run: `.venv/bin/pytest -q`
Expected: PASS, 0 failed.

- [ ] **Step 6: Проверка импорта точки входа без переменных окружения**

Run: `.venv/bin/python -m referrals; echo "exit=$?"`
Expected: `ConfigError: не задана переменная окружения ...` и ненулевой код — значит, модуль запускается и падает только на конфигурации.

- [ ] **Step 7: Commit**

```bash
git add referrals/app.py referrals/__main__.py tests/test_app.py
git commit -m "feat: Telegram-адаптер, расписание задач и точка входа" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: GAS-скрипт фото, документация по развёртыванию, публикация

**Files:**
- Create: `gas/photos.gs`, `docs/DEPLOY.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: заголовки таблицы из раздела 4 спецификации; Script Properties `BOT_TOKEN`, `FOLDER_ID`.
- Produces: функции GAS `uploadPhotos()` (по триггеру) и `installTrigger()` (один раз вручную).

- [ ] **Step 1: GAS-скрипт**

`gas/photos.gs`:
```javascript
/**
 * Istok Referrals — загрузка фото ворка из Telegram на Google Диск.
 *
 * Работает от аккаунта владельца таблицы. Раз в 5 минут ищет строки листа «Заявки»,
 * где заполнен file_id, а «Фото» пусто, скачивает файл через Telegram Bot API,
 * кладёт в папку FOLDER_ID и пишет ссылку в «Фото». Бот эту колонку не трогает.
 *
 * Настройка: Script Properties → BOT_TOKEN, FOLDER_ID; один раз запустить installTrigger().
 */
var SHEET_NAME = 'Заявки';
var MAX_ROWS_PER_RUN = 30;

function uploadPhotos() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) return;  // предыдущий запуск ещё идёт
  try {
    var props = PropertiesService.getScriptProperties();
    var token = props.getProperty('BOT_TOKEN');
    var folder = DriveApp.getFolderById(props.getProperty('FOLDER_ID'));
    var sheet = SpreadsheetApp.getActive().getSheetByName(SHEET_NAME);
    var values = sheet.getDataRange().getValues();
    var head = values[0].map(function (h) { return String(h).trim(); });
    var col = {
      id: head.indexOf('№'),
      first: head.indexOf('Имя'),
      last: head.indexOf('Фамилия'),
      fileId: head.indexOf('file_id'),
      photo: head.indexOf('Фото')
    };
    if (col.id < 0 || col.fileId < 0 || col.photo < 0) {
      throw new Error('В листе «' + SHEET_NAME + '» нет заголовков №, file_id или Фото');
    }

    var processed = 0;
    for (var r = 1; r < values.length && processed < MAX_ROWS_PER_RUN; r++) {
      var row = values[r];
      var number = String(row[col.id]).trim();
      var fileId = String(row[col.fileId]).trim();
      if (!number || !fileId || String(row[col.photo]).trim()) continue;
      var cell = sheet.getRange(r + 1, col.photo + 1);
      try {
        var baseName = number + ' ' + String(row[col.first]).trim() + ' ' + String(row[col.last]).trim();
        cell.setValue(uploadOne_(token, folder, fileId, number, baseName));
        cell.setNote('');
      } catch (e) {
        cell.setNote('Ошибка загрузки ' + new Date().toISOString() + ': ' + e.message);
      }
      processed++;
    }
  } finally {
    lock.releaseLock();
  }
}

function uploadOne_(token, folder, fileId, number, baseName) {
  // Файл уже загружен прошлым запуском, который упал до записи ссылки, — не создаём дубль.
  var existing = folder.searchFiles('title contains "' + number + ' "');
  if (existing.hasNext()) return existing.next().getUrl();

  var info = JSON.parse(UrlFetchApp.fetch(
    'https://api.telegram.org/bot' + token + '/getFile?file_id=' + encodeURIComponent(fileId),
    { muteHttpExceptions: true }
  ).getContentText());
  if (!info.ok) throw new Error(info.description || 'getFile не удался');

  var path = info.result.file_path;
  var dot = path.lastIndexOf('.');
  var name = baseName + (dot >= 0 ? path.substring(dot) : '.jpg');
  var response = UrlFetchApp.fetch('https://api.telegram.org/file/bot' + token + '/' + path,
                                   { muteHttpExceptions: true });
  if (response.getResponseCode() !== 200) {
    throw new Error('скачивание файла: HTTP ' + response.getResponseCode());
  }
  return folder.createFile(response.getBlob().setName(name)).getUrl();
}

function installTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'uploadPhotos') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('uploadPhotos').timeBased().everyMinutes(5).create();
}
```

- [ ] **Step 2: Инструкция по развёртыванию**

`docs/DEPLOY.md`:
````markdown
# Развёртывание Istok Referrals

## 1. Telegram

1. В @BotFather создать бота `Istok Referrals` → токен в `TELEGRAM_BOT_TOKEN`. Для проверок создать второго, тестового бота.
2. Создать группу HR, добавить туда бота. ID группы (вида `-100…`) → `ADMIN_CHAT_ID`.
3. Telegram ID администраторов через запятую → `ADMIN_USER_IDS`.

## 2. Google

1. На Диске создать папку `Istok Referrals`, внутри — Google-таблицу `Заявки` с листом `Заявки` и подпапку `Фото ворка` (ID подпапки — из её адреса).
2. Первая строка листа — ровно эти заголовки:
   `№ | Дата | Имя | Фамилия | Телефон | Почта | Работал у нас | Рекомендатель | Emplid рекомендателя | file_id | Фото | Статус | Заметки`
   Колонки после `Фото` — для HR, их можно добавлять и переименовывать.
3. Скрыть колонку `file_id`. Защитить колонки `№`…`file_id`: Данные → Защищённые диапазоны → «Только показывать предупреждение».
4. Открыть доступ «Редактор» сервисному аккаунту (можно тот же, что у бота водителей). Его JSON → `GOOGLE_CREDENTIALS`, ID таблицы → `SPREADSHEET_ID`.
5. Расширения → Apps Script → вставить `gas/photos.gs`. Настройки проекта → Script Properties: `BOT_TOKEN` (токен бота), `FOLDER_ID` (ID папки `Фото ворка`). Запустить `installTrigger` один раз и выдать разрешения.

## 3. Railway

1. New Project → Deploy from GitHub → `LDrahrep/istok_referrals`.
2. В проекте: New → Database → PostgreSQL. В его настройках Backups включить ежедневный бэкап.
3. В сервисе бота — переменные:
   `TELEGRAM_BOT_TOKEN`, `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `TABELI_URL=http://<IP tabeli>`, `GOOGLE_CREDENTIALS`, `SPREADSHEET_ID`, `ADMIN_CHAT_ID`, `ADMIN_USER_IDS`, при необходимости `SHEET_NAME`.
4. Деплой. В логах должно быть `применены миграции: 001_init`, затем без ошибок задач.

## 4. Проверить при запуске (раздел 14 спецификации)

- [ ] Бэкапы Postgres на тарифе Railway включились. Если нет — завести задачу на ежедневную выгрузку `referrals` в чат HR.
- [ ] При деплое два экземпляра не конфликтуют надолго: в логах нет повторяющихся `Conflict: terminated by other getUpdates request` дольше минуты.
- [ ] tabeli доступен с Railway: через минуту после старта в таблице `employees` ~950 строк (`/sync` в чате HR запускает синхронизацию сразу).

## 5. Ручная проверка на тестовом боте

1. `/start` → язык → фото QR с бейджа → «Здравствуйте, <имя>».
2. Три нечитаемых фото → появляется кнопка «попросить админа» → имя → карточка в чате HR → «Это …» → в личке приходит меню.
3. Анкета целиком → «Заявка R-… принята» → в чате HR сообщение с фото → через минуту строка в таблице → через ≤5 минут ссылка в «Фото».
4. Порча таблицы: удалить строку заявки, затереть телефон, отсортировать одну колонку бота (защита должна предупредить) → через ≤15 минут (или `/sync`) бот восстановил данные.
5. Повторная рекомендация того же телефона → «Этого кандидата уже рекомендовали».
6. `/unbind EMP-…` в чате HR → пользователь снова проходит проверку.

## Локальная разработка

```bash
/opt/homebrew/bin/python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
docker run -d --name referrals-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16-alpine
.venv/bin/pytest -q
```

Запуск с тестовым ботом: положить переменные в `.env` (он в `.gitignore`), затем
`set -a; source .env; set +a; .venv/bin/python -m referrals`.
````

- [ ] **Step 3: README**

Заменить строку статуса в `README.md` на `Статус: MVP реализован, см. [docs/DEPLOY.md](docs/DEPLOY.md).` и добавить в список документов:
```markdown
- [docs/superpowers/plans/2026-09-25-istok-referrals.md](docs/superpowers/plans/2026-09-25-istok-referrals.md) — план реализации
- [docs/DEPLOY.md](docs/DEPLOY.md) — развёртывание и ручная проверка
```

- [ ] **Step 4: Полный прогон**

Run: `.venv/bin/pytest -q`
Expected: PASS, 0 failed.

- [ ] **Step 5: Commit и push**

```bash
git add gas/photos.gs docs/DEPLOY.md README.md
git commit -m "docs: GAS-скрипт загрузки фото и инструкция по развёртыванию" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push -u origin main
```
Expected: ветка `main` в `https://github.com/LDrahrep/istok_referrals`.
