"""Фабрики тестовых данных без обращения к БД."""
from datetime import datetime, timezone
from uuid import uuid4

from referrals.models import PhotoBlob, Referral, ReferralDraft

EMP_A = "EMP-00000000-0000-4000-8000-00000000000a"
EMP_B = "EMP-00000000-0000-4000-8000-00000000000b"
EMP_C = "EMP-00000000-0000-4000-8000-00000000000c"


def make_draft(**overrides) -> ReferralDraft:
    values = dict(
        submission_key=uuid4(), first_name="Aziz", last_name="Karimov",
        phone="+16502530000", email="aziz@example.com", worked_before=False,
        referrer_tg_user_id=111, referrer_emplid=EMP_A, referrer_name="Ivan Petrov",
        photo_file_id="file-1", photo_kind="photo",
    )
    values.update(overrides)
    return ReferralDraft(**values)


def make_photo(content: bytes = b"\xff\xd8photo-bytes", mime: str = "image/jpeg") -> PhotoBlob:
    return PhotoBlob.from_bytes(content, mime)


def make_referral(id: int = 1, **overrides) -> Referral:
    values = dict(
        id=id, first_name="Aziz", last_name="Karimov", phone="+16502530000",
        email="aziz@example.com", worked_before=True, referrer_tg_user_id=111,
        referrer_emplid=EMP_A, referrer_name="Ivan Petrov", photo_file_id="file-1",
        photo_kind="photo", photo_url=None, hr_data={},
        created_at=datetime(2026, 9, 25, 19, 3, tzinfo=timezone.utc),
    )
    values.update(overrides)
    return Referral(**values)
