"""Users and who may do what on an installation (ADR 0029, ADR 0030)."""

from __future__ import annotations

from dataclasses import dataclass

from calendar_sync.domain.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class UserId:
    """The User every Connected Account, rule, token, Incident, and Audit Entry belongs to."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or self.value.isspace():
            raise DomainValidationError("user id must not be empty")
