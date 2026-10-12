"""The installation's settings, read from the environment the README and deployment guide list."""

from datetime import date
from pathlib import Path

import pytest

from calendar_sync.bootstrap.config import Settings

MICROSOFT_VARIABLES = (
    "CALENDAR_SYNC_MICROSOFT_CLIENT_ID",
    "CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET",
    "CALENDAR_SYNC_MICROSOFT_REDIRECT_URI",
    "CALENDAR_SYNC_MICROSOFT_TENANT",
    "CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET_EXPIRES",
)


def test_microsoft_is_unconfigured_by_default_and_signs_in_any_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in MICROSOFT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    settings = Settings.from_environment()

    assert (settings.microsoft_client_id, settings.microsoft_client_secret) == ("", "")
    assert settings.microsoft_redirect_uri == (
        "http://localhost:8000/api/v1/oauth/microsoft/callback"
    )
    # "common" signs in personal and work or school accounts alike.
    assert settings.microsoft_tenant == "common"
    assert Settings(Path("unused.db")).microsoft_tenant == "common"


def test_microsoft_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CALENDAR_SYNC_MICROSOFT_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setenv(
        "CALENDAR_SYNC_MICROSOFT_REDIRECT_URI",
        "https://ghost.example.test/api/v1/oauth/microsoft/callback",
    )
    monkeypatch.setenv("CALENDAR_SYNC_MICROSOFT_TENANT", "organizations")

    settings = Settings.from_environment()

    assert settings.microsoft_client_id == "synthetic-client"
    assert settings.microsoft_client_secret == "synthetic-secret"
    assert settings.microsoft_redirect_uri == (
        "https://ghost.example.test/api/v1/oauth/microsoft/callback"
    )
    assert settings.microsoft_tenant == "organizations"


@pytest.mark.parametrize(
    "document", ["README.md", "docker-compose.yml", "docs/deployment.md"], ids=str
)
def test_every_microsoft_setting_is_documented_where_operators_look(document: str) -> None:
    text = (Path(__file__).resolve().parents[2] / document).read_text()

    assert [variable for variable in MICROSOFT_VARIABLES if variable not in text] == []


def test_the_microsoft_client_secrets_expiry_is_an_optional_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET_EXPIRES", raising=False)
    assert Settings.from_environment().microsoft_client_secret_expires is None

    monkeypatch.setenv("CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET_EXPIRES", " ")
    assert Settings.from_environment().microsoft_client_secret_expires is None

    monkeypatch.setenv("CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET_EXPIRES", "2027-04-12")
    assert Settings.from_environment().microsoft_client_secret_expires == date(2027, 4, 12)


def test_an_unreadable_client_secret_expiry_names_its_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET_EXPIRES", "12/04/2027")

    with pytest.raises(ValueError, match="CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET_EXPIRES"):
        Settings.from_environment()
