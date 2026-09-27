# «Мои рекомендации» и отзыв заявки — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сотрудник видит в боте свои заявки и может отозвать заявку, пока HR не заполнил «Статус»; отзыв ничего не удаляет и освобождает телефон и почту кандидата.

**Architecture:** Миграция 002 добавляет `referrals.withdrawn_at` и переносит уникальность телефона/почты на неотозванные заявки. Новый модуль диалога `referrals/flow/mine.py` работает на шаге MENU через кнопки `menu:mine` / `my:*` без новых шагов сессии. Проверка «Статуса» идёт через протокол `SheetReader` (живое чтение таблицы) с откатом на копию в базе. В таблице появляется колонка бота «Отозвана», которую бот при отсутствии дописывает сам.

**Tech Stack:** как в основном проекте (Python 3.14, python-telegram-bot 22.8, psycopg 3, gspread 6.2, pytest).

**Spec:** `docs/superpowers/specs/2026-09-25-istok-referrals-design.md`, раздел 16 (и правки в разделах 1, 3, 4).

## Global Constraints

- Всё из Global Constraints основного плана `docs/superpowers/plans/2026-09-25-istok-referrals.md` остаётся в силе.
- Заголовок новой колонки бота — ровно `Отозвана`; колонка HR, по которой запрещается отзыв, — ровно `Статус`.
- Статус HR сотруднику не показывается ни в каком виде; отказ в отзыве — только текст «Эту заявку отозвать нельзя, напишите HR».
- Список — не больше 20 заявок, новые сверху, отбор по `referrer_emplid`.
- Никаких `DELETE` заявок и строк таблицы.

## Review Focus

- Старая кнопка `my:*` нажата посреди анкеты → «кнопка неактуальна» + повтор вопроса, черновик цел. Тест: Task 3 `test_my_button_mid_form_is_stale`.
- Подделанная кнопка на чужую или несуществующую заявку → «неактуальна», ничего не отзывается. Тест: Task 3 `test_foreign_and_garbage_buttons_are_stale`.
- Таблица недоступна в момент отзыва → решение по копии `hr_data` в базе. Тест: Task 3 `test_withdraw_falls_back_to_db_copy_when_sheet_down`.
- В таблице ещё нет колонки «Отозвана» (как у текущей живой таблицы) → бот дописывает заголовок, расширяя лист. Тест: Task 2 `test_missing_withdrawn_header_is_added`.
- Миграция на базе, где уже есть заявки. Тест: Task 1 `test_migration_002_on_existing_data`.

---

### Task 1: Миграция 002, модель и репозиторий

**Files:**
- Create: `referrals/migrations/002_withdrawal.sql`, `tests/test_repo_withdrawal.py`
- Modify: `referrals/models.py`, `referrals/repo.py`

**Interfaces:**
- Produces: `Referral.withdrawn_at: datetime | None = None` (последнее поле); `models.WithdrawResult` (`WITHDRAWN`, `ALREADY`, `NOT_FOUND`); `repo.list_referrals_by_referrer(db, emplid, limit=20) -> list[Referral]` (новые сверху); `repo.get_referral(db, referral_id) -> Referral | None`; `repo.withdraw_referral(db, referral_id, emplid) -> WithdrawResult` (ставит `withdrawn_at = now()` и `sheet_synced_at = NULL`); `find_referral_by_phone/email` ищут только среди неотозванных; `stale_photo_referrals` пропускает отозванные.

- [ ] **Step 1: Тесты (падают)**

`tests/test_repo_withdrawal.py`:
```python
from datetime import timedelta

import psycopg
import pytest

from referrals import repo
from referrals.db import migrate, migration_files
from referrals.models import Session, WithdrawResult
from tests.factories import EMP_A, EMP_B, make_draft, make_photo
from tests.helpers import seed_referrer


def menu_session(tg_user_id: int = 111) -> Session:
    return Session(tg_user_id=tg_user_id, step="menu", language="ru")


async def test_withdraw_releases_phone_and_email(db):
    await seed_referrer(db)
    first = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    assert await repo.withdraw_referral(db, first.id, EMP_A) is WithdrawResult.WITHDRAWN
    assert await repo.find_referral_by_phone(db, "+16502530000") is None
    assert await repo.find_referral_by_email(db, "aziz@example.com") is None
    second = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    assert second.created and second.id != first.id
    with pytest.raises(repo.DuplicateCandidate) as err:
        await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    assert err.value.existing_id == second.id


async def test_withdraw_outcomes(db):
    await seed_referrer(db)
    await seed_referrer(db, tg_user_id=222, emplid=EMP_B, name="Other Person")
    created = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    assert await repo.withdraw_referral(db, created.id, EMP_B) is WithdrawResult.NOT_FOUND
    assert await repo.withdraw_referral(db, 999, EMP_A) is WithdrawResult.NOT_FOUND
    assert await repo.withdraw_referral(db, created.id, EMP_A) is WithdrawResult.WITHDRAWN
    assert await repo.withdraw_referral(db, created.id, EMP_A) is WithdrawResult.ALREADY


async def test_withdraw_marks_referral_for_sheet_sync(db):
    await seed_referrer(db)
    created = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    await repo.mark_sheet_synced(db, [created.id])
    await repo.withdraw_referral(db, created.id, EMP_A)
    [pending] = await repo.referrals_pending_sheet(db)
    assert pending.id == created.id and pending.withdrawn_at is not None


async def test_list_and_get(db):
    await seed_referrer(db)
    await seed_referrer(db, tg_user_id=222, emplid=EMP_B, name="Other Person")
    a = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    other = make_draft(phone="+16502530001", email="o@example.com", referrer_tg_user_id=222,
                       referrer_emplid=EMP_B, referrer_name="Other Person")
    await repo.create_referral(db, other, make_photo(), menu_session(222))
    c = await repo.create_referral(db, make_draft(phone="+16502530002", email="c@example.com"), make_photo(), menu_session())
    assert [r.id for r in await repo.list_referrals_by_referrer(db, EMP_A)] == [c.id, a.id]
    assert [r.id for r in await repo.list_referrals_by_referrer(db, EMP_A, limit=1)] == [c.id]
    assert (await repo.get_referral(db, a.id)).phone == "+16502530000"
    assert await repo.get_referral(db, 999) is None


async def test_stale_photos_skip_withdrawn(db):
    await seed_referrer(db)
    created = await repo.create_referral(db, make_draft(), make_photo(), menu_session())
    async with db.connection() as conn:
        await conn.execute("UPDATE referrals SET created_at = now() - interval '2 days'")
    await repo.withdraw_referral(db, created.id, EMP_A)
    assert await repo.stale_photo_referrals(db, timedelta(hours=24)) == []


async def test_migration_002_on_existing_data(migrated_url):
    base, _ = migrated_url.rsplit("/", 1)
    with psycopg.connect(migrated_url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS mig_002_test")
        admin.execute("CREATE DATABASE mig_002_test")
    url = f"{base}/mig_002_test"
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("CREATE TABLE schema_migrations (version text PRIMARY KEY, "
                         "applied_at timestamptz NOT NULL DEFAULT now())")
            conn.execute(dict(migration_files())["001_init"])
            conn.execute("INSERT INTO schema_migrations (version) VALUES ('001_init')")
            conn.execute("INSERT INTO employees (emplid, qr_data, name) VALUES (%s, %s, 'A')", (EMP_A, EMP_A))
            conn.execute(
                "INSERT INTO referrals (submission_key, first_name, last_name, phone, email, worked_before, "
                "referrer_tg_user_id, referrer_emplid, referrer_name, photo_file_id, photo_kind) "
                "VALUES (gen_random_uuid(), 'A', 'B', '+16502530000', 'a@b.co', false, 1, %s, 'R', 'f', 'photo')",
                (EMP_A,))
        assert await migrate(url) == ["002_withdrawal"]
        with psycopg.connect(url) as conn:
            assert conn.execute("SELECT withdrawn_at FROM referrals").fetchone() == (None,)
    finally:
        with psycopg.connect(migrated_url, autocommit=True) as admin:
            admin.execute("DROP DATABASE IF EXISTS mig_002_test")
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/bin/pytest tests/test_repo_withdrawal.py -q`
Expected: FAIL — `cannot import name 'WithdrawResult'`.

- [ ] **Step 3: Миграция**

`referrals/migrations/002_withdrawal.sql`:
```sql
-- Отзыв заявки сотрудником: заявка остаётся, телефон и почта освобождаются.
ALTER TABLE referrals ADD COLUMN withdrawn_at timestamptz;
ALTER TABLE referrals DROP CONSTRAINT referrals_phone_key;
ALTER TABLE referrals DROP CONSTRAINT referrals_email_key;
CREATE UNIQUE INDEX referrals_phone_active ON referrals (phone) WHERE withdrawn_at IS NULL;
CREATE UNIQUE INDEX referrals_email_active ON referrals (email) WHERE withdrawn_at IS NULL;
```

- [ ] **Step 4: Модель**

В `referrals/models.py`: в конец `Referral` добавить поле `withdrawn_at: datetime | None = None`; после `BindResult` добавить:
```python
class WithdrawResult(enum.Enum):
    WITHDRAWN = "withdrawn"
    ALREADY = "already"
    NOT_FOUND = "not_found"
```

- [ ] **Step 5: Репозиторий**

В `referrals/repo.py`:
- добавить `WithdrawResult` в импорт моделей;
- в `_REFERRAL_SELECT` после `created_at` добавить `, withdrawn_at`;
- `_find_id`: запрос `f"SELECT id FROM referrals WHERE {column} = %s AND withdrawn_at IS NULL"`;
- `stale_photo_referrals`: условие `WHERE photo_url IS NULL AND withdrawn_at IS NULL AND created_at < now() - %s ...`;
- добавить в конец:
```python
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
```

- [ ] **Step 6: Тесты проходят, весь набор зелёный**

Run: `.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add referrals/migrations/002_withdrawal.sql referrals/models.py referrals/repo.py tests/test_repo_withdrawal.py
git commit -m "feat: отзыв заявки в базе — withdrawn_at, уникальность только среди неотозванных" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Колонка «Отозвана» в таблице и чтение «Статуса»

**Files:**
- Modify: `referrals/sheet_model.py`, `referrals/sheets.py`, `tests/fakes.py`, `tests/test_sheet_model.py`, `tests/test_sheets.py`, `docs/DEPLOY.md`

**Interfaces:**
- Consumes: `Referral.withdrawn_at`, `repo.withdraw_referral`.
- Produces: `sheet_model.WITHDRAWN_HEADER = "Отозвана"` (последний в `BOT_HEADERS`), `sheet_model.HR_STATUS_HEADER = "Статус"`, `sheet_model.hr_status_from_values(values, number) -> str | None` (None — нет колонки `Статус`, нет `№` или строки); `sheets.LiveHrStatus(open_ws)` с `async hr_status(number) -> str | None`; `sync_sheet` дописывает недостающий заголовок `Отозвана`. `FakeSheet(rows, row_count=1000, col_count=26)` с `add_cols(n)`.

- [ ] **Step 1: Правка существующих тестов под новую колонку (падают)**

В `tests/test_sheet_model.py`:
- импортировать `WITHDRAWN_HEADER, hr_status_from_values`;
- `test_parse_layout_standard`: `layout.columns[PHOTO_HEADER] == 11`, `hr_columns == {"Статус": 12, "Заметки": 13}`, `layout.width == 14`;
- `test_parse_layout_any_order_and_spaces`: `layout.columns["№"] == 12`;
- `test_plan_handles_blank_and_short_rows`: ожидание `set(range(3, BOT_HEADERS.index(WITHDRAWN_HEADER)))`.

Добавить в конец:
```python
def test_bot_cells_marks_withdrawal():
    from datetime import datetime, timezone
    assert bot_cells(make_referral())[WITHDRAWN_HEADER] == ""
    withdrawn = make_referral(withdrawn_at=datetime(2026, 9, 26, 15, 30, tzinfo=timezone.utc))
    assert bot_cells(withdrawn)[WITHDRAWN_HEADER] == "2026-09-26 10:30"


def test_hr_status_from_values():
    values = [HEADER, sheet_row(make_referral(1), status="Интервью"), sheet_row(make_referral(2, phone="+16502530001"))]
    assert hr_status_from_values(values, "R-000001") == "Интервью"
    assert hr_status_from_values(values, "R-000002") == ""
    assert hr_status_from_values(values, "R-000009") is None
    assert hr_status_from_values([[h for h in HEADER if h != "Статус"]], "R-000001") is None
    assert hr_status_from_values([], "R-000001") is None
```

В `tests/test_sheets.py` добавить:
```python
from referrals.sheet_model import WITHDRAWN_HEADER
from referrals.sheets import LiveHrStatus
from tests.factories import EMP_A


async def test_missing_withdrawn_header_is_added(db):
    referrals = await create_referrals(db, 1)
    old_header = [h for h in HEADER if h != WITHDRAWN_HEADER]
    sheet = FakeSheet([old_header], col_count=len(old_header))
    await sync_sheet(db, sheet, referrals)
    header = sheet.get_all_values()[0]
    assert header[len(old_header)] == WITHDRAWN_HEADER
    assert sheet.col_count >= len(old_header) + 1
    assert sheet.column("№") == ["R-000001"]


async def test_withdrawn_referral_is_marked_in_sheet(db):
    referrals = await create_referrals(db, 1)
    sheet = FakeSheet([HEADER])
    await sync_sheet(db, sheet, referrals)
    await repo.withdraw_referral(db, referrals[0].id, EMP_A)
    await sync_sheet(db, sheet, await repo.referrals_pending_sheet(db))
    [mark] = sheet.column(WITHDRAWN_HEADER)
    assert mark.startswith("20")
    assert await repo.referrals_pending_sheet(db) == []


async def test_live_hr_status_reads_the_sheet(db):
    referrals = await create_referrals(db, 1)
    sheet = FakeSheet([HEADER])
    await sync_sheet(db, sheet, referrals)
    sheet.grid[1][HEADER.index("Статус")] = "Интервью"
    assert await LiveHrStatus(lambda: sheet).hr_status("R-000001") == "Интервью"
    assert await LiveHrStatus(lambda: sheet).hr_status("R-000404") is None
```

Run: `.venv/bin/pytest tests/test_sheet_model.py tests/test_sheets.py -q`
Expected: FAIL — `cannot import name 'WITHDRAWN_HEADER'`.

- [ ] **Step 2: FakeSheet с лимитом колонок**

В `tests/fakes.py` в `FakeSheet.__init__` добавить параметр `col_count: int = 26` и поле `self.col_count = col_count`; в `_write` перед записью:
```python
        if col > self.col_count:
            raise ValueError(f"column {col} exceeds grid limits ({self.col_count})")
```
и метод:
```python
    def add_cols(self, count: int) -> None:
        self.col_count += count
```

- [ ] **Step 3: sheet_model**

В `referrals/sheet_model.py`:
```python
WITHDRAWN_HEADER = "Отозвана"
HR_STATUS_HEADER = "Статус"
```
(рядом с другими заголовками); `BOT_HEADERS` дополнить `WITHDRAWN_HEADER` последним элементом; в `bot_cells` последним ключом:
```python
        WITHDRAWN_HEADER: format_created(referral.withdrawn_at) if referral.withdrawn_at else "",
```
и функцию:
```python
def hr_status_from_values(values: Sequence[Sequence[str]], number: str) -> str | None:
    """«Статус» HR у строки заявки прямо из листа. None — нет колонки, номера или строки."""
    header = [str(h).strip() for h in values[0]] if values else []
    if ID_HEADER not in header or HR_STATUS_HEADER not in header:
        return None
    id_col, status_col = header.index(ID_HEADER), header.index(HR_STATUS_HEADER)
    for row in values[1:]:
        if _cell(row, id_col).strip() == number:
            return _cell(row, status_col).strip()
    return None
```

- [ ] **Step 4: sheets**

В `referrals/sheets.py`: импортировать `WITHDRAWN_HEADER, hr_status_from_values`; добавить
```python
AUTO_HEADERS = (WITHDRAWN_HEADER,)


def _ensure_auto_headers(ws, values) -> bool:
    """Дописывает недостающие заголовки новых колонок бота справа от последнего заголовка."""
    if not values:
        return False
    header = [str(h).strip() for h in values[0]]
    missing = [h for h in AUTO_HEADERS if h not in header]
    if not missing:
        return False
    width = len(header)
    while width and not header[width - 1]:
        width -= 1
    needed = width + len(missing)
    if needed > ws.col_count:
        ws.add_cols(needed - ws.col_count)
    ws.update(values=[missing], range_name=rowcol_to_a1(1, width + 1), value_input_option="RAW")
    return True


class LiveHrStatus:
    """Живое чтение колонки «Статус» для проверки перед отзывом заявки."""

    def __init__(self, open_ws) -> None:
        self._open_ws = open_ws

    async def hr_status(self, number: str) -> str | None:
        ws = await asyncio.to_thread(self._open_ws)
        values = await asyncio.to_thread(ws.get_all_values)
        return hr_status_from_values(values, number)
```
и в начале `sync_sheet` после чтения `values`:
```python
    if await asyncio.to_thread(_ensure_auto_headers, ws, values):
        values = await asyncio.to_thread(ws.get_all_values)
```

- [ ] **Step 5: DEPLOY.md**

В списке заголовков после `file_id` добавить `Отозвана` и пометку: «колонку `Отозвана` бот дописывает сам, если её нет».

- [ ] **Step 6: Тесты проходят**

Run: `.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add referrals/sheet_model.py referrals/sheets.py tests/fakes.py tests/test_sheet_model.py tests/test_sheets.py docs/DEPLOY.md
git commit -m "feat: колонка «Отозвана» в таблице (дописывается сама) и живое чтение «Статуса»" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Диалог «Мои рекомендации» и отзыв

**Files:**
- Create: `referrals/flow/mine.py`, `tests/test_flow_mine.py`
- Modify: `referrals/i18n/ru.py`, `referrals/i18n/en.py`, `referrals/flow/common.py`, `referrals/flow/io.py`, `referrals/flow/admin_texts.py`, `referrals/flow/router.py`, `tests/fakes.py`, `tests/test_flow_auth.py`

**Interfaces:**
- Consumes: Task 1 (`list_referrals_by_referrer`, `get_referral`, `withdraw_referral`, `WithdrawResult`), Task 2 (`HR_STATUS_HEADER`).
- Produces: `flow.io.SheetReader` (протокол: `async hr_status(number) -> str | None`); `router.handle_event(db, io, user, event, sheet: SheetReader | None = None)`; `mine.on_button(db, io, s, ref, data, sheet)`; `admin_texts.withdrawn_text(referral, referrer_name) -> str`; `tests.fakes.FakeSheetReader(statuses=None, fail=False)`.

- [ ] **Step 1: FakeSheetReader**

В `tests/fakes.py`:
```python
class FakeSheetReader:
    def __init__(self, statuses: dict[str, str] | None = None, fail: bool = False):
        self.statuses = dict(statuses or {})
        self.fail = fail
        self.calls: list[str] = []

    async def hr_status(self, number):
        self.calls.append(number)
        if self.fail:
            raise RuntimeError("sheets down")
        return self.statuses.get(number)
```

- [ ] **Step 2: Тесты (падают)**

В `tests/test_flow_auth.py` в `test_menu_and_language_switch` ожидание кнопок заменить на `["menu:refer", "menu:mine", "menu:language"]`.

`tests/test_flow_mine.py`:
```python
from referrals import repo
from referrals.flow.events import Button, Text, User
from referrals.flow.router import handle_event
from referrals.flow.steps import MENU, REF_LAST_NAME
from referrals.i18n import t
from referrals.models import Session
from tests.factories import EMP_B, make_draft, make_photo
from tests.fakes import FakeIo, FakeSheetReader
from tests.helpers import seed_referrer

USER = User(id=111, username="ivan", full_name="Ivan P")


async def setup(db):
    await seed_referrer(db)
    await seed_referrer(db, tg_user_id=222, emplid=EMP_B, name="Other Person")
    await repo.save_session(db, Session(tg_user_id=111, step=MENU, language="ru"))
    a = await repo.create_referral(db, make_draft(), make_photo(), Session(tg_user_id=111, step=MENU, language="ru"))
    foreign = make_draft(phone="+16502530001", email="o@example.com", referrer_tg_user_id=222,
                         referrer_emplid=EMP_B, referrer_name="Other Person")
    b = await repo.create_referral(db, foreign, make_photo(), Session(tg_user_id=222, step=MENU))
    c = await repo.create_referral(db, make_draft(phone="+16502530002", email="c@example.com"), make_photo(),
                                   Session(tg_user_id=111, step=MENU, language="ru"))
    return a, b, c


async def press(db, io, data, sheet=None):
    await handle_event(db, io, USER, Button(data), sheet=sheet)


async def test_list_shows_only_own_referrals_newest_first(db):
    a, _, c = await setup(db)
    io = FakeIo()
    await press(db, io, "menu:mine")
    assert io.last_text == t("ru", "mine_title")
    assert io.button_data() == [f"my:show:{c.id}", f"my:show:{a.id}", "my:menu"]
    labels = [label for row in io.replies[-1][1] for label, _ in row]
    assert labels[0].startswith("R-000003 · Aziz Karimov · ")


async def test_empty_list(db):
    await seed_referrer(db)
    await repo.save_session(db, Session(tg_user_id=111, step=MENU, language="ru"))
    io = FakeIo()
    await press(db, io, "menu:mine")
    assert t("ru", "mine_empty") in io.texts() and io.last_text == t("ru", "menu")


async def test_card_shows_data_but_no_hr_status(db):
    a, _, _ = await setup(db)
    await repo.apply_sheet_feedback(db, {a.id: (None, {"Статус": "Интервью"})})
    io = FakeIo()
    await press(db, io, f"my:show:{a.id}")
    assert "+16502530000" in io.last_text and "Интервью" not in io.last_text
    assert io.button_data() == [f"my:withdraw:{a.id}", "my:list"]


async def test_foreign_and_garbage_buttons_are_stale(db):
    _, b, _ = await setup(db)
    for data in (f"my:show:{b.id}", f"my:confirm:{b.id}", "my:show:abc", "my:explode:1", "my:confirm:999"):
        io = FakeIo()
        await press(db, io, data, sheet=FakeSheetReader())
        assert io.replies[0][0] == t("ru", "stale_button")
    assert (await repo.get_referral(db, b.id)).withdrawn_at is None


async def test_withdraw_flow(db):
    a, _, _ = await setup(db)
    io = FakeIo()
    sheet = FakeSheetReader({"R-000001": ""})
    await press(db, io, f"my:withdraw:{a.id}", sheet)
    assert io.last_text == t("ru", "withdraw_confirm", number="R-000001")
    assert io.button_data() == [f"my:confirm:{a.id}", f"my:show:{a.id}"]
    await press(db, io, f"my:confirm:{a.id}", sheet)
    assert t("ru", "withdrawn_done", number="R-000001") in io.texts()
    assert io.admin_messages[-1][0] == "↩️ Заявка R-000001 (Aziz Karimov) отозвана рекомендателем Ivan Petrov"
    assert io.kicks == 1 and sheet.calls == ["R-000001"]
    assert (await repo.get_referral(db, a.id)).withdrawn_at is not None
    labels = [label for row in io.replies[-1][1] for label, _ in row]
    assert labels[1].endswith("· отозвана")
    await press(db, io, f"my:confirm:{a.id}", sheet)
    assert t("ru", "already_withdrawn", number="R-000001") in io.texts()


async def test_withdraw_blocked_by_hr_status(db):
    a, _, _ = await setup(db)
    io = FakeIo()
    await press(db, io, f"my:confirm:{a.id}", FakeSheetReader({"R-000001": "Интервью"}))
    assert t("ru", "withdraw_blocked") in io.texts()
    assert not any("Интервью" in text for text in io.texts())
    assert (await repo.get_referral(db, a.id)).withdrawn_at is None
    assert io.admin_messages == []


async def test_withdraw_falls_back_to_db_copy_when_sheet_down(db):
    a, _, c = await setup(db)
    await repo.apply_sheet_feedback(db, {a.id: (None, {"Статус": "Позвонили"})})
    io = FakeIo()
    await press(db, io, f"my:confirm:{a.id}", FakeSheetReader(fail=True))
    assert t("ru", "withdraw_blocked") in io.texts()
    await press(db, io, f"my:confirm:{c.id}", FakeSheetReader(fail=True))
    assert (await repo.get_referral(db, c.id)).withdrawn_at is not None


async def test_candidate_can_be_referred_again_after_withdrawal(db):
    a, _, _ = await setup(db)
    io = FakeIo()
    await press(db, io, f"my:confirm:{a.id}", FakeSheetReader())
    await press(db, io, "menu:refer")
    for text in ("Aziz", "Karimov", "(650) 253-0000"):
        await handle_event(db, io, USER, Text(text))
    assert io.last_text == t("ru", "ask_email")


async def test_my_button_mid_form_is_stale(db):
    await setup(db)
    io = FakeIo()
    await press(db, io, "menu:refer")
    await handle_event(db, io, USER, Text("Aziz"))
    await press(db, io, "my:list")
    assert io.replies[-2][0] == t("ru", "stale_button")
    assert io.last_text == t("ru", "ask_last_name")
    session = await repo.load_session(db, 111)
    assert session.step == REF_LAST_NAME and session.data == {"first_name": "Aziz"}
```

Run: `.venv/bin/pytest tests/test_flow_mine.py tests/test_flow_auth.py -q`
Expected: FAIL — `KeyError: 'mine_title'` / неизвестная кнопка.

- [ ] **Step 3: Тексты**

`referrals/i18n/ru.py`, добавить ключи:
```python
    "btn_mine": "📋 Мои рекомендации",
    "mine_title": "Ваши рекомендации (последние 20). Нажмите на заявку, чтобы открыть её.",
    "mine_empty": "Вы ещё никого не рекомендовали.",
    "withdrawn_mark": "отозвана",
    "mine_card": "Заявка {number} от {date}\n\nИмя: {first_name}\nФамилия: {last_name}\nТелефон: {phone}\nПочта: {email}\nРаботал у нас: {worked}",
    "mine_card_withdrawn": "Отозвана {date}.",
    "btn_withdraw": "↩️ Отозвать",
    "btn_back_to_list": "← К списку",
    "btn_to_menu": "← В меню",
    "withdraw_confirm": "Отозвать заявку {number}? Кандидата можно будет рекомендовать заново.",
    "btn_withdraw_yes": "Да, отозвать",
    "btn_withdraw_no": "Нет",
    "withdraw_blocked": "Эту заявку отозвать нельзя, напишите HR.",
    "withdrawn_done": "Заявка {number} отозвана.",
    "already_withdrawn": "Заявка {number} уже отозвана.",
```
`referrals/i18n/en.py`:
```python
    "btn_mine": "📋 My referrals",
    "mine_title": "Your referrals (latest 20). Tap one to open it.",
    "mine_empty": "You haven't referred anyone yet.",
    "withdrawn_mark": "withdrawn",
    "mine_card": "Application {number} from {date}\n\nFirst name: {first_name}\nLast name: {last_name}\nPhone: {phone}\nEmail: {email}\nWorked with us: {worked}",
    "mine_card_withdrawn": "Withdrawn on {date}.",
    "btn_withdraw": "↩️ Withdraw",
    "btn_back_to_list": "← Back to list",
    "btn_to_menu": "← Menu",
    "withdraw_confirm": "Withdraw application {number}? The candidate can be referred again.",
    "btn_withdraw_yes": "Yes, withdraw",
    "btn_withdraw_no": "No",
    "withdraw_blocked": "This application can't be withdrawn. Please contact HR.",
    "withdrawn_done": "Application {number} has been withdrawn.",
    "already_withdrawn": "Application {number} is already withdrawn.",
```

- [ ] **Step 4: Меню, протокол, текст для HR**

`referrals/flow/common.py` — `menu_buttons`:
```python
def menu_buttons(lang: str | None) -> Buttons:
    return [[(t(lang, "btn_refer"), "menu:refer")],
            [(t(lang, "btn_mine"), "menu:mine")],
            [(t(lang, "btn_language"), "menu:language")]]
```
`referrals/flow/io.py` — добавить:
```python
class SheetReader(Protocol):
    async def hr_status(self, number: str) -> str | None: ...
```
`referrals/flow/admin_texts.py` — добавить:
```python
def withdrawn_text(referral: Referral, referrer_name: str) -> str:
    return (f"↩️ Заявка {referral.number} ({referral.first_name} {referral.last_name}) "
            f"отозвана рекомендателем {referrer_name}")
```

- [ ] **Step 5: Модуль mine**

`referrals/flow/mine.py`:
```python
"""«Мои рекомендации»: список своих заявок, карточка и отзыв. Работает на шаге MENU."""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from referrals import repo
from referrals.config import TZ
from referrals.db import Db
from referrals.flow import admin_texts
from referrals.flow.common import show_menu
from referrals.flow.io import Io, SheetReader
from referrals.i18n import t
from referrals.models import Referral, Referrer, Session, WithdrawResult
from referrals.sheet_model import HR_STATUS_HEADER

log = logging.getLogger(__name__)
LIST_LIMIT = 20


def _date(moment: datetime, fmt: str) -> str:
    return moment.astimezone(ZoneInfo(TZ)).strftime(fmt)


def _label(referral: Referral, lang: str | None) -> str:
    label = f"{referral.number} · {referral.first_name} {referral.last_name} · {_date(referral.created_at, '%d.%m')}"
    return f"{label} · {t(lang, 'withdrawn_mark')}" if referral.withdrawn_at else label


async def show_list(db: Db, io: Io, s: Session, ref: Referrer) -> None:
    lang = s.language
    items = await repo.list_referrals_by_referrer(db, ref.emplid, LIST_LIMIT)
    if not items:
        await io.reply(t(lang, "mine_empty"))
        await show_menu(io, lang)
        return
    buttons = [[(_label(r, lang), f"my:show:{r.id}")] for r in items]
    buttons.append([(t(lang, "btn_to_menu"), "my:menu")])
    await io.reply(t(lang, "mine_title"), buttons)


async def _show_card(io: Io, s: Session, referral: Referral) -> None:
    lang = s.language
    text = t(lang, "mine_card", number=referral.number, date=_date(referral.created_at, "%d.%m.%Y"),
             first_name=referral.first_name, last_name=referral.last_name, phone=referral.phone,
             email=referral.email, worked=t(lang, "btn_yes" if referral.worked_before else "btn_no"))
    buttons = []
    if referral.withdrawn_at:
        text += "\n\n" + t(lang, "mine_card_withdrawn", date=_date(referral.withdrawn_at, "%d.%m.%Y"))
    else:
        buttons.append([(t(lang, "btn_withdraw"), f"my:withdraw:{referral.id}")])
    buttons.append([(t(lang, "btn_back_to_list"), "my:list")])
    await io.reply(text, buttons)


async def _own_referral(db: Db, ref: Referrer, raw_id: str) -> Referral | None:
    if not raw_id.isdigit():
        return None
    referral = await repo.get_referral(db, int(raw_id))
    return referral if referral is not None and referral.referrer_emplid == ref.emplid else None


async def _hr_status(sheet: SheetReader | None, referral: Referral) -> str:
    status = None
    if sheet is not None:
        try:
            status = await sheet.hr_status(referral.number)
        except Exception:
            log.exception("не удалось прочитать «Статус» заявки %s из таблицы", referral.number)
    if status is None:
        status = referral.hr_data.get(HR_STATUS_HEADER, "")
    return status.strip()


async def on_button(db: Db, io: Io, s: Session, ref: Referrer, data: str, sheet: SheetReader | None) -> None:
    lang = s.language
    if data in ("menu:mine", "my:list"):
        await show_list(db, io, s, ref)
        return
    if data == "my:menu":
        await show_menu(io, lang)
        return
    action, _, raw_id = data.removeprefix("my:").partition(":")
    referral = await _own_referral(db, ref, raw_id)
    if referral is None or action not in ("show", "withdraw", "confirm"):
        await io.reply(t(lang, "stale_button"))
        await show_list(db, io, s, ref)
        return
    if action == "show":
        await _show_card(io, s, referral)
        return
    if referral.withdrawn_at is not None:
        await io.reply(t(lang, "already_withdrawn", number=referral.number))
        await _show_card(io, s, referral)
        return
    if action == "withdraw":
        await io.reply(t(lang, "withdraw_confirm", number=referral.number),
                       [[(t(lang, "btn_withdraw_yes"), f"my:confirm:{referral.id}")],
                        [(t(lang, "btn_withdraw_no"), f"my:show:{referral.id}")]])
        return
    if await _hr_status(sheet, referral):
        await io.reply(t(lang, "withdraw_blocked"))
        await _show_card(io, s, referral)
        return
    result = await repo.withdraw_referral(db, referral.id, ref.emplid)
    if result is WithdrawResult.WITHDRAWN:
        await io.reply(t(lang, "withdrawn_done", number=referral.number))
        await io.send_admin(admin_texts.withdrawn_text(referral, ref.name))
        io.kick_background()
    elif result is WithdrawResult.ALREADY:
        await io.reply(t(lang, "already_withdrawn", number=referral.number))
    else:
        await io.reply(t(lang, "stale_button"))
    await show_list(db, io, s, ref)
```

- [ ] **Step 6: Роутер**

`referrals/flow/router.py`:
- импорт: `from referrals.flow import auth, mine, referral` и `from referrals.flow.io import Io, SheetReader`;
- сигнатура: `async def handle_event(db: Db, io: Io, user: User, event: Event, sheet: SheetReader | None = None) -> None:`;
- ветка меню: `await _on_menu(db, io, s, ref, event, sheet)`;
- `_on_menu`:
```python
async def _on_menu(db: Db, io: Io, s: Session, ref: Referrer, event: Event, sheet: SheetReader | None) -> None:
    if isinstance(event, Button):
        if event.data == "menu:refer":
            await referral.start_form(db, io, s)
            return
        if event.data == "menu:language":
            s.step = LANG
            await repo.save_session(db, s)
            await prompt_language(io)
            return
        if event.data == "menu:mine" or event.data.startswith("my:"):
            await mine.on_button(db, io, s, ref, event.data, sheet)
            return
        await io.reply(t(s.language, "stale_button"))
    await show_menu(io, s.language)
```

- [ ] **Step 7: Тесты проходят**

Run: `.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add referrals/flow referrals/i18n tests/fakes.py tests/test_flow_mine.py tests/test_flow_auth.py
git commit -m "feat: «Мои рекомендации» — список, карточка и отзыв заявки" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Подключение живой проверки «Статуса» в Telegram-адаптере

**Files:**
- Modify: `referrals/app.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: `LiveHrStatus`, `open_worksheet`, `handle_event(..., sheet=...)`.
- Produces: `app.sheet_reader(cfg) -> LiveHrStatus`.

- [ ] **Step 1: Тест (падает)**

В `tests/test_app.py`:
```python
async def test_sheet_reader_reads_status_from_configured_sheet(monkeypatch):
    from referrals import app as app_module
    from referrals.sheet_model import BOT_HEADERS, PHOTO_HEADER
    from tests.fakes import FakeSheet
    opened = []
    row = ["R-000001"] + [""] * (len(BOT_HEADERS) - 1) + ["", "Интервью"]
    sheet = FakeSheet([[*BOT_HEADERS, PHOTO_HEADER, "Статус"], row])

    def fake_open(credentials, spreadsheet_id, sheet_name):
        opened.append((spreadsheet_id, sheet_name))
        return sheet

    monkeypatch.setattr(app_module, "open_worksheet", fake_open)
    assert await app_module.sheet_reader(CFG).hr_status("R-000001") == "Интервью"
    assert opened == [("s", "Заявки")]
```
Run: `.venv/bin/pytest tests/test_app.py -q` → FAIL: `has no attribute 'sheet_reader'`.

- [ ] **Step 2: Реализация**

В `referrals/app.py`: импорт `from referrals.sheets import LiveHrStatus, open_worksheet`; функция
```python
def sheet_reader(cfg: Config) -> LiveHrStatus:
    return LiveHrStatus(lambda: open_worksheet(cfg.google_credentials, cfg.spreadsheet_id, cfg.sheet_name))
```
и в `on_private`:
```python
    deps = _deps(context)
    await handle_event(deps.db, io, to_user(update), to_event(update), sheet=sheet_reader(deps.cfg))
```

- [ ] **Step 3: Весь набор**

Run: `.venv/bin/pytest -q && node --test tests/gas/photos.test.js`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add referrals/app.py tests/test_app.py
git commit -m "feat: живая проверка «Статуса» при отзыве в Telegram-адаптере" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Постоянная кнопка «✖️ Отмена» внизу экрана

Дизайн согласован в чате 2026-09-26: кнопка видна всегда (reply-клавиатура Telegram), в анкете отменяет черновик, в меню просто показывает меню; `/cancel` работает, но убирается из меню команд.

**Files:**
- Create: `tests/test_flow_cancel.py`
- Modify: `referrals/flow/io.py`, `tests/fakes.py`, `referrals/flow/router.py`, `referrals/flow/auth.py`, `referrals/flow/admin.py`, `referrals/i18n/ru.py`, `referrals/i18n/en.py`, `referrals/app.py`

**Interfaces:**
- Produces: `Io.reply(text, buttons=None, keyboard: list[str] | None = None)` и `Io.send_user(tg_user_id, text, buttons=None, keyboard=None)` — при `keyboard` сообщение несёт постоянную reply-клавиатуру из одной строки кнопок; `FakeIo.keyboards` / `FakeIo.user_keyboards` — списки `(text, labels)`; `router.CANCEL_LABELS` — надписи кнопки на всех языках (`btn_cancel` ru и en).

- [ ] **Step 1: FakeIo**

В `tests/fakes.py` у `FakeIo`: в `__init__` поля `self.keyboards = []` и `self.user_keyboards = []`;
```python
    async def reply(self, text, buttons=None, keyboard=None):
        self.replies.append((text, buttons))
        if keyboard is not None:
            self.keyboards.append((text, keyboard))

    async def send_user(self, tg_user_id, text, buttons=None, keyboard=None):
        self.user_messages.append((tg_user_id, text, buttons))
        if keyboard is not None:
            self.user_keyboards.append((tg_user_id, text, keyboard))
```

- [ ] **Step 2: Тесты (падают)**

`tests/test_flow_cancel.py`:
```python
from referrals import repo
from referrals.flow.admin import on_admin_button
from referrals.flow.events import Button, Command, Text, User
from referrals.flow.router import handle_event
from referrals.flow.steps import AUTH_WAIT_ID, MENU
from referrals.i18n import t
from referrals.models import Session
from tests.factories import EMP_A
from tests.fakes import FakeIo
from tests.helpers import seed_employees

USER = User(id=111, username="ivan", full_name="Ivan P")


async def verified(db, io, lang="ru"):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await handle_event(db, io, USER, Command("start"))
    await handle_event(db, io, USER, Button(f"lang:{lang}"))
    await handle_event(db, io, USER, Text(EMP_A))


async def test_keyboard_appears_after_verification(db):
    io = FakeIo()
    await verified(db, io)
    assert io.keyboards == [(t("ru", "welcome", name="Ivan Petrov"), [t("ru", "btn_cancel")])]


async def test_cancel_button_mid_form_cancels_draft(db):
    io = FakeIo()
    await verified(db, io)
    await handle_event(db, io, USER, Button("menu:refer"))
    await handle_event(db, io, USER, Text("Aziz"))
    await handle_event(db, io, USER, Text(t("ru", "btn_cancel")))
    assert t("ru", "cancelled") in io.texts() and io.last_text == t("ru", "menu")
    session = await repo.load_session(db, 111)
    assert (session.step, session.data) == (MENU, {})


async def test_cancel_button_in_menu_just_shows_menu(db):
    io = FakeIo()
    await verified(db, io)
    before = len(io.replies)
    await handle_event(db, io, USER, Text(t("ru", "btn_cancel")))
    assert [text for text, _ in io.replies[before:]] == [t("ru", "menu")]


async def test_cancel_label_of_other_language_works(db):
    io = FakeIo()
    await verified(db, io, lang="en")
    await handle_event(db, io, USER, Button("menu:refer"))
    await handle_event(db, io, USER, Text(t("ru", "btn_cancel")))
    assert t("en", "cancelled") in io.texts()


async def test_start_and_language_switch_resend_keyboard(db):
    io = FakeIo()
    await verified(db, io)
    await handle_event(db, io, USER, Command("start"))
    assert io.keyboards[-1] == (t("ru", "keyboard_hint"), [t("ru", "btn_cancel")])
    await handle_event(db, io, USER, Button("menu:language"))
    await handle_event(db, io, USER, Button("lang:en"))
    assert io.keyboards[-1] == (t("en", "keyboard_hint"), [t("en", "btn_cancel")])
    assert io.last_text == t("en", "menu")


async def test_cancel_button_for_unverified_user_returns_to_id_prompt(db):
    io = FakeIo()
    await handle_event(db, io, USER, Command("start"))
    await handle_event(db, io, USER, Button("lang:ru"))
    await handle_event(db, io, USER, Text(t("ru", "btn_cancel")))
    assert io.last_text == t("ru", "ask_id")
    assert (await repo.load_session(db, 111)).step == AUTH_WAIT_ID


async def test_admin_approval_sends_keyboard_to_user(db):
    await seed_employees(db, (EMP_A, "Ivan Petrov"))
    await repo.save_session(db, Session(tg_user_id=111, step=AUTH_WAIT_ID, language="ru"))
    io = FakeIo()
    await on_admin_button(db, io, 7, frozenset({7}), f"v:111:{EMP_A}", (-100, 1))
    assert io.user_keyboards == [(111, t("ru", "welcome", name="Ivan Petrov"), [t("ru", "btn_cancel")])]
```
Run: `.venv/bin/pytest tests/test_flow_cancel.py -q` → FAIL (`keyboard_hint` нет, клавиатура не отправляется).

- [ ] **Step 3: Тексты**

`ru.py`: `"keyboard_hint": "Кнопка «✖️ Отмена» внизу экрана отменяет анкету в любой момент.",`
`en.py`: `"keyboard_hint": "The “✖️ Cancel” button at the bottom cancels the form at any time.",`

- [ ] **Step 4: Протокол Io**

`referrals/flow/io.py`:
```python
    async def reply(self, text: str, buttons: Buttons | None = None, keyboard: list[str] | None = None) -> None: ...
    async def send_user(self, tg_user_id: int, text: str, buttons: Buttons | None = None,
                        keyboard: list[str] | None = None) -> None: ...
```

- [ ] **Step 5: Роутер**

`referrals/flow/router.py`:
```python
CANCEL_LABELS = frozenset({t("ru", "btn_cancel"), t("en", "btn_cancel")})
```
В `handle_event` сразу после блока `if isinstance(event, Command): ...` добавить:
```python
    if isinstance(event, Text) and event.text.strip() in CANCEL_LABELS:
        await _on_cancel(db, io, s, ref)
        return
```
(импортировать `Text` из `referrals.flow.events`). `_on_cancel` для подтверждённого: анкета → `referral.cancel_form`, иначе — только меню:
```python
    if s.step in FORM_STEPS:
        await referral.cancel_form(db, io, s)
    else:
        await show_menu(io, s.language)
```
В `_on_start` в ветке меню перед `show_menu`:
```python
    await io.reply(t(s.language, "keyboard_hint"), keyboard=[t(s.language, "btn_cancel")])
```

- [ ] **Step 6: Проверка и админ**

`referrals/flow/auth.py`: в `_verify` приветствие отправлять с клавиатурой:
`await io.reply(t(s.language, "welcome", name=name), keyboard=[t(s.language, "btn_cancel")])`;
в `on_language` для подтверждённого перед `show_menu`:
`await io.reply(t(lang, "keyboard_hint"), keyboard=[t(lang, "btn_cancel")])`.
`referrals/flow/admin.py` в `_approve`:
`await io.send_user(tg_user_id, t(s.language, "welcome", name=employee.name), keyboard=[t(s.language, "btn_cancel")])`.

- [ ] **Step 7: Адаптер**

`referrals/app.py`: импорт `KeyboardButton, ReplyKeyboardMarkup`; функция
```python
def _markup(buttons: Buttons | None, keyboard: list[str] | None):
    if keyboard:
        return ReplyKeyboardMarkup([[KeyboardButton(label) for label in keyboard]],
                                   resize_keyboard=True, is_persistent=True)
    return to_markup(buttons)
```
`TelegramIo.reply` и `send_user` принимают `keyboard=None` и передают `reply_markup=_markup(buttons, keyboard)`. В `post_init` меню команд — только `BotCommand("start", "Начать / меню")`.

В `tests/test_app.py`:
```python
def test_reply_keyboard_markup():
    from telegram import ReplyKeyboardMarkup
    from referrals.app import _markup
    markup = _markup(None, ["✖️ Отмена"])
    assert isinstance(markup, ReplyKeyboardMarkup) and markup.is_persistent and markup.resize_keyboard
    assert [b.text for b in markup.keyboard[0]] == ["✖️ Отмена"]
    assert _markup(None, None) is None
```

- [ ] **Step 8: Весь набор**

Run: `.venv/bin/pytest -q && node --test tests/gas/photos.test.js` → PASS.

- [ ] **Step 9: Commit**

```bash
git add referrals tests
git commit -m "feat: постоянная кнопка «✖️ Отмена» внизу экрана" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
