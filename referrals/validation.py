"""Проверка и нормализация ввода: имена, телефоны, почта, ID сотрудника."""
from __future__ import annotations

import re
import unicodedata

import phonenumbers

NAME_MAX_LEN = 50
_NAME_SEPARATORS = frozenset(" -'’ʻ")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_EMP_RE = re.compile(rf"EMP-({_UUID})", re.IGNORECASE)


def _is_name_letter(ch: str) -> bool:
    return ch.isalpha() and unicodedata.name(ch, "").startswith(("LATIN", "CYRILLIC"))


def clean_name(raw: str) -> str | None:
    name = " ".join(raw.split())
    if not 1 <= len(name) <= NAME_MAX_LEN:
        return None
    if not (_is_name_letter(name[0]) and _is_name_letter(name[-1])):
        return None
    previous_was_separator = False
    for ch in name:
        if ch in _NAME_SEPARATORS:
            if previous_was_separator:
                return None
            previous_was_separator = True
        elif _is_name_letter(ch):
            previous_was_separator = False
        else:
            return None
    return name


def normalize_phone(raw: str) -> str | None:
    try:
        number = phonenumbers.parse(raw, "US")
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalize_email(raw: str) -> str | None:
    email = raw.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return None
    return email


def extract_emp_id(text: str) -> str | None:
    match = _EMP_RE.search(text)
    return f"EMP-{match.group(1).lower()}" if match else None


def parse_emp_id(text: str) -> str | None:
    match = _EMP_RE.fullmatch(text.strip())
    return f"EMP-{match.group(1).lower()}" if match else None


def _name_tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[\s\-]+", text.casefold()) if token]


def name_matches(query: str, full_name: str) -> bool:
    wanted = _name_tokens(query)
    have = set(_name_tokens(full_name))
    return bool(wanted) and all(token in have for token in wanted)
