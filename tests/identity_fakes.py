"""In-memory stand-ins for the identity ports, for application tests."""

from __future__ import annotations

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
from calendar_sync.domain.access import RegistrationPolicy, User, UserId, link_expiry


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

    def save(self, user: User) -> None:
        self._require_free(user)
        self.users[user.id] = user

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

    def delete(self, user_id: UserId) -> None:
        self.users.pop(user_id, None)
        self.hashes.pop(user_id, None)

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
    sessions: dict[str, UserId] = field(default_factory=dict)

    def start(self, user_id: UserId) -> Session:
        token = f"session-{len(self.sessions) + 1}"
        self.sessions[token] = user_id
        return Session(token, self.now + timedelta(days=7), user_id)

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
    current: RegistrationPolicy = RegistrationPolicy.ONLY_ME

    def policy(self) -> RegistrationPolicy:
        return self.current

    def set_policy(self, policy: RegistrationPolicy) -> None:
        self.current = policy


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
    links: list[_Link] = field(default_factory=list)

    def issue(self, created_by: UserId, at: datetime) -> IssuedLink:
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

    def revoke_all(self, at: datetime) -> None:
        for link in self.links:
            if link.usable(at):
                link.revoked_at = at

    def usable(self, token: str, at: datetime) -> bool:
        return any(link.token == token and link.usable(at) for link in self.links)

    def accept(self, token: str, user: User, password_hash: str, at: datetime) -> bool:
        link = next((link for link in self.links if link.token == token and link.usable(at)), None)
        if link is None:
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
