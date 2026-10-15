"""A new calendar account is refused at its User's Plan's account limit, after the provider's
consent; Reauthorization of an account the User has is never refused (ADR 0038)."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.sync.errors import AccountLimitReached, AuthorizationFailed
from calendar_sync.application.sync.ports import Allowances, AuthorizedAccount
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Adapters, Container, build_adapters, compose
from calendar_sync.domain.access import Role, UserId
from calendar_sync.domain.accounts import ConnectedAccount, ConnectedAccountState, ProviderKind
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.domain.plans import LimitedResource, PlanLimitReached
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.google.oauth import GoogleOAuthService
from calendar_sync.infrastructure.oauth import connect_account
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.sqlite import SqliteUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.helpers import endpoint
from tests.identity_fakes import BrokenAllowances
from tests.plans import FAMILY, FREE, plans_on
from tests.users import OTHER_USER, add_user, administrator, limited_user, session_for

CIPHER = CredentialCipher(CredentialCipher.generate_key())


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "calendar-sync.db"
    initialize_database(path)
    return path


def _store(database: Path, allowances: Allowances | None) -> SqliteConnectedAccountStore:
    return SqliteConnectedAccountStore(database, CIPHER, allowances=allowances)


def _connect(store: SqliteConnectedAccountStore, user: UserId, email: str) -> ConnectedAccount:
    """Save an account as a provider's callback does once its consent is given."""
    return store.for_user(user).save("Synthetic", email, "{}", provider=ProviderKind.GOOGLE)


def _emails(store: SqliteConnectedAccountStore, user: UserId) -> list[str]:
    return [account.email for account in store.for_user(user).list()]


def _on_free(database: Path) -> tuple[SqliteConnectedAccountStore, UserId]:
    """A member on the Default Plan, Free, which allows one calendar account."""
    plans = SqlitePlans(database)
    plans_on(plans, FREE)
    return _store(database, plans), limited_user(database)


def test_a_new_address_at_the_limit_is_refused_and_nothing_is_stored(database: Path) -> None:
    store, member = _on_free(database)
    _connect(store, member, "first@example.test")

    with pytest.raises(PlanLimitReached) as refused:
        _connect(store, member, "second@example.test")

    assert (refused.value.resource, refused.value.limit) == (
        LimitedResource.CONNECTED_ACCOUNTS,
        1,
    )
    assert _emails(store, member) == ["first@example.test"]


def test_the_oauth_flow_reports_the_limit_it_met(database: Path) -> None:
    store, member = _on_free(database)
    _connect(store, member, "first@example.test")

    with pytest.raises(AccountLimitReached) as refused:
        connect_account(
            store,
            member,
            display_name="Second",
            email="second@example.test",
            credentials="{}",
            provider=ProviderKind.GOOGLE,
        )

    assert refused.value.limit == 1
    # An AuthorizationFailed, so any caller that knows no better still connects nothing.
    assert isinstance(refused.value, AuthorizationFailed)
    assert _emails(store, member) == ["first@example.test"]


def test_disconnected_accounts_count_so_disconnecting_one_makes_no_room(database: Path) -> None:
    store, member = _on_free(database)
    first = _connect(store, member, "first@example.test")
    store.for_user(member).disconnect(first.id)

    with pytest.raises(PlanLimitReached):
        _connect(store, member, "second@example.test")
    # Connecting the Disconnected Account again is Reauthorization, which is never refused.
    again = _connect(store, member, "first@example.test")

    assert (again.id, again.state) == (first.id, ConnectedAccountState.CONNECTED)
    assert _emails(store, member) == ["first@example.test"]


def test_reauthorization_over_the_limit_succeeds_without_reading_plans(database: Path) -> None:
    plans = SqlitePlans(database)
    member = limited_user(database)
    # Both connected while Plans were off; Free then allows only one.
    work = _connect(_store(database, plans), member, "work@example.test")
    _connect(_store(database, plans), member, "home@example.test")
    plans_on(plans, FREE)
    with SqliteUnitOfWorkFactory(database, SystemClock()).for_user(member)() as uow:
        uow.accounts.lapse(work.id, attempted_at=datetime.now(UTC))
        uow.commit()

    # Every read of Plans raises, so a Reauthorization that read them would fail.
    renewed = _connect(_store(database, BrokenAllowances()), member, "work@example.test")

    assert renewed.id == work.id
    assert (renewed.state, renewed.authorization_lapsed_at) == (
        ConnectedAccountState.CONNECTED,
        None,
    )
    assert _emails(_store(database, plans), member) == ["home@example.test", "work@example.test"]


def test_a_failing_plans_read_refuses_a_new_address(database: Path) -> None:
    store = _store(database, BrokenAllowances())
    member = limited_user(database)

    # Fail closed: like any database error, never an account admitted past the limit. Through
    # the OAuth callback this answers 500, and connecting again works once Plans can be read.
    with pytest.raises(RuntimeError, match="database is locked"):
        connect_account(
            store,
            member,
            display_name="New",
            email="new@example.test",
            credentials="{}",
            provider=ProviderKind.GOOGLE,
        )

    assert _emails(store, member) == []


def test_administrators_and_plans_off_are_never_limited(database: Path) -> None:
    plans = SqlitePlans(database)
    store = _store(database, plans)
    member = limited_user(database)
    for number in range(3):
        _connect(store, member, f"member-{number}@example.test")
    plans_on(plans, FREE)
    owner = add_user(database)

    for number in range(3):
        _connect(store, owner, f"owner-{number}@example.test")

    assert len(_emails(store, member)) == 3
    assert len(_emails(store, owner)) == 3


def test_an_administrator_demoted_over_the_limit_keeps_every_account_but_adds_no_new_one(
    database: Path,
) -> None:
    add_user(database)  # Another administrator, so the demotion leaves one.
    owner = add_user(database, OTHER_USER)
    plans = SqlitePlans(database)
    store = _store(database, plans)
    first = _connect(store, owner, "first@example.test")
    _connect(store, owner, "second@example.test")
    plans_on(plans, FREE)
    directory = SqliteUserDirectory(database)
    directory.set_role(owner, Role.USER)

    with pytest.raises(PlanLimitReached) as refused:
        _connect(store, owner, "third@example.test")
    renewed = _connect(store, owner, "first@example.test")

    assert refused.value.limit == 1
    assert renewed.id == first.id
    assert _emails(store, owner) == ["first@example.test", "second@example.test"]

    # Promoting them again lifts the limit.
    directory.set_role(owner, Role.INSTALLATION_ADMINISTRATOR)
    _connect(store, owner, "third@example.test")

    assert len(_emails(store, owner)) == 3


def test_a_users_own_plan_sets_their_limit(database: Path) -> None:
    plans = SqlitePlans(database)
    plans_on(plans, FREE, FAMILY)
    store = _store(database, plans)
    member = limited_user(database, plan=FAMILY.key.value)
    for number in range(3):
        _connect(store, member, f"member-{number}@example.test")

    with pytest.raises(PlanLimitReached) as refused:
        _connect(store, member, "member-3@example.test")

    assert refused.value.limit == 3


def test_a_store_without_allowances_limits_nobody(database: Path) -> None:
    plans_on(SqlitePlans(database), FREE)
    store = _store(database, None)
    member = limited_user(database)

    _connect(store, member, "first@example.test")
    _connect(store, member, "second@example.test")

    assert len(_emails(store, member)) == 2


# Through the OAuth callback, as both providers complete their flows.

CALLBACK = "/api/v1/oauth/google/callback?state=synthetic-state&code=synthetic-code"


def _installation(database: Path) -> tuple[Container, Adapters]:
    settings = Settings(database, master_key=CredentialCipher.generate_key())
    adapters = build_adapters(settings)
    return replace(compose(settings, adapters), scheduler=None), adapters


def _account_store(adapters: Adapters) -> SqliteConnectedAccountStore:
    """The store both providers' callbacks save accounts through."""
    store = getattr(adapters.accounts, "__self__", None)
    assert isinstance(store, SqliteConnectedAccountStore)
    return store


def _consent_returns(adapters: Adapters, email: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Google's consent completes for the signed-in User with `email` as the account's address,
    and Calendar Ghost saves it as the real callback does."""
    descriptor = adapters.providers.of(ProviderKind.GOOGLE)
    assert descriptor is not None
    assert isinstance(descriptor.calendars, GoogleOAuthService)
    store = _account_store(adapters)

    def complete(state: str, code: str, user: UserId) -> AuthorizedAccount:
        return connect_account(
            store,
            user,
            display_name="Synthetic",
            email=email,
            credentials="{}",
            provider=ProviderKind.GOOGLE,
        )

    monkeypatch.setattr(descriptor.calendars, "complete", Mock(side_effect=complete))


def _member_at_the_limit(database: Path, adapters: Adapters) -> tuple[UserId, ConnectedAccount]:
    """A member on Free with one account and an enabled rule between two of its calendars."""
    administrator(adapters)
    member = limited_user(database)
    account = _connect(_account_store(adapters), member, "first@example.test")
    plans_on(adapters.plan_catalog, FREE)
    rule = SyncRule(
        SyncRuleId("member-rule"),
        endpoint(account.id.value, "home"),
        endpoint(account.id.value, "work"),
        state=SyncRuleState.ENABLED,
    )
    with adapters.unit_of_work(member)() as uow:
        uow.rules.add(rule)
        uow.commit()
    return member, account


def test_the_callback_reports_the_account_limit_and_connects_nothing(
    database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container, adapters = _installation(database)
    member, account = _member_at_the_limit(database, adapters)
    # The provider now reports another address: a renamed account, or another one chosen.
    _consent_returns(adapters, "renamed@example.test", monkeypatch)

    with TestClient(create_app(container)) as client:
        client.cookies.set(SESSION_COOKIE, session_for(database, member))
        response = client.get(CALLBACK, follow_redirects=False)
        rules = client.get("/api/v1/rules").json()

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/settings/connections?oauth=account_limit_reached&provider=google&limit=1"
    )
    assert _emails(_account_store(adapters), member) == ["first@example.test"]
    assert [(rule["id"], rule["state"]) for rule in rules] == [("member-rule", "enabled")]
    assert _account_store(adapters).for_user(member).get(account.id) == account


def test_reauthorizing_at_the_limit_resumes_the_rules_its_lapse_stopped(
    database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container, adapters = _installation(database)
    member, account = _member_at_the_limit(database, adapters)
    with adapters.unit_of_work(member)() as uow:
        stopped = uow.rules.get(SyncRuleId("member-rule"))
        assert stopped is not None
        uow.rules.save(stopped.degrade(awaiting_reauthorization=True))
        uow.accounts.lapse(account.id, attempted_at=datetime.now(UTC))
        uow.commit()
    _consent_returns(adapters, "first@example.test", monkeypatch)

    with TestClient(create_app(container)) as client:
        client.cookies.set(SESSION_COOKIE, session_for(database, member))
        response = client.get(CALLBACK, follow_redirects=False)
        rules = client.get("/api/v1/rules").json()

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/settings/connections?oauth=connected&provider=google"
        f"&account={account.id.value}&resumed=1"
    )
    assert [(rule["id"], rule["state"]) for rule in rules] == [("member-rule", "enabled")]
