"""Ports of identity and access: Users, sessions, links, Integration Tokens, and Plans."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from calendar_sync.domain.access import RegistrationPolicy, Role, User, UserId, UserState
from calendar_sync.domain.plans import AssignmentSource, NewPlan, Plan, PlanKey


@dataclass(frozen=True, slots=True)
class Session:
    """A signed-in browser's session; only its token's hash is stored."""

    token: str = field(repr=False)
    expires_at: datetime
    user_id: UserId


class UserSort(StrEnum):
    JOINED = "joined"
    EMAIL = "email"
    LAST_SIGN_IN = "last_sign_in"


@dataclass(frozen=True, slots=True)
class UserQuery:
    """One page of the Users an Installation Administrator looks for."""

    search: str = ""
    """Part of an email, in any case."""
    role: Role | None = None
    state: UserState | None = None
    plan: PlanKey | None = None
    """Only Users who have this Plan: as their own, or, for the Default Plan, by having none of
    their own, whatever their role or state and whether Plans are on (ADR 0038)."""
    sort: UserSort = UserSort.JOINED
    descending: bool = False
    offset: int = 0
    limit: int | None = 50
    """How many to return; None returns every match, read in the same step as the total."""


@dataclass(frozen=True, slots=True)
class UserPage:
    users: tuple[User, ...]
    total: int
    """How many Users match, across every page."""


class UserDirectory(Protocol):
    """Every User of the installation, and their password hashes. Signing in, inviting, and
    administering Users read it; it holds none of a User's calendars, rules, or activity."""

    def count(self) -> int: ...

    def list(self) -> Sequence[User]:
        """Every User, the first first."""
        ...

    def find(self, query: UserQuery) -> UserPage:
        """The Users matching `query`; Users who never signed in sort last either way."""
        ...

    def get(self, user_id: UserId) -> User | None: ...

    def by_email(self, email: str) -> User | None:
        """The User who signs in with `email`, already in its normal form."""
        ...

    def without_email(self) -> User | None:
        """The upgraded first User, while they have not added an email."""
        ...

    def add_first(self, user: User, password_hash: str) -> bool:
        """Add `user` only if there is no User yet, atomically; whether it was added."""
        ...

    def add(self, user: User, password_hash: str) -> None:
        """Add a User; raises EmailTaken when another User has the email."""
        ...

    def set_email(self, user_id: UserId, email: str) -> None:
        """Change only a User's email, already in its normal form; raises EmailTaken. Never
        writes their role or state, so it cannot undo an administrator's change."""
        ...

    def set_notification_email(self, user_id: UserId, notify_by_email: bool) -> None:
        """Change only whether a User's Incident Notifications also come by email."""
        ...

    def set_instant_sync(self, user_id: UserId, wanted: bool) -> None:
        """Change only whether a User wants Instant Sync."""
        ...

    def password_hash(self, user_id: UserId) -> str | None: ...

    def set_password_hash(self, user_id: UserId, password_hash: str) -> None: ...

    def record_sign_in(self, user_id: UserId, at: datetime) -> None: ...

    def set_role(self, user_id: UserId, role: Role) -> None:
        """Change only a User's role. Raises LastAdministrator, changing nothing, when that
        would take the role from the last active Installation Administrator; the check and the
        write are one serialized step, so two administrators acting at once cannot both pass."""
        ...

    def set_state(self, user_id: UserId, state: UserState) -> None:
        """Change only a User's state, guarded like `set_role`."""
        ...

    def delete(self, user_id: UserId) -> None:
        """Remove a User and, through their references, every record they own (ADR 0029).
        Guarded like `set_role`, except that the last remaining User may be deleted."""
        ...


@dataclass(frozen=True, slots=True)
class IssuedLink:
    """An Invitation or Password Reset Link as issued; its token is shown once."""

    id: str
    token: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PendingInvitation:
    id: str
    created_at: datetime
    expires_at: datetime


class RegistrationSettings(Protocol):
    def policy(self) -> RegistrationPolicy: ...

    def set_policy(self, policy: RegistrationPolicy) -> None:
        """Choose who may join. Raises OnlyMeNeedsOneUser for Only Me while another User exists,
        counted in one step with the change, so nobody joins between the count and the change."""
        ...

    def return_to_setup(self, at: datetime) -> None:
        """Choose Only Me, revoke every Invitation still usable at `at`, and turn Plans off,
        keeping their definitions, in one step, so a failure between them cannot leave an old
        Invitation or a hidden limit for the next setup. Raises OnlyMeNeedsOneUser, changing
        nothing, while another User exists."""
        ...


class Invitations(Protocol):
    """Single-use, expiring links that let one person become a User; only hashes are kept."""

    def issue(self, created_by: UserId, at: datetime) -> IssuedLink | None:
        """A new Invitation, or None when nobody may join now or `created_by` no longer
        administers; both are decided in one step with the insert."""
        ...

    def pending(self, at: datetime) -> Sequence[PendingInvitation]:
        """Invitations still usable at `at`, oldest first."""
        ...

    def revoke(self, invitation_id: str, at: datetime) -> bool:
        """Whether an invitation still usable at `at` is revoked now."""
        ...

    def usable(self, token: str, at: datetime) -> bool: ...

    def accept(self, token: str, user: User, password_hash: str, at: datetime) -> bool:
        """Use the invitation and add `user` in one step; False, adding nobody, when it is no
        longer usable, the Registration Policy lets nobody join, or no User is left (the
        installation returned to setup), all read in that same step. Raises EmailTaken,
        leaving the invitation usable."""
        ...


class PasswordResetLinks(Protocol):
    """Single-use, expiring links that let one User choose a new password."""

    def issue(self, user_id: UserId, created_by: UserId, at: datetime) -> IssuedLink:
        """A new link for the User; their earlier links stop working."""
        ...

    def owner(self, token: str, at: datetime) -> UserId | None:
        """The User a link still usable at `at` resets."""
        ...

    def reset(self, token: str, password_hash: str, at: datetime) -> UserId | None:
        """Use the link and store the new password in one step; the User, or None when it is no
        longer usable."""
        ...


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password: str, hashed: str) -> bool: ...


class Sessions(Protocol):
    def start(self, user_id: UserId, password_hash: str) -> Session | None:
        """Start a session only while the User is active and `password_hash`, the hash their
        password was just checked against, is still theirs; both in one step with the start.
        None otherwise, such as after a password change or reset that landed meanwhile."""
        ...

    def user_of(self, token: str | None) -> UserId | None:
        """The User a live session belongs to, while they may sign in."""
        ...

    def end(self, token: str | None) -> None: ...

    def end_all(self, user_id: UserId, *, keep: str | None = None) -> None:
        """End every session of a User, except `keep`."""
        ...


class SignInThrottle(Protocol):
    """Failed sign-ins counted per key, such as an email and a client address."""

    def wait(self, keys: tuple[str, ...]) -> float:
        """Seconds until every key may try again; 0 when they may now."""
        ...

    def failed(self, keys: tuple[str, ...]) -> None: ...

    def succeeded(self, keys: tuple[str, ...]) -> None:
        """Forget the failures of the email that signed in; a client's stay counted."""
        ...


class IntegrationTokenScope(StrEnum):
    STATUS_READ = "status:read"
    """Its User's Installation Status, over the status API and MCP."""
    INSTALLATION_READ = "installation:read"
    """Installation Health; only while its User is an Installation Administrator (ADR 0030)."""


@dataclass(frozen=True, slots=True)
class IntegrationTokenSummary:
    """An Integration Token as the administrator sees it; never the token or its hash."""

    id: str
    name: str
    scopes: frozenset[IntegrationTokenScope]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    owner: UserId = field(kw_only=True)
    """The User who issued it; it reads that User's Installation Status (ADR 0030)."""


@dataclass(frozen=True, slots=True)
class IssuedIntegrationToken:
    summary: IntegrationTokenSummary
    token: str = field(repr=False)
    """Shown once, when issued; only its hash is kept. Kept out of the repr, so a log line or
    traceback that prints this value never shows the token."""


class IntegrationTokens(Protocol):
    """One User's named credentials, issued so monitors and agents can read their status."""

    def issue(
        self,
        name: str,
        scopes: frozenset[IntegrationTokenScope] = frozenset({IntegrationTokenScope.STATUS_READ}),
        *,
        within: Callable[[], int | None] | None = None,
    ) -> IssuedIntegrationToken:
        """Issue a token; raises InvalidIntegrationTokenName before anything is stored.

        `within`, when given, reads the token limit once this store holds the write lock;
        raises PlanLimitReached(INTEGRATION_TOKENS, limit), issuing nothing, when the User's
        unrevoked tokens already reach it. A `within` that raises fails the issue.
        """
        ...

    def list(self) -> Sequence[IntegrationTokenSummary]:
        """Every token, newest first, revoked ones last."""
        ...

    def revoke(self, token_id: str) -> bool:
        """Whether a token of this User's that was not yet revoked is revoked now."""
        ...


class IntegrationTokenAuthentication(Protocol):
    def authenticate(self, token: str) -> IntegrationTokenSummary | None:
        """The token's summary, naming its owner, when it is well formed, known, and not
        revoked."""
        ...


@dataclass(frozen=True, slots=True)
class PlansSetting:
    """Whether Plans limit anyone, and the Default Plan of everyone with no Plan of their own."""

    enabled: bool
    default: PlanKey | None


@dataclass(frozen=True, slots=True)
class PlanListing:
    """A Plan as Administration lists it."""

    plan: Plan
    is_default: bool
    people: int
    """Everyone who has it: their own Plan, plus, for the default, everyone with none."""
    limited_people: int
    """Active Users who do not administer and have it, whom it limits while Plans are on."""


class PlanCatalog(Protocol):
    """The Plans an Installation Administrator defines, and whether they are on (ADR 0038)."""

    def settings(self) -> PlansSetting: ...

    def change_settings(self, enabled: bool, default: PlanKey | None, at: datetime) -> PlansSetting:
        """One step: raises PlanNotFound when `default` names no Plan, and PlansNeedDefault when
        it would clear a chosen default with Plans on. Turning Plans on when neither `default`
        nor the installation names one first adds NO_LIMITS_PLAN, at `at`, as the default."""
        ...

    def plans(self) -> Sequence[PlanListing]:
        """Every Plan, by name then key."""
        ...

    def followers(self) -> int:
        """How many Users have no Plan of their own, whatever their role or state: the people
        the Default Plan is theirs for, and whom making another Plan the default moves."""
        ...

    def any_plans(self) -> bool: ...

    def get(self, key: PlanKey) -> Plan | None: ...

    def add(self, plan: NewPlan, at: datetime) -> Plan:
        """Store the Plan under the key it asks for, or under the first key made from its name
        that no Plan has, and answer it as stored. Raises PlanKeyTaken when another Plan has the
        key it asks for."""
        ...

    def change(self, plan: Plan, at: datetime) -> None:
        """The key never changes; raises PlanNotFound."""
        ...

    def remove(self, key: PlanKey) -> None:
        """One step: raises PlanNotFound, PlanIsDefault, or PlanInUse(people)."""
        ...


@dataclass(frozen=True, slots=True)
class AssignmentChange:
    """How a User's own Plan was last set: by an administrator now, by billing later."""

    source: AssignmentSource
    actor: UserId | None
    """The administrator who set it; None when billing set it."""
    at: datetime


class PlanAssignments(Protocol):
    """The one way a User's own Plan changes; administrators now, billing later (ADR 0038)."""

    def assign_all(
        self, users: Collection[UserId], plan: PlanKey | None, change: AssignmentChange
    ) -> bool:
        """Set each of `users`' own Plan in one step, None for the Default Plan, all or none,
        recording the same change for each: False, changing nothing, when one of them is not a
        User. Raises PlanNotFound. A `plan` that is the Default Plan, read in the same write, is
        stored as None: giving the default is following it."""
        ...

    def last_changes(self, users: Collection[UserId]) -> Mapping[UserId, AssignmentChange]:
        """How each of `users`' own Plan was last set, read at once; a User whose own Plan
        nobody ever set is left out. The actor is None once that administrator is deleted."""
        ...
