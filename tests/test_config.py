import pytest

from referrals.config import ConfigError, load_config

BASE = {
    "TELEGRAM_BOT_TOKEN": "123:abc",
    "DATABASE_URL": "postgresql://user:pw@host/db",
    "TABELI_URL": "http://1.2.3.4/",
    "GOOGLE_CREDENTIALS": '{"type": "service_account"}',
    "SPREADSHEET_ID": "sheet-id",
    "ADMIN_CHAT_ID": "-1001",
    "ADMIN_USER_IDS": "11, 22",
}


def test_load_config_parses_values():
    cfg = load_config(BASE)
    assert cfg.telegram_bot_token == "123:abc"
    assert cfg.tabeli_url == "http://1.2.3.4"
    assert cfg.google_credentials == {"type": "service_account"}
    assert cfg.admin_chat_id == -1001
    assert cfg.admin_user_ids == frozenset({11, 22})
    assert cfg.sheet_name == "Заявки"


def test_custom_sheet_name():
    assert load_config({**BASE, "SHEET_NAME": "Test"}).sheet_name == "Test"


@pytest.mark.parametrize("name", sorted(BASE))
def test_missing_variable_is_reported(name):
    env = dict(BASE)
    del env[name]
    with pytest.raises(ConfigError, match=name):
        load_config(env)


def test_bad_admin_ids():
    with pytest.raises(ConfigError, match="ADMIN_USER_IDS"):
        load_config({**BASE, "ADMIN_USER_IDS": "11,abc"})


def test_bad_admin_chat():
    with pytest.raises(ConfigError, match="ADMIN_CHAT_ID"):
        load_config({**BASE, "ADMIN_CHAT_ID": "chat"})


def test_bad_credentials_json():
    with pytest.raises(ConfigError, match="GOOGLE_CREDENTIALS"):
        load_config({**BASE, "GOOGLE_CREDENTIALS": "{not json"})
