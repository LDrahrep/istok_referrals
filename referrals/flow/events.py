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
