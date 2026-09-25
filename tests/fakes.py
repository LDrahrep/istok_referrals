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
