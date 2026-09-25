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
