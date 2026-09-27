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


class WithdrawResult(enum.Enum):
    WITHDRAWN = "withdrawn"
    ALREADY = "already"
    NOT_FOUND = "not_found"


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
    withdrawn_at: datetime | None = None

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
