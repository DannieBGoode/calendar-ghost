"""Verified joining keeps anonymous admission separate from proof issuance and delivery."""

from contextlib import suppress
from dataclasses import dataclass

from calendar_sync.application.identity.administration import LinkUnusable
from calendar_sync.application.identity.errors import PasswordPolicyViolation
from calendar_sync.application.identity.identity_email import IdentityEmailSetup
from calendar_sync.application.identity.ports import (
    PasswordHasher,
    Session,
    Sessions,
    UserDirectory,
)
from calendar_sync.application.identity.registration_admission import RegistrationAdmission
from calendar_sync.application.identity.registration_ports import (
    IdentityRegistrationSender,
    PendingRegistration,
    PreparedRegistration,
    RegistrationEmailQueue,
    RegistrationEmailRequest,
    RegistrationProofs,
    RegistrationReadiness,
    RegistrationUnavailable,
)
from calendar_sync.application.identity.sign_in import require_password, start_session
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import email_address


def _bounded_token(token: str) -> bool:
    return 0 < len(token) <= 128 and token.isascii()


@dataclass(frozen=True, slots=True)
class RequestRegistration:
    admission: RegistrationAdmission
    readiness: RegistrationReadiness
    queue: RegistrationEmailQueue
    fingerprint: str | None

    def execute(self, email: str, client: str, invitation_token: str | None = None) -> None:
        normalized = email_address(email)
        if invitation_token is not None and not _bounded_token(invitation_token):
            raise LinkUnusable("this invitation is no longer usable")
        self.admission.admit_front(client)
        if not self.readiness.public_available() or self.fingerprint is None:
            raise RegistrationUnavailable("Open registration is temporarily unavailable")
        if self.admission.admit_durable(normalized, client):
            with suppress(Exception):
                self.queue.submit_registration(
                    RegistrationEmailRequest(normalized, self.fingerprint, invitation_token)
                )


@dataclass(frozen=True, slots=True)
class CheckRegistration:
    proofs: RegistrationProofs
    admission: RegistrationAdmission
    fingerprint: str | None

    def execute(self, token: str, client: str) -> PendingRegistration | None:
        pending = None

        def check() -> bool:
            nonlocal pending
            if _bounded_token(token):
                pending = self.proofs.check(token, self.fingerprint)
            return pending is not None

        return pending if self.admission.check_token(client, check) else None


@dataclass(frozen=True, slots=True)
class CompleteRegistration:
    proofs: RegistrationProofs
    passwords: PasswordHasher
    sessions: Sessions
    users: UserDirectory
    clock: Clock
    admission: RegistrationAdmission
    fingerprint: str | None

    def execute(self, token: str, password: str, client: str) -> Session:
        self.admission.admit_completion(client)
        if (
            CheckRegistration(self.proofs, self.admission, self.fingerprint).execute(token, client)
            is None
        ):
            raise LinkUnusable("this registration link is no longer usable")
        require_password(password)
        if len(password) > 1024:
            raise PasswordPolicyViolation("use at most 1024 characters")
        hashed = self.passwords.hash(password)
        user = self.proofs.complete(token, hashed, self.fingerprint)
        if user is None:
            raise LinkUnusable("this registration link is no longer usable")
        session = start_session(self.sessions, user.id, hashed, user.email, 0)
        self.users.record_sign_in(user.id, self.clock.now())
        return session


@dataclass(frozen=True, slots=True)
class DeliverRegistration:
    proofs: RegistrationProofs
    setup: IdentityEmailSetup
    sender: IdentityRegistrationSender

    def prepare(self, request: RegistrationEmailRequest) -> PreparedRegistration | None:
        if request.fingerprint != self.setup.fingerprint:
            return None
        return self.proofs.issue(request.email, request.invitation_token, request.fingerprint)

    def send(self, prepared: PreparedRegistration) -> None:
        self.sender.send_registration(prepared.recipient, prepared.link.token)
