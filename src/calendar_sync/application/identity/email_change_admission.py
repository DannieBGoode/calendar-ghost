"""Failures from admitting an email-change request or proof attempt."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from calendar_sync.application.shared.errors import ApplicationError, InfrastructureFailure


class EmailChangeThrottled(ApplicationError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Email change allowance exhausted")
        self.retry_after = retry_after


class EmailChangeStorageUnavailable(InfrastructureFailure):
    def __init__(self) -> None:
        super().__init__("Email change storage unavailable")


class EmailChangeAdmission(Protocol):
    """Independent bounded request, invalid-proof and password-submission allowances."""

    def admit_request(self, network: str) -> None: ...

    def check_token(self, network: str, check: Callable[[], bool]) -> bool: ...

    def admit_completion(self, network: str) -> None: ...

    def purge(self, before: datetime, limit: int) -> int: ...
