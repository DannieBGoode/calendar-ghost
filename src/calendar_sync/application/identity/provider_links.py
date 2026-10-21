"""Password-proven linking of a browser-bound, unverified provider identity."""

import secrets
from dataclasses import dataclass, field

from calendar_sync.application.identity.errors import SignInThrottled
from calendar_sync.application.identity.ports import (
    PasswordHasher,
    Session,
    SignInThrottle,
    UserDirectory,
)
from calendar_sync.application.identity.provider_sign_in_ports import (
    BrowserProof,
    ProviderAdmission,
    ProviderFlows,
    ProviderSignInRefused,
)
from calendar_sync.application.identity.sign_in import _normal_email
from calendar_sync.domain.access import UserState


@dataclass(slots=True)
class ConfirmProviderLink:
    users: UserDirectory
    passwords: PasswordHasher
    throttle: SignInThrottle
    flows: ProviderFlows
    admission: ProviderAdmission
    _decoy: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._decoy = self.passwords.hash(secrets.token_urlsafe(16))

    def execute(
        self, browser: BrowserProof, pending: str, email: str, password: str, client: str
    ) -> Session:
        address = _normal_email(email)
        keys = (f"email:{address or ''}", f"client:{client}")
        wait = self.throttle.wait(keys)
        if wait > 0:
            raise SignInThrottled(wait)
        if self.flows.pending(browser, pending) is None or len(password) > 1024:
            raise ProviderSignInRefused
        facts = self.users.sign_in_credentials(address) if address else None
        hashed = facts.credential.password_hash if facts else None
        matches = self.passwords.verify(password, hashed or self._decoy)
        if (
            facts is None
            or hashed is None
            or not matches
            or facts.user.state is not UserState.ACTIVE
        ):
            self.throttle.failed(keys)
            raise ProviderSignInRefused
        session = self.admission.confirm(pending, browser, facts.credential)
        if session is None:
            self.throttle.failed(keys)
            raise ProviderSignInRefused
        self.throttle.succeeded(keys)
        return session
