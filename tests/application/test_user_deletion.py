"""User Deletion: Rule Removal for each rule, then everything the User owns (ADR 0030)."""

from collections.abc import Callable
from dataclasses import replace

import pytest

from calendar_sync.application.administration import (
    AdministratorRequired,
    DeleteOwnAccount,
    DeleteUser,
    DeletionResult,
    OwnAccountDeletion,
    OwnedRules,
    ShowOwnAccountDeletion,
    UserDeletionInterrupted,
    YourOwnDeletion,
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
    RegistrationPolicy,
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
from tests.identity_fakes import (
    MemoryInvitations,
    MemoryRegistration,
    MemorySessions,
    MemoryUsers,
    PlainPasswords,
)

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
    def __init__(
        self,
        *,
        destination_authorized: bool = True,
        failing: bool = False,
        people: tuple[User, ...] = (ADMIN, MEMBER),
    ) -> None:
        self.users = MemoryUsers()
        for user in people:
            self.users.add(user, f"hashed:{PASSWORD}")
        self.registration = MemoryRegistration(self.users, RegistrationPolicy.INVITATION_ONLY)
        self.invitations = MemoryInvitations(self.users, self.registration)
        self.sessions = MemorySessions(NOW, self.users)
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
        return DeleteOwnAccount(
            self.users,
            PlainPasswords(),
            self.sessions,
            self.owned,
            self.registration,
            self.invitations,
            FixedClock(),
        )

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
    session = installation.sessions.signed_in(MEMBER.id)

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


def test_an_administrator_deletes_themself_only_with_their_password() -> None:
    second = User(
        UserId("second-admin"),
        "second@example.test",
        Role.INSTALLATION_ADMINISTRATOR,
        UserState.ACTIVE,
        NOW,
    )
    installation = Installation(people=(ADMIN, second, MEMBER))

    # Deleting oneself here would skip the password the own-account route asks for.
    with pytest.raises(YourOwnDeletion):
        installation.delete_user().execute(ADMIN.id, ADMIN.id)
    assert installation.users.get(ADMIN.id) == ADMIN


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


def test_the_last_administrator_cannot_leave_while_anyone_else_remains() -> None:
    disabled = replace(MEMBER, state=UserState.DISABLED)
    for others in ((MEMBER,), (disabled,)):
        installation = Installation(people=(ADMIN, *others))

        with pytest.raises(LastAdministrator):
            installation.delete_own().execute(ADMIN.id, PASSWORD, ProjectionHandling.DELETE)
        assert installation.users.get(ADMIN.id) == ADMIN
        assert ShowOwnAccountDeletion(installation.users).execute(ADMIN.id) == (
            OwnAccountDeletion(needs_another_administrator=True, last_user=False)
        )


OTHER_ADMIN = User(
    UserId("other-admin"),
    "other@example.test",
    Role.INSTALLATION_ADMINISTRATOR,
    UserState.ACTIVE,
    NOW,
)


def _demoting(user_id: UserId) -> Callable[[MemoryUsers], object]:
    """Another Installation Administrator demoting `user_id` while the deletion runs."""
    return lambda users: users.users.update(
        {user_id: replace(users.users[user_id], role=Role.USER)}
    )


def test_deleting_an_administrator_while_the_deleter_is_demoted_keeps_the_user() -> None:
    installation = Installation(people=(ADMIN, MEMBER, OTHER_ADMIN))
    installation.users.meanwhile = _demoting(ADMIN.id)

    with pytest.raises(LastAdministrator):
        installation.delete_user().execute(ADMIN.id, OTHER_ADMIN.id)

    assert installation.users.get(OTHER_ADMIN.id) == OTHER_ADMIN


def test_leaving_while_the_other_administrator_is_demoted_keeps_an_administrator() -> None:
    """The check before Rule Removal passed; the final deletion is checked again and refused."""
    installation = Installation(people=(ADMIN, MEMBER, OTHER_ADMIN))
    installation.users.meanwhile = _demoting(OTHER_ADMIN.id)

    with pytest.raises(LastAdministrator):
        installation.delete_own().execute(ADMIN.id, PASSWORD, ProjectionHandling.DELETE)

    assert installation.users.get(ADMIN.id) == ADMIN


def test_two_last_users_leaving_at_once_return_the_installation_to_setup() -> None:
    """Both saw another User before removing their rules; the second to finish is the last."""
    installation = Installation(people=(ADMIN, OTHER_ADMIN))
    pending = installation.invitations.issue(ADMIN.id, NOW)
    installation.users.meanwhile = lambda users: users.users.pop(OTHER_ADMIN.id)

    installation.delete_own().execute(ADMIN.id, PASSWORD, ProjectionHandling.DELETE)

    assert installation.users.count() == 0
    assert installation.registration.policy() is RegistrationPolicy.ONLY_ME
    assert not installation.invitations.usable(pending.token, NOW)


def test_the_only_user_may_leave_and_the_installation_returns_to_setup() -> None:
    installation = Installation(people=(ADMIN,))
    pending = installation.invitations.issue(ADMIN.id, NOW)
    shown = ShowOwnAccountDeletion(installation.users).execute(ADMIN.id)

    installation.delete_own().execute(ADMIN.id, PASSWORD, ProjectionHandling.DELETE)

    assert shown == OwnAccountDeletion(needs_another_administrator=False, last_user=True)
    assert installation.users.count() == 0
    assert installation.registration.policy() is RegistrationPolicy.ONLY_ME
    assert not installation.invitations.usable(pending.token, NOW)


def test_anyone_else_may_leave_while_others_remain() -> None:
    installation = Installation()

    assert ShowOwnAccountDeletion(installation.users).execute(MEMBER.id) == (
        OwnAccountDeletion(needs_another_administrator=False, last_user=False)
    )


def test_someone_joining_while_the_last_user_leaves_keeps_their_administrator() -> None:
    installation = Installation(people=(ADMIN,))
    set_policy = installation.registration.set_policy

    def joined_meanwhile(policy: RegistrationPolicy) -> None:
        if installation.users.get(MEMBER.id) is None:
            installation.users.add(MEMBER, f"hashed:{PASSWORD}")
        set_policy(policy)

    installation.registration.set_policy = joined_meanwhile  # type: ignore[method-assign]

    with pytest.raises(LastAdministrator):
        installation.delete_own().execute(ADMIN.id, PASSWORD, ProjectionHandling.DELETE)
    assert installation.users.get(ADMIN.id) == ADMIN
    assert installation.rules_of(MEMBER.id) == (rule().id,)
