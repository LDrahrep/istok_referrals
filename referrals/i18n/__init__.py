"""Тексты бота на русском и английском."""
from referrals.i18n import en, ru

LANGS = ("ru", "en")
_TEXTS = {"ru": ru.TEXTS, "en": en.TEXTS}


def t(lang: str | None, key: str, **kwargs) -> str:
    template = _TEXTS.get(lang or "ru", ru.TEXTS)[key]
    return template.format(**kwargs) if kwargs else template
