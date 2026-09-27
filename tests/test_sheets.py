import pytest

from referrals import repo
from referrals.models import Session
from referrals.sheet_model import BOT_HEADERS, PHOTO_HEADER, WITHDRAWN_HEADER, SheetLayoutError
from referrals.sheets import LiveHrStatus, sync_sheet
from tests.factories import EMP_A, make_draft, make_photo
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


async def test_restored_row_keeps_hr_data_and_photo(db):
    referrals = await create_referrals(db, 1)
    sheet = FakeSheet([HEADER])
    await sync_sheet(db, sheet, referrals)
    sheet.grid[1][HEADER.index(PHOTO_HEADER)] = "https://drive/1"
    sheet.grid[1][HEADER.index("Статус")] = "Интервью"
    await sync_sheet(db, sheet, await repo.all_referrals(db))
    del sheet.grid[1]
    await sync_sheet(db, sheet, await repo.all_referrals(db))
    await sync_sheet(db, sheet, await repo.all_referrals(db))
    [referral] = await repo.all_referrals(db)
    assert (referral.photo_url, referral.hr_data) == ("https://drive/1", {"Статус": "Интервью"})
    assert sheet.column("Статус") == ["Интервью"]


async def test_cleared_number_is_restored_without_duplicate(db):
    referrals = await create_referrals(db, 1)
    sheet = FakeSheet([HEADER])
    await sync_sheet(db, sheet, referrals)
    sheet.grid[1][HEADER.index("Статус")] = "Позвонили"
    sheet.grid[1][0] = ""
    report = await sync_sheet(db, sheet, await repo.all_referrals(db))
    assert report.appended == 0
    assert sheet.column("№") == ["R-000001"]
    assert sheet.column("Статус") == ["Позвонили"]


IMAGE_FORMULA = ('=HYPERLINK("https://drive.google.com/file/d/abc123/view", '
                 'IMAGE("https://drive.google.com/uc?export=view&id=abc123"))')


async def test_image_formula_in_photo_column_is_read_back(db):
    referrals = await create_referrals(db, 1)
    sheet = FakeSheet([HEADER])
    await sync_sheet(db, sheet, referrals)
    sheet.grid[1][HEADER.index(PHOTO_HEADER)] = IMAGE_FORMULA
    await sync_sheet(db, sheet, await repo.all_referrals(db))
    [referral] = await repo.all_referrals(db)
    assert referral.photo_url == "https://drive.google.com/file/d/abc123/view"
    assert sheet.grid[1][HEADER.index(PHOTO_HEADER)] == IMAGE_FORMULA


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


async def test_withdrawn_header_does_not_take_over_unlabeled_hr_column(db):
    referrals = await create_referrals(db, 1)
    old_header = [h for h in HEADER if h != WITHDRAWN_HEADER]
    # живая таблица: строка заявки, а справа от «Статус» — заметка HR в столбце без заголовка
    row = ["R-000001"] + [""] * (len(old_header) - 1) + ["позвонить в пн"]
    sheet = FakeSheet([old_header, row], col_count=len(old_header) + 1)
    await sync_sheet(db, sheet, referrals)
    header = sheet.get_all_values()[0]
    assert header.index(WITHDRAWN_HEADER) == len(old_header) + 1
    assert sheet.grid[1][len(old_header)] == "позвонить в пн"
