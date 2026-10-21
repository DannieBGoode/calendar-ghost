"""In-memory stand-ins for the identity ports, for application tests."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.credentials import CredentialSnapshot
from calendar_sync.application.identity.errors import (
    EmailTaken,
    PlanKeyTaken,
    PlanNotFound,
    UserDisabled,
)
from calendar_sync.application.identity.password_reset import PreparedPasswordReset
from calendar_sync.application.identity.ports import (
    AssignmentChange,
    IssuedLink,
    PendingInvitation,
    PlanListing,
    PlansSetting,
    Session,
    SignInCredentials,
    UserPage,
    UserQuery,
    UserSort,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import (
    RegistrationPolicy,
    Role,
    User,
    UserId,
    UserState,
    link_expiry,
    require_administrator_remains,
    require_registration_change,
)
from calendar_sync.domain.plans import (
    NO_LIMITS_PLAN,
    UNLIMITED,
    Allowance,
    NewPlan,
    Plan,
    PlanKey,
    allowance_for,
    needs_no_limits_plan,
    require_removable,
    require_unique_name,
)


def _sort_value(user: User, sort: UserSort) -> object:
    if sort is UserSort.EMAIL:
        return user.email
    if sort is UserSort.LAST_SIGN_IN:
        return user.last_sign_in_at
    return user.created_at


@dataclass
class MemoryUsers:
    users: dict[UserId, User] = field(default_factory=dict)
    hashes: dict[UserId, str] = field(default_factory=dict)
    revisions: dict[UserId, int] = field(default_factory=dict)
    meanwhile: Callable[[MemoryUsers], object] | None = None
    """Another request's change, landing once just before this directory's next guarded write."""
    default_plan: PlanKey | None = None
    """The Default Plan, which MemoryPlans keeps here, as SQLite keeps Users and Plans in one
    database."""

    def sign_in_credentials(self, email: str | None) -> SignInCredentials | None:
        user = self.without_email() if email is None else self.by_email(email)
        if user is None:
            return None
        return SignInCredentials(
            user,
            CredentialSnapshot(user.id, self.revisions[user.id], self.hashes[user.id], user.email),
        )

    def count(self) -> int:
        return len(self.users)

    def list(self) -> tuple[User, ...]:
        return tuple(sorted(self.users.values(), key=lambda user: user.created_at))

    def find(self, query: UserQuery) -> UserPage:
        matching = [
            user
            for user in self.users.values()
            if query.search.casefold() in (user.email or "").casefold()
            and query.role in (None, user.role)
            and query.state in (None, user.state)
            and query.plan in (None, user.plan or self.default_plan)
        ]
        known = [user for user in matching if _sort_value(user, query.sort) is not None]
        known.sort(key=lambda user: str(_sort_value(user, query.sort)), reverse=query.descending)
        ordered = known + [user for user in matching if _sort_value(user, query.sort) is None]
        end = None if query.limit is None else query.offset + query.limit
        page = ordered[query.offset : end]
        return UserPage(tuple(page), len(matching))

    def get(self, user_id: UserId) -> User | None:
        return self.users.get(user_id)

    def by_email(self, email: str) -> User | None:
        return next((user for user in self.users.values() if user.email == email), None)

    def without_email(self) -> User | None:
        return next((user for user in self.users.values() if user.email is None), None)

    def add_first(self, user: User, password_hash: str) -> bool:
        if self.users:
            return False
        self.add(user, password_hash)
        return True

    def add(self, user: User, password_hash: str) -> None:
        self._require_free(user)
        self.users[user.id] = user
        self.hashes[user.id] = password_hash
        self.revisions[user.id] = 0

    def set_email(self, user_id: UserId, email: str) -> None:
        user = self.users.get(user_id)
        if user is None:
            return
        changed = replace(user, email=email)
        self._require_free(changed)
        self.users[user_id] = changed
        self.revisions[user_id] += 1

    def set_notification_email(self, user_id: UserId, notify_by_email: bool) -> None:
        if user_id in self.users:
            self.users[user_id] = replace(self.users[user_id], notify_by_email=notify_by_email)

    def set_instant_sync(self, user_id: UserId, wanted: bool) -> None:
        if user_id in self.users:
            self.users[user_id] = replace(self.users[user_id], instant_sync=wanted)

    def password_hash(self, user_id: UserId) -> str | None:
        return self.hashes.get(user_id)

    def set_password_hash(self, user_id: UserId, password_hash: str) -> None:
        self.hashes[user_id] = password_hash
        self.revisions[user_id] += 1

    def record_sign_in(self, user_id: UserId, at: datetime) -> None:
        self.users[user_id] = replace(self.users[user_id], last_sign_in_at=at)

    def set_role(self, user_id: UserId, role: Role) -> None:
        self._guarded(user_id, lambda user: replace(user, role=role))

    def set_state(self, user_id: UserId, state: UserState) -> None:
        self._guarded(user_id, lambda user: replace(user, state=state))
        if state is UserState.DISABLED and user_id in self.users:
            self.revisions[user_id] += 1

    def delete(self, user_id: UserId) -> None:
        self._guarded(user_id, lambda _user: None)

    def _guarded(self, user_id: UserId, change: Callable[[User], User | None]) -> None:
        """SQLite's guarded write: checked against every User as stored at the write."""
        self._concurrently()
        current = self.users.get(user_id)
        if current is None:
            return
        after = change(current)
        require_administrator_remains(self.users.values(), user_id, after)
        if after is None:
            del self.users[user_id]
            self.hashes.pop(user_id, None)
        else:
            self.users[user_id] = after

    def _concurrently(self) -> None:
        meanwhile, self.meanwhile = self.meanwhile, None
        if meanwhile is not None:
            meanwhile(self)

    def _require_free(self, user: User) -> None:
        if user.email is not None and any(
            other.email == user.email and other.id != user.id for other in self.users.values()
        ):
            raise EmailTaken("another User signs in with this email")


class PlainPasswords:
    """Keeps passwords recognizable, so tests can see which one was stored."""

    def hash(self, password: str) -> str:
        return f"hashed:{password}"

    def verify(self, password: str, hashed: str) -> bool:
        return hashed == f"hashed:{password}"


@dataclass
class MemorySessions:
    now: datetime
    users: MemoryUsers
    sessions: dict[str, UserId] = field(default_factory=dict)
    started: int = 0

    def start(
        self, user_id: UserId, password_hash: str, email: str | None, revision: int
    ) -> Session | None:
        user = self.users.get(user_id)
        if (
            user is None
            or user.state is not UserState.ACTIVE
            or self.users.password_hash(user_id) != password_hash
            or user.email != email
            or self.users.revisions[user_id] != revision
        ):
            return None
        self.started += 1
        token = f"session-{self.started}"
        self.sessions[token] = user_id
        return Session(token, self.now + timedelta(days=7), user_id)

    def signed_in(self, user_id: UserId) -> Session:
        """A session of `user_id`, as signing in with their current password gives."""
        facts = self.users.sign_in_credentials(self.users.users[user_id].email)
        assert facts is not None
        session = self.start(
            user_id,
            facts.credential.password_hash,
            facts.credential.email,
            facts.credential.revision,
        )
        assert session is not None
        return session

    def user_of(self, token: str | None) -> UserId | None:
        return self.sessions.get(token) if token else None

    def end(self, token: str | None) -> None:
        if token:
            self.sessions.pop(token, None)

    def end_all(self, user_id: UserId, *, keep: str | None = None) -> None:
        self.sessions = {
            token: owner
            for token, owner in self.sessions.items()
            if owner != user_id or token == keep
        }


@dataclass
class CountingThrottle:
    """Refuses a key once it has failed `limit` times."""

    limit: int = 3
    failures: dict[str, int] = field(default_factory=dict)

    def wait(self, keys: tuple[str, ...]) -> float:
        return 60.0 if any(self.failures.get(key, 0) >= self.limit for key in keys) else 0.0

    def failed(self, keys: tuple[str, ...]) -> None:
        for key in keys:
            self.failures[key] = self.failures.get(key, 0) + 1

    def succeeded(self, keys: tuple[str, ...]) -> None:
        for key in keys:
            if key.startswith("email:"):
                self.failures.pop(key, None)


@dataclass
class MemoryRegistration:
    users: MemoryUsers
    current: RegistrationPolicy = RegistrationPolicy.ONLY_ME
    links: list[_Link] = field(default_factory=list)
    """The Invitations' links, shared with MemoryInvitations as SQLite shares one database."""
    plans: MemoryPlans | None = None
    """The installation's Plans, which returning to setup turns off as SQLite's does."""

    def policy(self) -> RegistrationPolicy:
        return self.current

    def set_policy(self, policy: RegistrationPolicy) -> None:
        require_registration_change(policy, self.users.count())
        self.current = policy

    def return_to_setup(self, at: datetime) -> None:
        require_registration_change(RegistrationPolicy.ONLY_ME, self.users.count())
        self.current = RegistrationPolicy.ONLY_ME
        for link in self.links:
            if link.usable(at):
                link.revoked_at = at
        if self.plans is not None:
            self.plans.enabled = False


@dataclass
class _Link:
    id: str
    token: str
    issued_at: datetime
    owner: UserId | None = None
    used_at: datetime | None = None
    revoked_at: datetime | None = None

    def usable(self, at: datetime) -> bool:
        return self.used_at is None and self.revoked_at is None and at < link_expiry(self.issued_at)


@dataclass
class MemoryInvitations:
    users: MemoryUsers
    registration: MemoryRegistration

    @property
    def links(self) -> list[_Link]:
        return self.registration.links

    def issue(self, created_by: UserId, at: datetime) -> IssuedLink | None:
        creator = self.users.get(created_by)
        if (
            creator is None
            or not creator.administers
            or creator.state is not UserState.ACTIVE
            or not self.registration.policy().lets_people_join
        ):
            return None
        link = _Link(f"invitation-{len(self.links) + 1}", f"token-{len(self.links) + 1}", at)
        self.links.append(link)
        return IssuedLink(link.id, link.token, link_expiry(at))

    def pending(self, at: datetime) -> tuple[PendingInvitation, ...]:
        return tuple(
            PendingInvitation(link.id, link.issued_at, link_expiry(link.issued_at))
            for link in self.links
            if link.usable(at)
        )

    def revoke(self, invitation_id: str, at: datetime) -> bool:
        link = next((link for link in self.links if link.id == invitation_id), None)
        if link is None or not link.usable(at):
            return False
        link.revoked_at = at
        return True

    def usable(self, token: str, at: datetime) -> bool:
        return any(link.token == token and link.usable(at) for link in self.links)

    def accept(self, token: str, user: User, password_hash: str, at: datetime) -> bool:
        link = next((link for link in self.links if link.token == token and link.usable(at)), None)
        joining = self.registration.policy().lets_people_join and self.users.count() > 0
        if link is None or not joining:
            return False
        self.users.add(user, password_hash)
        link.used_at = at
        return True


@dataclass
class _ResetLink:
    id: str
    token: str = field(repr=False)
    issued_at: datetime
    owner: UserId
    revision: int
    expires_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None

    def usable(self, at: datetime) -> bool:
        return self.used_at is None and self.revoked_at is None and at < self.expires_at


@dataclass
class MemoryResetLinks:
    users: MemoryUsers
    sessions: MemorySessions
    clock: Clock
    links: list[_ResetLink] = field(default_factory=list)

    def issue(self, user_id: UserId, created_by: UserId, at: datetime) -> IssuedLink:
        self.users._concurrently()
        actor = self.users.users.get(created_by)
        if actor is None or not actor.administers or actor.state is not UserState.ACTIVE:
            raise AdministratorRequired("an active Installation Administrator is required")
        user = self.users.users.get(user_id)
        if user is None or user.state is not UserState.ACTIVE:
            raise UserDisabled("the User is no longer active")
        self._revoke(user_id, at)
        return self._insert(user_id, at, link_expiry(at))

    def issue_for_email(self, email: str) -> PreparedPasswordReset | None:
        self.users._concurrently()
        at = self.clock.now()
        user = self.users.by_email(email)
        if user is None or user.state is not UserState.ACTIVE:
            return None
        return PreparedPasswordReset(email, self._insert(user.id, at, at + timedelta(hours=1)))

    def _insert(self, user_id: UserId, at: datetime, expires: datetime) -> IssuedLink:
        link = _ResetLink(
            f"reset-{len(self.links) + 1}",
            f"reset-token-{len(self.links) + 1}",
            at,
            user_id,
            self.users.revisions[user_id],
            expires,
        )
        self.links.append(link)
        return IssuedLink(link.id, link.token, expires)

    def owner(self, token: str, at: datetime) -> UserId | None:
        link = next((link for link in self.links if link.token == token and link.usable(at)), None)
        user = self.users.users.get(link.owner) if link is not None else None
        if user is None or user.state is not UserState.ACTIVE or link is None:
            return None
        return user.id if link.revision == self.users.revisions[user.id] else None

    def reset(self, token: str, password_hash: str) -> UserId | None:
        self.users._concurrently()
        at = self.clock.now()
        owner = self.owner(token, at)
        if owner is None:
            return None
        link = next(link for link in self.links if link.token == token)
        link.used_at = at
        self.users.set_password_hash(owner, password_hash)
        self._revoke(owner, at)
        self.sessions.end_all(owner)
        return owner

    def _revoke(self, user_id: UserId, at: datetime) -> None:
        for link in self.links:
            if link.owner == user_id and link.used_at is None and link.revoked_at is None:
                link.revoked_at = at


@dataclass
class MemoryCredentialChanges:
    users: MemoryUsers
    sessions: MemorySessions
    clock: Clock

    def current(self, user_id: UserId) -> CredentialSnapshot | None:
        user = self.users.users.get(user_id)
        if user is None or user.state is not UserState.ACTIVE:
            return None
        return CredentialSnapshot(
            user_id, self.users.revisions[user_id], self.users.hashes[user_id], user.email
        )

    def change_password(self, expected: CredentialSnapshot, hashed: str, keep: str | None) -> bool:
        self.users._concurrently()
        if self.current(expected.user_id) != expected:
            return False
        if keep is not None and self.sessions.user_of(keep) != expected.user_id:
            return False
        self.users.set_password_hash(expected.user_id, hashed)
        self.sessions.end_all(expected.user_id, keep=keep)
        return True

    def change_email(self, expected: CredentialSnapshot, email: str) -> bool:
        self.users._concurrently()
        if self.current(expected.user_id) != expected:
            return False
        self.users.set_email(expected.user_id, email)
        return True


@dataclass
class MemoryPlans:
    """Plans as SqlitePlans keeps them; each User's role and own Plan come from `users`."""

    users: MemoryUsers = field(default_factory=MemoryUsers)
    enabled: bool = False
    catalog: dict[PlanKey, Plan] = field(default_factory=dict)
    changes: dict[UserId, AssignmentChange] = field(default_factory=dict)
    """How each User's own Plan was last set, as SQLite's users table records it."""

    @property
    def default(self) -> PlanKey | None:
        return self.users.default_plan

    def of(self, user: UserId) -> Allowance:
        found = self.users.get(user)
        if found is None:
            return UNLIMITED
        return allowance_for(
            plans_on=self.enabled,
            administers=found.administers,
            own=self.catalog.get(found.plan) if found.plan is not None else None,
            default=self.catalog.get(self.default) if self.default is not None else None,
        )

    def of_users(self, users: Collection[UserId]) -> dict[UserId, Allowance]:
        return {user: self.of(user) for user in users}

    def settings(self) -> PlansSetting:
        return PlansSetting(self.enabled, self.default)

    def change_settings(self, enabled: bool, default: PlanKey | None, at: datetime) -> PlansSetting:
        if default is not None:
            self._require(default)
        if needs_no_limits_plan(enabled, default, self.default):
            names = [plan.name for plan in self.catalog.values()]
            default = self.add(NO_LIMITS_PLAN.named_apart(names), at).key
        self.enabled, self.users.default_plan = enabled, default
        return self.settings()

    def plans(self) -> tuple[PlanListing, ...]:
        ordered = sorted(self.catalog.values(), key=lambda plan: (plan.name, plan.key.value))
        return tuple(self._listing(plan) for plan in ordered)

    def followers(self) -> int:
        return sum(user.plan is None for user in self.users.users.values())

    def any_plans(self) -> bool:
        return bool(self.catalog)

    def get(self, key: PlanKey) -> Plan | None:
        return self.catalog.get(key)

    def add(self, plan: NewPlan, at: datetime) -> Plan:
        require_unique_name(plan.name, [other.name for other in self.catalog.values()])
        taken = {key.value for key in self.catalog}
        if plan.key is not None and plan.key.value in taken:
            raise PlanKeyTaken(f"a plan with the key {plan.key.value} already exists")
        stored = plan.keyed(taken)
        self.catalog[stored.key] = stored
        return stored

    def change(self, plan: Plan, at: datetime) -> None:
        self._require(plan.key)
        others = [other.name for other in self.catalog.values() if other.key != plan.key]
        require_unique_name(plan.name, others)
        self.catalog[plan.key] = plan

    def remove(self, key: PlanKey) -> None:
        self._require(key)
        people = sum(user.plan == key for user in self.users.users.values())
        require_removable(key, self.default, people)
        del self.catalog[key]

    def assign_all(self, plans: Mapping[UserId, PlanKey | None], change: AssignmentChange) -> bool:
        for plan in plans.values():
            if plan is not None:
                self._require(plan)
        found = [self.users.get(user) for user in plans]
        if any(user is None for user in found):
            return False
        for user in found:
            assert user is not None
            plan = plans[user.id]
            self.users.users[user.id] = replace(user, plan=None if plan == self.default else plan)
            self.changes[user.id] = change
        return True

    def last_changes(self, users: Collection[UserId]) -> dict[UserId, AssignmentChange]:
        return {user: self.changes[user] for user in users if user in self.changes}

    def _require(self, key: PlanKey) -> None:
        if key not in self.catalog:
            raise PlanNotFound(f"plan {key.value} does not exist")

    def _listing(self, plan: Plan) -> PlanListing:
        holders = [
            user
            for user in self.users.users.values()
            if user.plan == plan.key or (user.plan is None and plan.key == self.default)
        ]
        limited = [
            user for user in holders if not user.administers and user.state is UserState.ACTIVE
        ]
        return PlanListing(plan, plan.key == self.default, len(holders), len(limited))


@dataclass
class BrokenAllowances:
    """An Allowances whose every read raises, as a locked or failing database would."""

    def of(self, user: UserId) -> Allowance:
        raise RuntimeError("database is locked")

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        raise RuntimeError("database is locked")
