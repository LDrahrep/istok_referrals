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
_FORMULA_URL_RE = re.compile(r'"(https?://[^"]+)"')


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
    """Строка для дозаписи. «Фото» и колонки HR берутся из копии в базе: если строку удалили,
    она восстанавливается целиком, а следующая сверка не затрёт эту копию пустыми ячейками."""
    row = [""] * layout.width
    for header, value in bot_cells(referral).items():
        row[layout.columns[header]] = value
    row[layout.columns[PHOTO_HEADER]] = referral.photo_url or ""
    for header, value in referral.hr_data.items():
        if header in layout.hr_columns:
            row[layout.hr_columns[header]] = value
    return row


def parse_number(cell: str) -> int | None:
    match = _NUMBER_RE.fullmatch(cell.strip())
    return int(match.group(1)) if match else None


def _cell(row: Sequence[str], index: int) -> str:
    return str(row[index]) if index < len(row) else ""


def photo_url_from_cell(value: str, formula: str = "") -> str | None:
    """Ссылка на фото из ячейки «Фото». GAS пишет туда формулу HYPERLINK(ссылка, IMAGE(…)), у которой
    нет текстового значения, поэтому ссылку берём из формулы; обычный текст — как есть."""
    match = _FORMULA_URL_RE.search(formula or "")
    if match:
        return match.group(1)
    return value.strip() or None


def _match_blank_row(row: Sequence[str], layout: Layout, candidates: Sequence[Referral]) -> Referral | None:
    phone = _cell(row, layout.columns["Телефон"]).strip()
    email = _cell(row, layout.columns["Почта"]).strip().lower()
    file_id = _cell(row, layout.columns[FILE_ID_HEADER]).strip()
    for referral in candidates:
        if (phone and phone == referral.phone) or (email and email == referral.email) or (
                file_id and file_id == referral.photo_file_id):
            return referral
    return None


def plan_reconcile(values: Sequence[Sequence[str]], referrals: Sequence[Referral],
                   photo_formulas: Sequence[str] = ()) -> tuple[Layout, ReconcilePlan]:
    """Что нужно дописать/исправить в таблице и что забрать из колонок «Фото» и HR."""
    layout = parse_layout(values[0] if values else [])
    id_col = layout.columns[ID_HEADER]
    photo_col = layout.columns[PHOTO_HEADER]
    known = {r.id for r in referrals}
    row_of: dict[int, int] = {}
    duplicates: set[int] = set()
    plan = ReconcilePlan()

    blank_rows: list[int] = []
    for index in range(1, len(values)):
        cell = _cell(values[index], id_col).strip()
        if not cell:
            if any(_cell(values[index], layout.columns[h]).strip() for h in BOT_HEADERS if h != ID_HEADER):
                blank_rows.append(index)
            continue
        number = parse_number(cell)
        if number is None or number not in known:
            plan.unknown_numbers.append(cell)
        elif number in row_of:
            duplicates.add(number)
        else:
            row_of[number] = index
    plan.duplicate_ids = sorted(duplicates)

    # Строка с затёртым «№»: узнаём заявку по телефону, почте или file_id и возвращаем номер,
    # вместо того чтобы дописывать дубль и осиротить заметки HR.
    unplaced = [r for r in referrals if r.id not in row_of and r.id not in duplicates]
    for index in blank_rows:
        match = _match_blank_row(values[index], layout, unplaced)
        if match is None:
            plan.unknown_numbers.append(f"без № (строка {index + 1})")
            continue
        row_of[match.id] = index
        unplaced.remove(match)

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
        photo = photo_url_from_cell(_cell(row, photo_col), _cell(photo_formulas, index))
        hr = {h: _cell(row, c) for h, c in layout.hr_columns.items() if _cell(row, c).strip()}
        if photo != referral.photo_url or hr != referral.hr_data:
            plan.feedback[referral.id] = (photo, hr)
    return layout, plan
