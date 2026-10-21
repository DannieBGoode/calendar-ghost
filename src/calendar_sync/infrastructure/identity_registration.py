"""Bounded registration maintenance, including optional provider proof stores."""

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime

from calendar_sync.application.identity.provider_sign_in_ports import ProviderFlowMaintenance
from calendar_sync.application.identity.registration import DeliverRegistration
from calendar_sync.application.identity.registration_admission import RegistrationAdmission
from calendar_sync.application.identity.registration_ports import RegistrationProofs


@dataclass(frozen=True, slots=True)
class RegistrationMaintenance:
    delivery: DeliverRegistration | None
    proofs: RegistrationProofs
    admission: RegistrationAdmission
    provider_stores: tuple[ProviderFlowMaintenance, ...] = ()

    def purge(self, before: datetime, limit: int) -> bool:
        half = max(0, min(limit, 500)) // 2
        if not half:
            return False
        more = False
        stores: tuple[ProviderFlowMaintenance, ...] = (
            self.proofs,
            self.admission,
            *self.provider_stores,
        )
        for store in stores:
            with suppress(Exception):
                more = store.purge(before, half) == half or more
        return more
