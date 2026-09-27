from datetime import datetime, timezone

import pytest

from referrals.sheet_model import (
    BOT_HEADERS,
    PHOTO_HEADER,
    WITHDRAWN_HEADER,
    CellUpdate,
    SheetLayoutError,
    bot_cells,
    build_row,
    format_created,
    hr_status_from_values,
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
    assert layout.columns[PHOTO_HEADER] == 11
    assert layout.hr_columns == {"Статус": 12, "Заметки": 13}
    assert layout.width == 14


def test_parse_layout_any_order_and_spaces():
    layout = parse_layout(["Заметки", f" {PHOTO_HEADER} ", *reversed(BOT_HEADERS)])
    assert layout.columns["№"] == 12
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
    assert {u.col for u in plan.cell_updates} == set(range(3, BOT_HEADERS.index(WITHDRAWN_HEADER)))
    assert all(u.row == 3 for u in plan.cell_updates)


def test_build_row_restores_photo_and_hr_from_db():
    layout = parse_layout(HEADER)
    row = build_row(layout, make_referral(photo_url="https://drive/1", hr_data={"Статус": "Интервью", "Удалена": "x"}))
    assert row[layout.columns[PHOTO_HEADER]] == "https://drive/1"
    assert row[layout.hr_columns["Статус"]] == "Интервью"
    assert row[layout.hr_columns["Заметки"]] == ""


def test_plan_restores_blank_number_by_phone():
    r1 = make_referral(1, hr_data={"Статус": "Позвонили"})
    row = sheet_row(r1, status="Позвонили")
    row[0] = ""
    _, plan = plan_reconcile([HEADER, row], [r1])
    assert plan.appends == []
    assert plan.cell_updates == [CellUpdate(1, 0, "R-000001")]
    assert plan.feedback == {} and plan.unknown_numbers == []


def test_plan_reports_blank_number_rows_without_match():
    r1 = make_referral(1)
    orphan = sheet_row(make_referral(5, phone="+16502530009", email="x@example.com", photo_file_id="f-5"))
    orphan[0] = ""
    _, plan = plan_reconcile([HEADER, sheet_row(r1), orphan], [r1])
    assert plan.unknown_numbers == ["без № (строка 3)"]


IMAGE_FORMULA = ('=HYPERLINK("https://drive.google.com/file/d/abc123/view", '
                 'IMAGE("https://drive.google.com/uc?export=view&id=abc123"))')


def test_photo_url_is_read_from_image_formula():
    r1 = make_referral(1)
    # у ячейки с картинкой нет текстового значения — ссылку берём из формулы
    _, plan = plan_reconcile([HEADER, sheet_row(r1, photo="")], [r1], photo_formulas=["", IMAGE_FORMULA])
    assert plan.feedback == {1: ("https://drive.google.com/file/d/abc123/view", {})}


def test_photo_formula_matching_db_gives_no_feedback():
    r1 = make_referral(1, photo_url="https://drive.google.com/file/d/abc123/view")
    _, plan = plan_reconcile([HEADER, sheet_row(r1, photo="")], [r1], photo_formulas=["", IMAGE_FORMULA])
    assert plan.feedback == {}


def test_plain_photo_link_still_read_without_formulas():
    r1 = make_referral(1)
    _, plan = plan_reconcile([HEADER, sheet_row(r1, photo="https://drive/x")], [r1], photo_formulas=["", ""])
    assert plan.feedback == {1: ("https://drive/x", {})}


def test_bot_cells_marks_withdrawal():
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


def test_blank_row_prefers_file_id_when_contacts_repeat():
    withdrawn = make_referral(1, photo_file_id="f-1", withdrawn_at=datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc))
    again = make_referral(2, photo_file_id="f-2")  # тот же кандидат, рекомендован снова
    row = sheet_row(withdrawn, status="Отказ")
    row[0] = ""
    _, plan = plan_reconcile([HEADER, row], [withdrawn, again])
    assert CellUpdate(1, 0, "R-000001") in plan.cell_updates
    assert plan.appends == [again]


def test_blank_row_with_ambiguous_contacts_is_reported_not_matched():
    first = make_referral(1, photo_file_id="f-1")
    second = make_referral(2, photo_file_id="f-2")
    row = sheet_row(first)
    row[0] = ""
    row[BOT_HEADERS.index("file_id")] = ""
    _, plan = plan_reconcile([HEADER, row], [first, second])
    assert plan.unknown_numbers == ["без № (строка 2)"]
    assert all(u.row != 1 for u in plan.cell_updates)


def test_push_mode_matches_blank_rows_only_by_file_id():
    withdrawn = make_referral(1, photo_file_id="f-1")
    again = make_referral(2, photo_file_id="f-2")
    row = sheet_row(withdrawn, status="Отказ")
    row[0] = ""
    # при дозаписи видна только новая заявка: телефон совпадает, но по контактам не сопоставляем
    _, plan = plan_reconcile([HEADER, row], [again], match_by_contacts=False)
    assert plan.appends == [again] and all(u.row != 1 for u in plan.cell_updates)
    # отозванная заявка тоже ждёт выгрузки — её строку узнаём по file_id, дубля нет
    _, plan = plan_reconcile([HEADER, row], [withdrawn, again], match_by_contacts=False)
    assert CellUpdate(1, 0, "R-000001") in plan.cell_updates and plan.appends == [again]
