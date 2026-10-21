"""Independent public joining allowances; no account-dependent admission decisions."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from calendar_sync.application.shared.errors import ApplicationError


class RegistrationNetworkThrottled(ApplicationError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Registration network allowance exhausted")
        self.retry_after = retry_after


class RegistrationGlobalThrottled(ApplicationError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Registration installation allowance exhausted")
        self.retry_after = retry_after


class RegistrationAdmission(Protocol):
    def admit_front(self, client: str) -> None: ...

    def admit_durable(self, email: str, client: str) -> bool: ...

    def check_token(self, client: str, check: Callable[[], bool]) -> bool: ...

    def admit_completion(self, client: str) -> None: ...

    def purge(self, before: datetime, limit: int) -> int: ...
