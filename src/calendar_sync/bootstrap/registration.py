"""Compose verified joining through its narrow identity contracts."""

from dataclasses import dataclass

from calendar_sync.application.identity.identity_email import IdentityEmailSetup
from calendar_sync.application.identity.ports import PasswordHasher, Sessions, UserDirectory
from calendar_sync.application.identity.registration import (
    CheckRegistration,
    CompleteRegistration,
    RequestRegistration,
)
from calendar_sync.application.identity.registration_admission import RegistrationAdmission
from calendar_sync.application.identity.registration_ports import (
    RegistrationEmailQueue,
    RegistrationProofs,
    RegistrationReadiness,
)
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.bootstrap.config import Settings
from calendar_sync.infrastructure.persistence.registration_admission import (
    SqliteRegistrationAdmission,
)
from calendar_sync.infrastructure.persistence.registration_proofs import SqliteRegistrationProofs
from calendar_sync.infrastructure.persistence.registration_readiness import (
    SqliteRegistrationReadiness,
)


@dataclass(frozen=True, slots=True)
class RegistrationAdapters:
    proofs: RegistrationProofs
    readiness: RegistrationReadiness
    admission: RegistrationAdmission
    fingerprint: str | None


@dataclass(frozen=True, slots=True)
class RegistrationServices:
    readiness: RegistrationReadiness
    request: RequestRegistration
    check: CheckRegistration
    complete: CompleteRegistration


def build_registration(
    settings: Settings, ids: IdGenerator, clock: Clock, setup: IdentityEmailSetup
) -> RegistrationAdapters:
    database = settings.database_path
    return RegistrationAdapters(
        SqliteRegistrationProofs(database, ids, clock),
        SqliteRegistrationReadiness(database, setup),
        SqliteRegistrationAdmission(database, settings.master_key, clock),
        setup.fingerprint,
    )


def compose_registration(
    adapters: RegistrationAdapters,
    users: UserDirectory,
    passwords: PasswordHasher,
    sessions: Sessions,
    clock: Clock,
    queue: RegistrationEmailQueue,
) -> RegistrationServices:
    return RegistrationServices(
        adapters.readiness,
        RequestRegistration(adapters.admission, adapters.readiness, queue, adapters.fingerprint),
        CheckRegistration(adapters.proofs, adapters.admission, adapters.fingerprint),
        CompleteRegistration(
            adapters.proofs,
            passwords,
            sessions,
            users,
            clock,
            adapters.admission,
            adapters.fingerprint,
        ),
    )
