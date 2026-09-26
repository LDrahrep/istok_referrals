"""Запись заявок в Google-таблицу «Заявки» и обратное чтение колонок GAS/HR."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

import gspread
from gspread.utils import ValueRenderOption, rowcol_to_a1

from referrals import repo
from referrals.db import Db
from referrals.models import Referral, referral_number
from referrals.sheet_model import PHOTO_HEADER, Layout, build_row, parse_layout, plan_reconcile


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


def _photo_formulas(ws, layout: Layout, row_count: int) -> list[str]:
    """Формулы колонки «Фото»: GAS пишет туда HYPERLINK(…, IMAGE(…)), у которой нет текстового значения."""
    if row_count <= 1:
        return []
    column = rowcol_to_a1(1, layout.columns[PHOTO_HEADER] + 1).rstrip("0123456789")
    rows = ws.get(f"{column}1:{column}{row_count}", value_render_option=ValueRenderOption.formula)
    cells = [str(row[0]) if row else "" for row in rows]
    return cells + [""] * (row_count - len(cells))


async def sync_sheet(db: Db, ws, referrals: Sequence[Referral]) -> SheetSyncReport:
    """Приводит колонки бота к базе, дописывает недостающие строки, забирает «Фото» и колонки HR."""
    values = await asyncio.to_thread(ws.get_all_values)
    layout = parse_layout(values[0] if values else [])
    photo_formulas = await asyncio.to_thread(_photo_formulas, ws, layout, len(values))
    layout, plan = plan_reconcile(values, referrals, photo_formulas)

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
