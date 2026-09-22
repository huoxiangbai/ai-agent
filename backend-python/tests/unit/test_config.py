from pydantic import SecretStr

from reactor_backend.config import Settings


def test_database_url_is_built_and_credentials_are_escaped() -> None:
    settings = Settings(
        mysql_host="db.internal",
        mysql_database="reactor db",
        mysql_user="user@example.com",
        mysql_password=SecretStr("p@ss/word"),
    )

    assert settings.sqlalchemy_database_url == (
        "mysql+asyncmy://user%40example.com:p%40ss%2Fword@db.internal:3306/"
        "reactor+db?charset=utf8mb4"
    )
    assert "p@ss/word" not in repr(settings)


def test_explicit_database_url_wins() -> None:
    settings = Settings(database_url=SecretStr("mysql+asyncmy://custom/db"))
    assert settings.sqlalchemy_database_url == "mysql+asyncmy://custom/db"
