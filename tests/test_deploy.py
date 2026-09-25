import importlib.util


def test_timezone_data_is_bundled():
    # В образе Railway может не оказаться системной базы часовых поясов — тогда ZoneInfo("America/Chicago")
    # падает и вместе с ним вся синхронизация таблицы. Пакет tzdata закрывает этот случай.
    assert importlib.util.find_spec("tzdata") is not None
