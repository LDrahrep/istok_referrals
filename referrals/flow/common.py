"""Общие элементы диалога: меню, выбор языка, навигация."""
from __future__ import annotations

from referrals.flow.io import Buttons, Io
from referrals.i18n import t

LANGUAGE_BUTTONS: Buttons = [[("Русский", "lang:ru"), ("English", "lang:en")]]


def menu_buttons(lang: str | None) -> Buttons:
    return [[(t(lang, "btn_refer"), "menu:refer")],
            [(t(lang, "btn_mine"), "menu:mine")],
            [(t(lang, "btn_language"), "menu:language")]]


def nav_row(lang: str | None) -> list[tuple[str, str]]:
    return [(t(lang, "btn_back"), "nav:back"), (t(lang, "btn_cancel"), "nav:cancel")]


async def show_menu(io: Io, lang: str | None) -> None:
    await io.reply(t(lang, "menu"), menu_buttons(lang))


async def prompt_language(io: Io) -> None:
    await io.reply(t(None, "choose_language"), LANGUAGE_BUTTONS)
