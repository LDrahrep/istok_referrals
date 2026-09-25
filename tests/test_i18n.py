from string import Formatter

from referrals.i18n import LANGS, en, ru, t


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(template) if name}


def test_languages_have_same_keys_and_placeholders():
    assert set(ru.TEXTS) == set(en.TEXTS)
    for key in ru.TEXTS:
        assert placeholders(ru.TEXTS[key]) == placeholders(en.TEXTS[key]), key


def test_t_formats_and_falls_back_to_russian():
    assert LANGS == ("ru", "en")
    assert t("en", "welcome", name="Ivan") == en.TEXTS["welcome"].format(name="Ivan")
    assert t(None, "menu") == ru.TEXTS["menu"]
    assert t("de", "menu") == ru.TEXTS["menu"]
