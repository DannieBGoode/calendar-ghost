"""Failures from admitting an email-change request or proof attempt."""

from calendar_sync.application.shared.errors import ApplicationError, InfrastructureFailure


class EmailChangeThrottled(ApplicationError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Email change allowance exhausted")
        self.retry_after = retry_after


class EmailChangeStorageUnavailable(InfrastructureFailure):
    def __init__(self) -> None:
        super().__init__("Email change storage unavailable")
