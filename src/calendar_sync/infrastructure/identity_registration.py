"""Bounded independent registration proof and admission maintenance."""

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime

from calendar_sync.application.identity.registration import DeliverRegistration
from calendar_sync.application.identity.registration_admission import RegistrationAdmission
from calendar_sync.application.identity.registration_ports import RegistrationProofs


@dataclass(frozen=True, slots=True)
class RegistrationMaintenance:
    delivery: DeliverRegistration | None
    proofs: RegistrationProofs
    admission: RegistrationAdmission

    def purge(self, before: datetime, limit: int) -> bool:
        half = max(0, min(limit, 500)) // 2
        if not half:
            return False
        more = False
        for store in (self.proofs, self.admission):
            with suppress(Exception):
                more = store.purge(before, half) == half or more
        return more
