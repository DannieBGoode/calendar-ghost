"""Provider method writes prove current ownership and retain a usable sign-in method."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.provider_sign_in_ports import (
    LastSignInMethod,
    LinkOwner,
    ProviderAvailability,
)
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.credentials import SqliteCredentialChanges
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.provider_methods import SqliteProviderMethods
from calendar_sync.infrastructure.persistence.provider_sign_in_settings import (
    SqliteProviderSignInSettings,
)
from calendar_sync.infrastructure.persistence.registration import SqlitePasswordResetLinks
from calendar_sync.infrastructure.persistence.users import SqliteSessions, SqliteUserDirectory
from calendar_sync.infrastructure.security import token_hash
from tests.adapters.test_users_store import FIRST, NOW, SECOND, MovableClock, SequentialIds

AVAILABLE = (ProviderAvailability("alpha", True, None), ProviderAvailability("beta", True, None))


@dataclass
class MethodsHarness:
    path: Path
    clock: MovableClock
    methods: SqliteProviderMethods
    settings: SqliteProviderSignInSettings
    credentials: SqliteCredentialChanges

    def owner(self, session: str = "owner-session") -> LinkOwner:
        expected = self.credentials.current(SECOND.id)
        assert expected is not None
        return LinkOwner(SECOND.id, token_hash(session), expected.revision)


@pytest.fixture
def methods(tmp_path: Path) -> MethodsHarness:
    path = tmp_path / "methods.db"
    initialize_database(path)
    clock = MovableClock(NOW)
    users = SqliteUserDirectory(path)
    users.add(FIRST, "administrator-hash")
    users.add(SECOND, "temporary-hash")
    with transaction(path) as connection:
        connection.execute("UPDATE users SET password_hash = NULL WHERE id = ?", (SECOND.id.value,))
        for token, user in [
            ("owner-session", SECOND),
            ("other-session", SECOND),
            ("foreign", FIRST),
        ]:
            connection.execute(
                "INSERT INTO user_sessions(token_hash,user_id,created_at,expires_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    token_hash(token),
                    user.id.value,
                    NOW.isoformat(),
                    (NOW + timedelta(days=1)).isoformat(),
                ),
            )
        for provider in ("alpha", "beta"):
            connection.execute(
                "INSERT INTO provider_identities VALUES (?, ?, ?, ?, ?, ?)",
                (
                    provider,
                    SECOND.id.value,
                    provider,
                    f"https://{provider}.test",
                    "subject",
                    NOW.isoformat(),
                ),
            )
    settings = SqliteProviderSignInSettings(path, AVAILABLE)
    settings.set_enabled(FIRST.id, "alpha", True)
    settings.set_enabled(FIRST.id, "beta", True)
    return MethodsHarness(
        path,
        clock,
        SqliteProviderMethods(path, clock, AVAILABLE),
        settings,
        SqliteCredentialChanges(path, clock),
    )


@pytest.mark.parametrize("session", ["missing", "foreign", "expired"])
def test_set_first_password_requires_live_owner(methods: MethodsHarness, session: str) -> None:
    if session == "expired":
        methods.clock.moment += timedelta(days=1)
        session = "owner-session"
    expected = methods.credentials.current(SECOND.id)
    assert expected is not None
    assert not methods.methods.set_password(methods.owner(session), expected, "new-hash")
    assert methods.credentials.current(SECOND.id) == expected


@pytest.mark.parametrize("operation", ["password", "unlink"])
def test_method_change_keeps_owner_and_invalidates_stale_work(
    methods: MethodsHarness, operation: str
) -> None:
    links = SqlitePasswordResetLinks(methods.path, SequentialIds(), methods.clock)
    proof = links.issue(SECOND.id, FIRST.id, NOW)
    expected = methods.credentials.current(SECOND.id)
    assert expected is not None
    assert expected.password_hash is None
    with transaction(methods.path) as connection:
        connection.execute(
            "INSERT INTO email_change_proofs(id, user_id, proposed_email, credential_revision, "
            "created_at, expires_at) VALUES ('email-proof', ?, 'next@example.test', 0, ?, ?)",
            (SECOND.id.value, NOW.isoformat(), (NOW + timedelta(days=1)).isoformat()),
        )
    if operation == "password":
        assert methods.methods.set_password(methods.owner(), expected, "new-hash")
    else:
        assert methods.methods.unlink(methods.owner(), "alpha")
    current = methods.credentials.current(SECOND.id)
    assert current is not None
    assert current.password_hash == ("new-hash" if operation == "password" else None)
    assert current.revision == 1
    sessions = SqliteSessions(methods.path, methods.clock)
    assert sessions.user_of("owner-session") == SECOND.id
    assert sessions.user_of("other-session") is None
    assert sessions.user_of("foreign") == FIRST.id
    assert links.owner(proof.token, NOW) is None
    assert not methods.methods.set_password(methods.owner(), expected, "stale")
    with transaction(methods.path) as connection:
        assert connection.execute("SELECT revoked_at FROM email_change_proofs").fetchone()[0]


@pytest.mark.parametrize("change", ["revision", "disabled", "different-owner", "password-present"])
def test_first_password_refuses_stale_or_mismatched_snapshot(
    methods: MethodsHarness, change: str
) -> None:
    expected = methods.credentials.current(SECOND.id)
    assert expected is not None
    owner = methods.owner()
    if change == "different-owner":
        expected = replace(expected, user_id=FIRST.id)
    else:
        with transaction(methods.path) as connection:
            if change == "revision":
                connection.execute(
                    "UPDATE users SET credential_revision = 1 WHERE id = ?", (SECOND.id.value,)
                )
            elif change == "disabled":
                connection.execute(
                    "UPDATE users SET state = 'disabled' WHERE id = ?", (SECOND.id.value,)
                )
            else:
                connection.execute(
                    "UPDATE users SET password_hash = 'existing' WHERE id = ?", (SECOND.id.value,)
                )
    assert not methods.methods.set_password(owner, expected, "forbidden")


def test_concurrent_last_method_removal(methods: MethodsHarness) -> None:
    owner = methods.owner()
    barrier = Barrier(2)

    def unlink(identity: str) -> bool:
        barrier.wait(timeout=2)
        return methods.methods.unlink(owner, identity)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(unlink, ("alpha", "beta")))
    assert sorted(results) == [False, True]
    shown = methods.methods.show(SECOND.id)
    assert not shown.has_password
    assert len(shown.identities) == 1
    assert not methods.methods.unlink(methods.owner(), shown.identities[0].id)


@pytest.mark.parametrize("session", ["missing", "foreign", "expired"])
def test_unlink_requires_live_owner(methods: MethodsHarness, session: str) -> None:
    if session == "expired":
        methods.clock.moment += timedelta(days=1)
        session = "owner-session"
    assert not methods.methods.unlink(methods.owner(session), "alpha")
    assert len(methods.methods.show(SECOND.id).identities) == 2


def test_unlink_cannot_reach_another_users_identity(methods: MethodsHarness) -> None:
    owner = LinkOwner(FIRST.id, token_hash("foreign"), 0)
    assert not methods.methods.unlink(owner, "alpha")


def test_unavailable_or_disabled_provider_is_not_a_remaining_method(
    methods: MethodsHarness,
) -> None:
    methods.settings.set_enabled(FIRST.id, "beta", False)
    assert not methods.methods.unlink(methods.owner(), "alpha")
    methods.settings.set_enabled(FIRST.id, "beta", True)
    unavailable = SqliteProviderMethods(
        methods.path, methods.clock, (ProviderAvailability("beta", False, "missing"),)
    )
    assert not unavailable.unlink(methods.owner(), "alpha")


def test_disable_provider_cannot_strand_user(methods: MethodsHarness) -> None:
    methods.settings.set_enabled(FIRST.id, "alpha", False)
    with pytest.raises(LastSignInMethod):
        methods.settings.set_enabled(FIRST.id, "beta", False)
    assert [setting.enabled for setting in methods.settings.list()] == [False, True]
    assert len(methods.methods.show(SECOND.id).identities) == 2


def test_disable_and_unlink_serialize(methods: MethodsHarness) -> None:
    barrier = Barrier(2)
    owner = methods.owner()

    def disable() -> bool:
        barrier.wait(timeout=2)
        try:
            methods.settings.set_enabled(FIRST.id, "beta", False)
        except LastSignInMethod:
            return False
        return True

    def unlink() -> bool:
        barrier.wait(timeout=2)
        return methods.methods.unlink(owner, "alpha")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(disable), pool.submit(unlink)
        assert sorted([first.result(), second.result()]) == [False, True]


@pytest.mark.parametrize("actor", ["ordinary", "disabled", "missing"])
def test_settings_require_active_administrator(methods: MethodsHarness, actor: str) -> None:
    from calendar_sync.domain.access import UserId

    user_id = SECOND.id if actor == "ordinary" else FIRST.id
    with transaction(methods.path) as connection:
        if actor == "disabled":
            connection.execute(
                "UPDATE users SET state = 'disabled' WHERE id = ?", (FIRST.id.value,)
            )
        if actor == "missing":
            user_id = UserId("missing")
    with pytest.raises(AdministratorRequired):
        methods.settings.set_enabled(user_id, "alpha", False)


def test_reset_sets_first_password(methods: MethodsHarness) -> None:
    links = SqlitePasswordResetLinks(methods.path, SequentialIds(), methods.clock)
    proof = links.issue(SECOND.id, FIRST.id, NOW)
    assert links.reset(proof.token, "reset-hash") == SECOND.id
    assert methods.methods.show(SECOND.id).has_password
    sessions = SqliteSessions(methods.path, methods.clock)
    assert sessions.user_of("owner-session") is None
    assert sessions.user_of("other-session") is None
    assert sessions.user_of("foreign") == FIRST.id


def test_password_allows_last_provider_removal(methods: MethodsHarness) -> None:
    expected = methods.credentials.current(SECOND.id)
    assert expected is not None
    assert methods.methods.set_password(methods.owner(), expected, "password")
    assert methods.methods.unlink(methods.owner(), "alpha")
    assert methods.methods.unlink(methods.owner(), "beta")
    assert methods.methods.show(SECOND.id).identities == ()
    methods.settings.set_enabled(FIRST.id, "alpha", False)
    methods.settings.set_enabled(FIRST.id, "beta", False)


@pytest.mark.parametrize("change", ["disabled", "revision"])
def test_unlink_rechecks_active_revision(methods: MethodsHarness, change: str) -> None:
    owner = methods.owner()
    with transaction(methods.path) as connection:
        if change == "disabled":
            connection.execute(
                "UPDATE users SET state = 'disabled' WHERE id = ?", (SECOND.id.value,)
            )
        else:
            connection.execute(
                "UPDATE users SET credential_revision = 1 WHERE id = ?", (SECOND.id.value,)
            )
    assert not methods.methods.unlink(owner, "alpha")
    assert len(methods.methods.show(SECOND.id).identities) == 2


def test_settings_start_disabled_and_cannot_enable_unavailable(methods: MethodsHarness) -> None:
    from calendar_sync.domain.errors import DomainValidationError

    settings = SqliteProviderSignInSettings(
        methods.path, (ProviderAvailability("missing", False, "unconfigured"),)
    )
    assert not settings.list()[0].enabled
    assert not settings.list()[0].available
    with pytest.raises(DomainValidationError):
        settings.set_enabled(FIRST.id, "missing", True)
    with pytest.raises(DomainValidationError):
        settings.set_enabled(FIRST.id, "unknown", True)


def test_disabled_user_does_not_block_provider_disable(methods: MethodsHarness) -> None:
    with transaction(methods.path) as connection:
        connection.execute("UPDATE users SET state = 'disabled' WHERE id = ?", (SECOND.id.value,))
    methods.settings.set_enabled(FIRST.id, "alpha", False)
    methods.settings.set_enabled(FIRST.id, "beta", False)


@pytest.mark.parametrize("operation", ["password", "unlink"])
def test_method_failure_rolls_back_all_mutations(methods: MethodsHarness, operation: str) -> None:
    import sqlite3

    expected = methods.credentials.current(SECOND.id)
    assert expected is not None
    owner = methods.owner()
    with transaction(methods.path) as connection:
        connection.execute(
            "CREATE TRIGGER refuse_session_delete BEFORE DELETE ON user_sessions "
            "BEGIN SELECT RAISE(ABORT, 'synthetic-failure'); END"
        )
    before = methods.methods.show(SECOND.id)

    def write() -> bool:
        if operation == "password":
            return methods.methods.set_password(owner, expected, "new")
        return methods.methods.unlink(owner, "alpha")

    with pytest.raises(sqlite3.IntegrityError):
        write()
    assert methods.methods.show(SECOND.id) == before
    assert methods.credentials.current(SECOND.id) == expected
    assert SqliteSessions(methods.path, methods.clock).user_of("other-session") == SECOND.id


def test_disable_does_not_count_unavailable_remaining_provider(methods: MethodsHarness) -> None:
    settings = SqliteProviderSignInSettings(
        methods.path,
        (
            ProviderAvailability("alpha", True, None),
            ProviderAvailability("beta", False, "unconfigured"),
        ),
    )
    with pytest.raises(LastSignInMethod):
        settings.set_enabled(FIRST.id, "alpha", False)
    assert settings.list()[0].enabled


def test_disable_checks_every_affected_active_user(methods: MethodsHarness) -> None:
    with transaction(methods.path) as connection:
        connection.execute("UPDATE users SET password_hash = NULL WHERE id = ?", (FIRST.id.value,))
        connection.execute(
            "INSERT INTO provider_identities VALUES ('administrator', ?, 'alpha', "
            "'https://alpha.test', 'administrator', ?)",
            (FIRST.id.value, NOW.isoformat()),
        )
    with pytest.raises(LastSignInMethod):
        methods.settings.set_enabled(FIRST.id, "alpha", False)
    assert methods.settings.list()[0].enabled


@pytest.mark.parametrize("kind", ["administrator", "email"])
def test_password_recovery_removes_all_owned_provider_methods_only(
    methods: MethodsHarness, kind: str
) -> None:
    from tests.users import add_account

    add_account(methods.path, "preserved-calendar", SECOND.id)
    with transaction(methods.path) as connection:
        connection.execute(
            "INSERT INTO provider_identities VALUES ('foreign-method',?,'alpha','https://alpha.test','foreign-subject',?)",
            (FIRST.id.value, NOW.isoformat()),
        )
    links = SqlitePasswordResetLinks(methods.path, SequentialIds(), methods.clock)
    if kind == "administrator":
        proof = links.issue(SECOND.id, FIRST.id, NOW)
    else:
        prepared = links.issue_for_email(SECOND.email or "")
        assert prepared is not None
        proof = prepared.link
    assert links.reset(proof.token, "replacement-hash") == SECOND.id
    assert methods.methods.show(SECOND.id).identities == ()
    assert len(methods.methods.show(FIRST.id).identities) == 1
    with transaction(methods.path) as connection:
        assert (
            connection.execute("SELECT id FROM connected_accounts").fetchone()[0]
            == "preserved-calendar"
        )
    assert links.reset(proof.token, "replayed") is None


@pytest.mark.parametrize("verified", [False, True])
@pytest.mark.parametrize("kind", ["administrator", "email", "deleted-administrator"])
def test_reset_preserves_email_assurance_without_inferring_it_from_creator(
    methods: MethodsHarness, verified: bool, kind: str
) -> None:
    with transaction(methods.path) as connection:
        connection.execute(
            "UPDATE users SET email_verified=? WHERE id=?", (int(verified), SECOND.id.value)
        )
    links = SqlitePasswordResetLinks(methods.path, SequentialIds(), methods.clock)
    if kind == "email":
        prepared = links.issue_for_email(SECOND.email or "")
        assert prepared is not None
        proof = prepared.link
    else:
        proof = links.issue(SECOND.id, FIRST.id, NOW)
    if kind == "deleted-administrator":
        with transaction(methods.path) as connection:
            connection.execute(
                "UPDATE users SET role='installation_administrator' WHERE id=?", (SECOND.id.value,)
            )
        SqliteUserDirectory(methods.path).delete(FIRST.id)
        with transaction(methods.path) as connection:
            assert (
                connection.execute("SELECT created_by FROM password_reset_links").fetchone()[0]
                is None
            )
    assert links.reset(proof.token, "new-hash") == SECOND.id
    with transaction(methods.path) as connection:
        assert (
            bool(
                connection.execute(
                    "SELECT email_verified FROM users WHERE id=?", (SECOND.id.value,)
                ).fetchone()[0]
            )
            is verified
        )
    assert methods.methods.show(SECOND.id).identities == ()


def test_refused_reset_and_failed_provider_removal_preserve_all_credentials(
    methods: MethodsHarness,
) -> None:
    from calendar_sync.application.identity.errors import ResetStorageUnavailable

    links = SqlitePasswordResetLinks(methods.path, SequentialIds(), methods.clock)
    proof = links.issue(SECOND.id, FIRST.id, NOW)
    assert links.reset("invalid-proof", "forbidden") is None
    assert len(methods.methods.show(SECOND.id).identities) == 2
    with transaction(methods.path) as connection:
        connection.execute(
            "CREATE TRIGGER refuse_identity_removal BEFORE DELETE ON provider_identities "
            "BEGIN SELECT RAISE(ABORT,'synthetic'); END"
        )
    with pytest.raises(ResetStorageUnavailable):
        links.reset(proof.token, "forbidden")
    assert not methods.methods.show(SECOND.id).has_password
    assert len(methods.methods.show(SECOND.id).identities) == 2
    assert links.owner(proof.token, NOW) == SECOND.id
    assert SqliteSessions(methods.path, methods.clock).user_of("owner-session") == SECOND.id
