"""Фейки внешних систем для тестов."""
from gspread.utils import a1_to_rowcol


class FakeSheet:
    """Имитация gspread.Worksheet: сетка строк, лимит строк как у настоящего листа."""

    def __init__(self, rows, row_count: int = 1000, col_count: int = 26):
        self.grid = [list(r) for r in rows]
        self.row_count = row_count
        self.col_count = col_count
        self.writes: list[tuple[str, str | None]] = []

    @staticmethod
    def _display(cell):
        # Как в настоящем листе: у формулы с картинкой (IMAGE) нет текстового значения.
        return "" if str(cell).startswith("=") else cell

    def get_all_values(self):
        rows = [[self._display(c) for c in r] for r in self.grid]
        while rows and not any(str(c).strip() for c in rows[-1]):
            rows.pop()
        width = max((len(r) for r in rows), default=0)
        return [r + [""] * (width - len(r)) for r in rows]

    def _write(self, row: int, col: int, value: str) -> None:
        if row > self.row_count:
            raise ValueError(f"row {row} exceeds grid limits ({self.row_count})")
        if col > self.col_count:
            raise ValueError(f"column {col} exceeds grid limits ({self.col_count})")
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

    def get(self, range_name, value_render_option=None):
        start, end = range_name.split(":")
        (r1, c1), (r2, c2) = a1_to_rowcol(start), a1_to_rowcol(end)
        formulas = str(value_render_option).upper().endswith("FORMULA")
        result = []
        for r in range(r1, r2 + 1):
            line = self.grid[r - 1] if r - 1 < len(self.grid) else []
            cells = [line[c - 1] if c - 1 < len(line) else "" for c in range(c1, c2 + 1)]
            result.append(cells if formulas else [self._display(c) for c in cells])
        return result

    def add_rows(self, count: int) -> None:
        self.row_count += count

    def add_cols(self, count: int) -> None:
        self.col_count += count

    def column(self, header: str) -> list[str]:
        values = self.get_all_values()
        index = values[0].index(header)
        return [row[index] for row in values[1:]]


class FakeIo:
    """Имитация Telegram для логики диалога: всё, что бот «сказал», складывается в списки."""

    def __init__(self, files: dict[str, bytes] | None = None):
        self.files = dict(files or {})
        self.replies: list[tuple[str, list | None]] = []
        self.admin_messages: list[tuple[str, list | None]] = []
        self.admin_edits: list[tuple[tuple[int, int], str]] = []
        self.user_messages: list[tuple[int, str, list | None]] = []
        self.answered: list[str | None] = []
        self.keyboards_removed: list[bool] = []
        self.keyboards: list[tuple[str, list[str]]] = []
        self.user_keyboards: list[tuple[int, str, list[str]]] = []
        self.kicks = 0
        self._next_message_id = 100

    async def reply(self, text, buttons=None, keyboard=None):
        self.replies.append((text, buttons))
        if keyboard is not None:
            self.keyboards.append((text, keyboard))

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

    async def send_user(self, tg_user_id, text, buttons=None, keyboard=None):
        self.user_messages.append((tg_user_id, text, buttons))
        if keyboard is not None:
            self.user_keyboards.append((tg_user_id, text, keyboard))

    async def answer_button(self, text=None, remove_keyboard=True):
        self.answered.append(text)
        self.keyboards_removed.append(remove_keyboard)

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


class FakeSheetReader:
    def __init__(self, statuses: dict[str, str] | None = None, fail: bool = False, delay: float = 0):
        self.statuses = dict(statuses or {})
        self.fail = fail
        self.delay = delay
        self.calls: list[str] = []

    async def hr_status(self, number):
        self.calls.append(number)
        if self.delay:
            import asyncio
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("sheets down")
        return self.statuses.get(number)
