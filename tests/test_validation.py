import pytest

from referrals.validation import (
    clean_name,
    extract_emp_id,
    name_matches,
    normalize_email,
    normalize_phone,
    parse_emp_id,
)

EMP = "EMP-7b682ed0-2485-44fe-a727-d40f8d7e0f42"


@pytest.mark.parametrize("raw,expected", [
    ("Ivan", "Ivan"),
    ("  Иван  ", "Иван"),
    ("Mary-Jane", "Mary-Jane"),
    ("O'Brien", "O'Brien"),
    ("Abdukakhor   Abdugaforov", "Abdukakhor Abdugaforov"),
    ("Ғайратҷон", "Ғайратҷон"),
    ("Oʻgʻiloy", "Oʻgʻiloy"),
])
def test_clean_name_accepts(raw, expected):
    assert clean_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "Ivan2", "-Ivan", "Ivan-", "Iv--an", "Ivan!", "李雷", "a" * 51])
def test_clean_name_rejects(raw):
    assert clean_name(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("(650) 253-0000", "+16502530000"),
    ("650.253.0000", "+16502530000"),
    ("+1 650 253 0000", "+16502530000"),
    ("+7 912 345-67-89", "+79123456789"),
])
def test_normalize_phone_accepts(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "12345", "phone", "+1 000 000 0000", "650-253-000"])
def test_normalize_phone_rejects(raw):
    assert normalize_phone(raw) is None


def test_normalize_email():
    assert normalize_email(" Ivan.Petrov@Gmail.com ") == "ivan.petrov@gmail.com"


@pytest.mark.parametrize("raw", ["", "ivan", "ivan@", "ivan@gmail", "iv an@gmail.com", "@gmail.com"])
def test_normalize_email_rejects(raw):
    assert normalize_email(raw) is None


def test_extract_emp_id_finds_id_in_text():
    assert extract_emp_id(f"мой id {EMP.upper().replace('EMP-', 'emp-')} спасибо") == EMP
    assert extract_emp_id(f"  {EMP}\n") == EMP
    assert extract_emp_id("EMP-123") is None
    assert extract_emp_id("") is None


def test_parse_emp_id_requires_exact_value():
    assert parse_emp_id(f"  {EMP.upper()} ") == EMP
    assert parse_emp_id(f"id {EMP}") is None


@pytest.mark.parametrize("query,name,expected", [
    ("ivan petrov", "Ivan Petrov", True),
    ("Petrov  Ivan", "Ivan Petrov", True),
    ("Petrov", "Ivan Petrov", True),
    ("Ivan Sidorov", "Ivan Petrov", False),
    ("", "Ivan Petrov", False),
])
def test_name_matches(query, name, expected):
    assert name_matches(query, name) is expected
