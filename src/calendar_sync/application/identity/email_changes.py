"""Signed-in email changes through credential checks and an atomic proof store."""

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from calendar_sync.application.identity.credentials import CredentialChanges, CredentialSnapshot
from calendar_sync.application.identity.email_change_admission import EmailChangeAdmission
from calendar_sync.application.identity.errors import IncorrectCredentials, IncorrectPassword
from calendar_sync.application.identity.identity_email import (
    IdentityEmailReason,
    IdentityEmailSetup,
)
from calendar_sync.application.identity.ports import PasswordHasher, UserDirectory, UserQuery
from calendar_sync.application.identity.sign_in import SetOwnEmail
from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.domain.access import User, UserId, UserState, email_address
from calendar_sync.domain.email_changes import EmailChangeMode, email_change_mode


@dataclass(frozen=True, slots=True)
class PendingEmailChange:
    id: str
    email: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PreparedEmailChange:
    recipient: str = field(repr=False)
    token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class EmailChangeCompletion:
    previous_email: str = field(repr=False)


class EmailChangeProofs(Protocol):
    def prepare(self, request_id: str) -> PreparedEmailChange | None: ...

    def purge(self, before: datetime, limit: int) -> int: ...

    def pending(self, user_id: UserId) -> PendingEmailChange | None: ...

    def request(
        self, expected: CredentialSnapshot, email: str, session: str
    ) -> PendingEmailChange: ...

    def cancel(self, user_id: UserId, request_id: str) -> None: ...

    def check(self, user_id: UserId, token: str) -> bool: ...

    def confirm(
        self, expected: CredentialSnapshot, token: str, session: str
    ) -> EmailChangeCompletion | None: ...


class EmailChangeUnavailable(ApplicationError):
    """The requested address cannot be used, without disclosing whose it is."""

    def __init__(self) -> None:
        super().__init__("Email change unavailable")


class EmailChangeProofUnusable(ApplicationError):
    """No usable proof belongs to this signed-in User."""

    def __init__(self) -> None:
        super().__init__("Email change proof is no longer usable")


class EmailChangeConfigurationRequired(ApplicationError):
    """Identity email setup is incomplete or unsafe for an emailed proof."""

    def __init__(self, reason: IdentityEmailReason) -> None:
        super().__init__("Identity email configuration required")
        self.reason = reason


class EmailChangeVerificationRequired(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Verify the new email address before changing it")


@dataclass(frozen=True, slots=True)
class EmailChangeMailRequest:
    request_id: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class EmailChangedNotice:
    recipient: str = field(repr=False)


class EmailChangeQueue(Protocol):
    def submit_change(self, request: EmailChangeMailRequest) -> bool: ...

    def submit_notice(self, notice: EmailChangedNotice) -> bool: ...


@dataclass(frozen=True, slots=True)
class EmailChangeStatus:
    mode: EmailChangeMode
    reason: IdentityEmailReason | None
    pending: PendingEmailChange | None


@dataclass(frozen=True, slots=True)
class ShowEmailChange:
    users: UserDirectory
    proofs: EmailChangeProofs
    setup: IdentityEmailSetup
    smtp_present: bool

    def initial(self, user: User) -> bool:
        if user.email is not None or not user.administers or user.state is not UserState.ACTIVE:
            return False
        first = self.users.find(UserQuery(limit=1)).users
        return bool(first and first[0].id == user.id)

    def execute(self, user_id: UserId) -> EmailChangeStatus:
        user = self.users.get(user_id)
        if user is None or user.state is not UserState.ACTIVE:
            raise IncorrectCredentials("the signed-in User is no longer active")
        mode = email_change_mode(
            self.smtp_present, self.setup.fingerprint is not None, self.initial(user)
        )
        return EmailChangeStatus(
            mode,
            self.setup.reason if mode is EmailChangeMode.UNAVAILABLE else None,
            self.proofs.pending(user_id),
        )


@dataclass(frozen=True, slots=True)
class DirectEmailChange:
    show: ShowEmailChange
    change: SetOwnEmail

    def execute(self, user_id: UserId, email: str, password: str | None) -> User:
        status = self.show.execute(user_id)
        if status.mode is EmailChangeMode.UNAVAILABLE:
            assert status.reason is not None
            raise EmailChangeConfigurationRequired(status.reason)
        if status.mode is EmailChangeMode.VERIFIED:
            raise EmailChangeVerificationRequired
        if status.pending is not None:
            raise EmailChangeUnavailable
        user = self.show.users.get(user_id)
        assert user is not None
        if user.needs_email and not self.show.initial(user):
            # Only the upgraded first administrator can have a missing email legitimately.
            raise EmailChangeUnavailable
        return self.change.execute(user_id, email, password)


def confirmed_credential(
    credentials: CredentialChanges, passwords: PasswordHasher, user_id: UserId, password: str | None
) -> CredentialSnapshot:
    expected = credentials.current(user_id)
    if expected is None:
        raise IncorrectCredentials("the signed-in User is no longer active")
    if (
        password is None
        or len(password) > 1024
        or expected.password_hash is None
        or not passwords.verify(password, expected.password_hash)
    ):
        raise IncorrectPassword("that is not your current password")
    return expected


@dataclass(frozen=True, slots=True)
class RequestEmailChange:
    show: ShowEmailChange
    credentials: CredentialChanges
    passwords: PasswordHasher
    admission: EmailChangeAdmission
    queue: EmailChangeQueue

    def execute(
        self, user_id: UserId, email: str, password: str, session: str, network: str
    ) -> None:
        self.admission.admit_request(network)
        self.admission.admit_completion(network)
        normalized = email_address(email)
        status = self.show.execute(user_id)
        fingerprint = self.show.setup.fingerprint
        if status.mode is not EmailChangeMode.VERIFIED or fingerprint is None:
            raise EmailChangeConfigurationRequired(
                self.show.setup.reason or IdentityEmailReason.SMTP_MISSING
            )
        expected = confirmed_credential(self.credentials, self.passwords, user_id, password)
        pending = self.show.proofs.request(expected, normalized, session)
        # Mail is volatile; failure cannot undo a committed request or expose delivery.
        with suppress(Exception):
            self.queue.submit_change(EmailChangeMailRequest(pending.id, fingerprint))


@dataclass(frozen=True, slots=True)
class CancelEmailChange:
    proofs: EmailChangeProofs

    def execute(self, user_id: UserId, request_id: str) -> None:
        self.proofs.cancel(user_id, request_id)


@dataclass(frozen=True, slots=True)
class CheckEmailChange:
    proofs: EmailChangeProofs
    admission: EmailChangeAdmission

    def execute(self, user_id: UserId, token: str, network: str) -> bool:
        return self.admission.check_token(network, lambda: self.proofs.check(user_id, token))


@dataclass(frozen=True, slots=True)
class ConfirmEmailChange:
    proofs: EmailChangeProofs
    credentials: CredentialChanges
    passwords: PasswordHasher
    admission: EmailChangeAdmission
    queue: EmailChangeQueue

    def execute(
        self, user_id: UserId, token: str, password: str, session: str, network: str
    ) -> None:
        self.admission.admit_completion(network)
        if not self.admission.check_token(network, lambda: self.proofs.check(user_id, token)):
            raise EmailChangeProofUnusable
        expected = confirmed_credential(self.credentials, self.passwords, user_id, password)
        result = self.proofs.confirm(expected, token, session)
        if result is None:
            raise EmailChangeProofUnusable
        # Notice failure must never turn a successful credential commit into an error.
        with suppress(Exception):
            self.queue.submit_notice(EmailChangedNotice(result.previous_email))


@dataclass(frozen=True, slots=True)
class EmailChangeServices:
    show: ShowEmailChange
    direct: DirectEmailChange
    request: RequestEmailChange
    cancel: CancelEmailChange
    check: CheckEmailChange
    confirm: ConfirmEmailChange
