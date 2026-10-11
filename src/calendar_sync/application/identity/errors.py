"""Errors of identity and access."""

from __future__ import annotations

from calendar_sync.application.shared.errors import ApplicationError


class AdminAlreadyConfigured(ApplicationError):
    """The installation already has its first User."""


class PasswordPolicyViolation(ApplicationError):
    """A proposed password is too weak."""


class IncorrectCredentials(ApplicationError):
    """No User signs in with this email and password; which part was wrong is not said."""


class IncorrectPassword(ApplicationError):
    """The signed-in User's current password, asked for to confirm a change, is wrong."""


class SignInThrottled(ApplicationError):
    """Too many failed sign-ins for this email or from this client; try again later."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = max(1, round(retry_after))
        super().__init__(f"too many failed sign-ins; try again in {self.retry_after} seconds")


class UserDisabled(ApplicationError):
    """An Installation Administrator has stopped this User from signing in."""


class EmailTaken(ApplicationError):
    """Another User already signs in with this email."""


class EmailRequired(ApplicationError):
    """The User must add an email before anything else."""


class InvalidIntegrationTokenName(ValueError):
    """An Integration Token name must be 1 to 80 printable characters."""
