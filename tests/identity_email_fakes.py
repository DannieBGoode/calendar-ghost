"""Focused in-memory identity email port for use-case tests."""

import math
from datetime import datetime, timedelta
from uuid import uuid4

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.identity_email import EmailTest, IdentityEmailTestThrottled
from calendar_sync.domain.access import User, UserId, UserState


class MemoryIdentityEmailTests:
    def __init__(self, users: dict[UserId, User]) -> None:
        self.users = users
        self.generation = 0
        self.attempts: dict[str, tuple[EmailTest, datetime]] = {}
        self.readiness: tuple[str, datetime] | None = None

    def tested_at(self, fingerprint: str) -> datetime | None:
        if self.readiness and self.readiness[0] == fingerprint:
            return self.readiness[1]
        return None

    def _recipient(self, actor: UserId) -> str | None:
        user = self.users.get(actor)
        if user and user.administers and user.state is UserState.ACTIVE:
            return user.email
        return None

    def admit(self, actor: UserId, fingerprint: str, at: datetime) -> EmailTest:
        if self._recipient(actor) is None:
            raise AdministratorRequired
        recent = sorted(
            admitted
            for test, admitted in self.attempts.values()
            if test.actor == actor and admitted > at - timedelta(hours=1)
        )
        if len(recent) >= 3:
            available = recent[len(recent) - 3] + timedelta(hours=1)
            raise IdentityEmailTestThrottled(max(1, math.ceil((available - at).total_seconds())))
        test = EmailTest(str(uuid4()), actor, self.generation, fingerprint)
        self.attempts[test.id] = (test, at)
        return test

    def record_success(self, test: EmailTest, recipient: str, at: datetime) -> bool:
        attempt = self.attempts.get(test.id)
        if (
            attempt is None
            or attempt[0].actor != test.actor
            or test.generation != self.generation
            or self._recipient(test.actor) != recipient
        ):
            return False
        self.readiness = (test.fingerprint, at)
        return True

    def purge(self, before: datetime, limit: int) -> None:
        old = sorted((at, key) for key, (_, at) in self.attempts.items() if at < before)
        for _, key in old[: max(0, limit)]:
            del self.attempts[key]

    def return_to_setup(self) -> None:
        self.generation += 1
        self.readiness = None
