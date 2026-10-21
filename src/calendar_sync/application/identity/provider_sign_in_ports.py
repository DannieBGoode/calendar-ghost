"""Provider sign-in methods and installation enablement, separate from calendar consent."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from calendar_sync.application.identity.credentials import CredentialSnapshot
from calendar_sync.application.identity.ports import Session
from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.domain.access import UserId
from calendar_sync.domain.provider_identity import ProviderClaims


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


class ProviderSignInRefused(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Provider sign-in could not be completed")


class ProviderSignInUnavailable(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Provider sign-in is temporarily unavailable")


class ProviderSignInThrottled(ApplicationError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Provider sign-in is temporarily limited")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class BrowserProof:
    value: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class InvitationIntent:
    token: str = field(repr=False)
    email: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class BoundInvitation:
    token_hash: str = field(repr=False)
    email: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class BeginIntent:
    provider: str
    browser: BrowserProof
    invitation: InvitationIntent | None = None
    owner: LinkOwner | None = None


@dataclass(frozen=True, slots=True)
class FlowContext:
    invitation: BoundInvitation | None
    owner: LinkOwner | None
    config_fingerprint: str


@dataclass(frozen=True, slots=True)
class ProviderFlow:
    state_hash: str = field(repr=False)
    provider: str
    browser_hash: str = field(repr=False)
    expires_at: datetime
    context: FlowContext


@dataclass(frozen=True, slots=True)
class ProviderCallback:
    provider: str
    state: str = field(repr=False)
    code: str = field(repr=False)
    browser: BrowserProof
    # Resolved from the current session by the interface, never accepted from request input.
    owner: LinkOwner | None = None


@dataclass(frozen=True, slots=True)
class PendingLink:
    token: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PendingProviderLink:
    flow: ProviderFlow
    claims: ProviderClaims


class ProviderAuthorization(Protocol):
    @property
    def fingerprint(self) -> str: ...

    def begin(self, state: str, nonce: str, verifier: str) -> str: ...

    def exchange(self, code: str, nonce: str, verifier: str) -> ProviderClaims: ...


class ProviderFlows(Protocol):
    def begin(self, intent: BeginIntent, state: str) -> ProviderFlow: ...

    def consume(self, callback: ProviderCallback) -> ProviderFlow | None:
        """Claim exactly once before exchange, bound to the actual current browser and owner."""
        ...

    def defer(self, flow: ProviderFlow, claims: ProviderClaims) -> PendingLink:
        """Issue a fresh proof, invalidating any older pending proof for this browser."""
        ...

    def pending(self, browser: BrowserProof, token: str) -> PendingLink | None: ...

    def cancel(self, browser: BrowserProof) -> None: ...


@dataclass(frozen=True, slots=True)
class ProviderSignInResult:
    session: Session | None
    pending: PendingLink | None


@dataclass(frozen=True, slots=True)
class AdmissionCommand:
    claims: ProviderClaims
    flow: ProviderFlow
    expected: CredentialSnapshot | None


class ProviderAdmission(Protocol):
    def complete(self, command: AdmissionCommand) -> ProviderSignInResult: ...

    def confirm(
        self, pending: str, browser: BrowserProof, expected: CredentialSnapshot
    ) -> Session | None: ...


class ProviderFlowMaintenance(Protocol):
    def purge(self, before: datetime, limit: int) -> int: ...
