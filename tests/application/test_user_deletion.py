"""User Deletion: Rule Removal for each rule, then everything the User owns (ADR 0030)."""

from dataclasses import replace

import pytest

from calendar_sync.application.administration import (
    AdministratorRequired,
    DeleteOwnAccount,
    DeleteUser,
    DeletionResult,
    OwnedRules,
    UserDeletionInterrupted,
)
from calendar_sync.application.errors import (
    IncorrectPassword,
    ProviderFailure,
    ProviderFailureKind,
    RemovalRequiresAuthorization,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import ConnectedAccountState, UnitOfWorkFactory
from calendar_sync.application.removal import RemoveSyncRule
from calendar_sync.domain.access import (
    LastAdministrator,
    Role,
    User,
    UserId,
    UserState,
)
from calendar_sync.domain.model import (
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    ProjectionFingerprint,
    ProjectionHandling,
    SyncRuleId,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, rule
from tests.identity_fakes import MemorySessions, MemoryUsers, PlainPasswords

PASSWORD = "correct horse battery staple"
ADMIN = User(
    UserId("admin"), "admin@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW
)
MEMBER = User(UserId("member"), "member@example.test", Role.USER, UserState.ACTIVE, NOW)


class Deleter:
    def __init__(self, failing: bool = False) -> None:
        self.deleted: list[EventRef] = []
        self.failing = failing

    def delete_projection(
        self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
    ) -> None:
        if self.failing:
            raise ProviderFailure(ProviderFailureKind.PERMANENT, "synthetic refusal")
        self.deleted.append(destination)


class Installation:
    def __init__(self, *, destination_authorized: bool = True, failing: bool = False) -> None:
        self.users = MemoryUsers()
        for user in (ADMIN, MEMBER):
            self.users.add(user, f"hashed:{PASSWORD}")
        self.sessions = MemorySessions(NOW)
        self.database = InMemoryUnitOfWorkFactory()
        self.deleter = Deleter(failing)
        self.locks = RuleLocks()
        state = self.database.for_user(MEMBER.id).state
        state.rules[rule().id] = rule()
        state.accounts[rule().source.connected_account_id] = ConnectedAccountState.CONNECTED
        state.accounts[rule().destination.connected_account_id] = (
            ConnectedAccountState.CONNECTED
            if destination_authorized
            else ConnectedAccountState.DISCONNECTED
        )
        source = EventRef(rule().source, EventId("source-1"))
        state.mappings[(rule().id, source)] = EventMapping(
            EventMappingId("mapping-1"),
            rule().id,
            source,
            EventRef(rule().destination, EventId("projection-1")),
            "revision-1",
            ProjectionFingerprint("fingerprint"),
        )

    def owned(self, user_id: UserId) -> OwnedRules:
        units = self.database.for_user(user_id)
        return OwnedRules(
            units,
            RemoveSyncRule(units, self.deleter, _Authorizations(units), FixedClock(), self.locks),
        )

    def delete_user(self) -> DeleteUser:
        return DeleteUser(self.users, self.sessions, self.owned)

    def delete_own(self) -> DeleteOwnAccount:
        return DeleteOwnAccount(self.users, PlainPasswords(), self.sessions, self.owned)

    def rules_of(self, user_id: UserId) -> tuple[SyncRuleId, ...]:
        with self.database.for_user(user_id)() as uow:
            return tuple(item.id for item in uow.rules.list())


class _Authorizations:
    def __init__(self, units: UnitOfWorkFactory) -> None:
        self._units = units

    def is_connected(self, account_id: ConnectedAccountId) -> bool:
        with self._units() as uow:
            return uow.accounts.state(account_id) is ConnectedAccountState.CONNECTED


def test_an_administrator_deleting_a_user_deletes_their_projections_and_everything_else() -> None:
    installation = Installation()
    session = installation.sessions.start(MEMBER.id)

    result = installation.delete_user().execute(ADMIN.id, MEMBER.id)

    assert result == DeletionResult(rules=1, deleted=1, detached=0, left=0)
    assert installation.deleter.deleted == [EventRef(rule().destination, EventId("projection-1"))]
    assert installation.rules_of(MEMBER.id) == ()
    assert installation.users.get(MEMBER.id) is None
    assert installation.sessions.user_of(session.token) is None


def test_projections_nothing_can_reach_are_left_where_they_are() -> None:
    installation = Installation(destination_authorized=False)

    result = installation.delete_user().execute(ADMIN.id, MEMBER.id)

    assert result == DeletionResult(rules=1, deleted=0, detached=1, left=1)
    assert installation.deleter.deleted == []
    assert installation.users.get(MEMBER.id) is None


def test_an_interrupted_deletion_keeps_the_user_disabled_so_it_can_be_retried() -> None:
    installation = Installation(failing=True)

    with pytest.raises(UserDeletionInterrupted) as interrupted:
        installation.delete_user().execute(ADMIN.id, MEMBER.id)

    assert (interrupted.value.removed, interrupted.value.remaining) == (0, 1)
    assert installation.users.get(MEMBER.id) == replace(MEMBER, state=UserState.DISABLED)
    installation.deleter.failing = False
    assert installation.delete_user().execute(ADMIN.id, MEMBER.id).deleted == 1


def test_only_an_administrator_deletes_another_user() -> None:
    installation = Installation()

    with pytest.raises(AdministratorRequired):
        installation.delete_user().execute(MEMBER.id, ADMIN.id)
    assert installation.users.count() == 2


def test_a_user_deleting_themself_may_keep_their_projections() -> None:
    installation = Installation()

    result = installation.delete_own().execute(MEMBER.id, PASSWORD, ProjectionHandling.DETACH)

    assert result == DeletionResult(rules=1, deleted=0, detached=1, left=0)
    assert installation.deleter.deleted == []
    assert installation.users.get(MEMBER.id) is None


def test_a_user_deleting_themself_confirms_their_password() -> None:
    installation = Installation()

    with pytest.raises(IncorrectPassword):
        installation.delete_own().execute(MEMBER.id, "wrong password!", ProjectionHandling.DELETE)
    assert installation.rules_of(MEMBER.id) == (rule().id,)


def test_a_user_who_cannot_reach_their_projections_is_asked_to_choose_again() -> None:
    installation = Installation(destination_authorized=False)

    with pytest.raises(RemovalRequiresAuthorization):
        installation.delete_own().execute(MEMBER.id, PASSWORD, ProjectionHandling.DELETE)
    assert installation.rules_of(MEMBER.id) == (rule().id,)
    assert installation.users.get(MEMBER.id) == MEMBER


def test_the_last_administrator_cannot_be_deleted() -> None:
    installation = Installation()

    with pytest.raises(LastAdministrator):
        installation.delete_own().execute(ADMIN.id, PASSWORD, ProjectionHandling.DELETE)
    assert installation.users.get(ADMIN.id) == ADMIN
