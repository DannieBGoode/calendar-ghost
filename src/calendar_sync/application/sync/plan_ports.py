"""Allowance and Plan Grace ports enforced by Synchronization."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Protocol

from calendar_sync.domain.access import UserId
from calendar_sync.domain.plan_hold import PlanGrace
from calendar_sync.domain.plans import Allowance


class PlanGraceRecord(Protocol):
    def acquire(self) -> None:
        """Take this User's writer lock before settlement reads; require an existing User."""
        ...

    def get(self) -> PlanGrace | None: ...

    def save(self, grace: PlanGrace | None) -> None: ...

    def admissions(self) -> int: ...

    def admit(self, count: int = 1) -> None:
        """Record new admissions in this transaction, without resetting past admissions."""
        ...


class Allowances(Protocol):
    """What each User may use now, as their Plan allows (ADR 0038). Declared here so sync
    enforces limits without importing identity; SqlitePlans implements it."""

    def of(self, user: UserId) -> Allowance:
        """The User's Allowance, read now. Raises when it cannot be read, so a limit check
        fails closed; a User not found reads as UNLIMITED."""
        ...

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        """Each User's Allowance, in one read per 500 Users. A User not found reads as
        UNLIMITED."""
        ...
