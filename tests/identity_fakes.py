"""In-memory stand-ins for the identity ports, for application tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from calendar_sync.application.errors import EmailTaken
from calendar_sync.application.ports import (
    IssuedLink,
    PendingInvitation,
    Session,
    UserPage,
    UserQuery,
    UserSort,
)
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
    meanwhile: Callable[[MemoryUsers], object] | None = None
    """Another request's change, landing once just before this directory's next guarded write."""

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
        ]
        known = [user for user in matching if _sort_value(user, query.sort) is not None]
        known.sort(key=lambda user: str(_sort_value(user, query.sort)), reverse=query.descending)
        ordered = known + [user for user in matching if _sort_value(user, query.sort) is None]
        page = ordered[query.offset : query.offset + query.limit]
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

    def set_email(self, user_id: UserId, email: str) -> None:
        user = self.users.get(user_id)
        if user is None:
            return
        changed = replace(user, email=email)
        self._require_free(changed)
        self.users[user_id] = changed

    def set_notification_email(self, user_id: UserId, notify_by_email: bool) -> None:
        if user_id in self.users:
            self.users[user_id] = replace(self.users[user_id], notify_by_email=notify_by_email)

    def password_hash(self, user_id: UserId) -> str | None:
        return self.hashes.get(user_id)

    def set_password_hash(self, user_id: UserId, password_hash: str) -> None:
        self.hashes[user_id] = password_hash

    def record_sign_in(self, user_id: UserId, at: datetime) -> None:
        self.users[user_id] = replace(self.users[user_id], last_sign_in_at=at)

    def set_role(self, user_id: UserId, role: Role) -> None:
        self._guarded(user_id, lambda user: replace(user, role=role))

    def set_state(self, user_id: UserId, state: UserState) -> None:
        self._guarded(user_id, lambda user: replace(user, state=state))

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

    def start(self, user_id: UserId, password_hash: str) -> Session | None:
        user = self.users.get(user_id)
        if (
            user is None
            or user.state is not UserState.ACTIVE
            or self.users.password_hash(user_id) != password_hash
        ):
            return None
        self.started += 1
        token = f"session-{self.started}"
        self.sessions[token] = user_id
        return Session(token, self.now + timedelta(days=7), user_id)

    def signed_in(self, user_id: UserId) -> Session:
        """A session of `user_id`, as signing in with their current password gives."""
        session = self.start(user_id, self.users.password_hash(user_id) or "")
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
class MemoryResetLinks:
    users: MemoryUsers
    links: list[_Link] = field(default_factory=list)

    def issue(self, user_id: UserId, created_by: UserId, at: datetime) -> IssuedLink:
        for earlier in self.links:
            if earlier.owner == user_id and earlier.usable(at):
                earlier.revoked_at = at
        link = _Link(
            f"reset-{len(self.links) + 1}", f"reset-token-{len(self.links) + 1}", at, user_id
        )
        self.links.append(link)
        return IssuedLink(link.id, link.token, link_expiry(at))

    def owner(self, token: str, at: datetime) -> UserId | None:
        link = next((link for link in self.links if link.token == token and link.usable(at)), None)
        return link.owner if link is not None else None

    def reset(self, token: str, password_hash: str, at: datetime) -> UserId | None:
        owner = self.owner(token, at)
        if owner is None:
            return None
        link = next(link for link in self.links if link.token == token)
        link.used_at = at
        self.users.set_password_hash(owner, password_hash)
        return owner
