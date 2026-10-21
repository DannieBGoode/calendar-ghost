"""Ordinary sign-in atomically cancels browser work retained during provider exchange."""

from pathlib import Path

import pytest

from calendar_sync.application.identity.errors import SignInStorageUnavailable
from calendar_sync.application.identity.ports import SignInBrowser
from calendar_sync.application.identity.provider_sign_in_ports import (
    BeginIntent,
    BrowserProof,
    ProviderCallback,
)
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.users import SqliteSessions
from calendar_sync.infrastructure.security import token_hash
from tests.adapters.test_provider_flows import database as database
from tests.adapters.test_provider_flows import flows
from tests.fakes.oidc import FixedClock


def test_password_session_cancels_claimed_callback_atomically(database: Path) -> None:
    service = flows(database)
    browser = BrowserProof("b" * 43)
    service.begin(BeginIntent("google", browser), "s" * 43)
    assert service.consume(ProviderCallback("google", "s" * 43, "code", browser))
    sessions = SqliteSessions(database, FixedClock())
    result = sessions.start(
        UserId("one"), "hash", "one@example.test", 0, SignInBrowser("two", browser.value)
    )
    assert result
    assert sessions.user_of("two") is None
    with transaction(database) as connection:
        assert connection.execute("SELECT count(*) FROM provider_flows").fetchone()[0] == 0
        assert connection.execute(
            "SELECT browser_hash FROM user_sessions WHERE token_hash=?", (token_hash(result.token),)
        ).fetchone()[0] == token_hash(browser.value)


def test_failed_credentials_leave_browser_work_and_previous_session(database: Path) -> None:
    service = flows(database)
    browser = BrowserProof("b" * 43)
    service.begin(BeginIntent("google", browser), "s" * 43)
    sessions = SqliteSessions(database, FixedClock())
    assert (
        sessions.start(
            UserId("one"), "wrong", "one@example.test", 0, SignInBrowser("two", browser.value)
        )
        is None
    )
    assert sessions.user_of("two") == UserId("two")
    assert service.consume(ProviderCallback("google", "s" * 43, "code", browser))


def test_cancellation_failure_rolls_back_replacement(database: Path) -> None:
    service = flows(database)
    browser = BrowserProof("b" * 43)
    service.begin(BeginIntent("google", browser), "s" * 43)
    with transaction(database) as connection:
        connection.execute(
            "CREATE TRIGGER reject_cancel BEFORE DELETE ON provider_flows "
            "BEGIN SELECT RAISE(ABORT, 'synthetic'); END"
        )
    sessions = SqliteSessions(database, FixedClock())
    with pytest.raises(SignInStorageUnavailable):
        sessions.start(
            UserId("one"), "hash", "one@example.test", 0, SignInBrowser("two", browser.value)
        )
    assert sessions.user_of("two") == UserId("two")
    with transaction(database) as connection:
        assert connection.execute("SELECT count(*) FROM user_sessions").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM provider_flows").fetchone()[0] == 1
