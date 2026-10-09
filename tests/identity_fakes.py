"""In-memory stand-ins for the identity ports, for application tests."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from calendar_sync.application.errors import EmailTaken
from calendar_sync.application.ports import Session
from calendar_sync.domain.access import User, UserId


@dataclass
class MemoryUsers:
    users: dict[UserId, User] = field(default_factory=dict)
    hashes: dict[UserId, str] = field(default_factory=dict)

    def count(self) -> int:
        return len(self.users)

    def list(self) -> tuple[User, ...]:
        return tuple(sorted(self.users.values(), key=lambda user: user.created_at))

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
