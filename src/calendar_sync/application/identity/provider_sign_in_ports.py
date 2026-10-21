"""Provider sign-in methods and installation enablement, separate from calendar consent."""

from dataclasses import dataclass, field
from typing import Protocol

from calendar_sync.application.identity.credentials import CredentialSnapshot
from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.domain.access import UserId


@dataclass(frozen=True, slots=True)
class LinkOwner:
    user_id: UserId
    session_hash: str = field(repr=False)
    revision: int


@dataclass(frozen=True, slots=True)
class LinkedProviderIdentity:
    id: str
    provider: str


@dataclass(frozen=True, slots=True)
class SignInMethods:
    has_password: bool
    identities: tuple[LinkedProviderIdentity, ...]


@dataclass(frozen=True, slots=True)
class ProviderAvailability:
    """Immutable environment facts supplied by composition, never administrator enablement."""

    provider: str
    available: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class ProviderSignInSetting:
    provider: str
    enabled: bool
    available: bool
    reason: str | None


class LastSignInMethod(ApplicationError):
    def __init__(self) -> None:
        super().__init__("A User must retain a usable sign-in method")


class ProviderMethods(Protocol):
    def show(self, user_id: UserId) -> SignInMethods: ...

    def unlink(self, owner: LinkOwner, identity_id: str) -> bool:
        """Recheck live ownership and remaining methods, advance revision, keep owner session."""
        ...

    def set_password(self, owner: LinkOwner, expected: CredentialSnapshot, hashed: str) -> bool:
        """Set only a first password with live owning session and unchanged active credential."""
        ...


class ProviderSignInSettings(Protocol):
    def list(self) -> tuple[ProviderSignInSetting, ...]: ...

    def set_enabled(self, actor: UserId, provider: str, enabled: bool) -> None:
        """Recheck administrator and refuse disablement that strands an active User."""
        ...
