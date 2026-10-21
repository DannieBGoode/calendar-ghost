"""Compose verified joining through its narrow identity contracts."""

from dataclasses import dataclass, replace
from pathlib import Path

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
from calendar_sync.application.operations.instant_sync import InstantSyncStatus
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.application.sync.watch_ports import PlanCadence
from calendar_sync.bootstrap.config import Settings
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.registration_admission import (
    SqliteRegistrationAdmission,
)
from calendar_sync.infrastructure.persistence.registration_proofs import SqliteRegistrationProofs
from calendar_sync.infrastructure.persistence.registration_readiness import (
    SqliteRegistrationReadiness,
)
from calendar_sync.infrastructure.persistence.sqlite.unit_of_work import SqliteUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.users import SqliteSessions, SqliteUserDirectory
from calendar_sync.infrastructure.persistence.watch_inbox import SqliteDeliveryEvidenceLog
from calendar_sync.infrastructure.registration_session import (
    RegistrationProviderKinds,
    RegistrationSessionReads,
)


@dataclass(frozen=True, slots=True)
class RegistrationAdapters:
    proofs: RegistrationProofs
    readiness: RegistrationReadiness
    admission: RegistrationAdmission
    fingerprint: str | None
    users: UserDirectory
    sessions: Sessions
    database: Path


@dataclass(frozen=True, slots=True)
class RegistrationServices:
    readiness: RegistrationReadiness
    request: RequestRegistration
    check: CheckRegistration
    complete: CompleteRegistration
    answers: RegistrationSessionReads


def build_registration(
    settings: Settings, ids: IdGenerator, clock: Clock, setup: IdentityEmailSetup
) -> RegistrationAdapters:
    database = settings.database_path
    return RegistrationAdapters(
        SqliteRegistrationProofs(database, ids, clock),
        SqliteRegistrationReadiness(database, setup),
        SqliteRegistrationAdmission(database, settings.master_key, clock),
        setup.fingerprint,
        SqliteUserDirectory(database, sign_in_timeout=0.1, read_timeout=0.1),
        SqliteSessions(database, clock, sign_in_timeout=0.1),
        database,
    )


def compose_registration(
    adapters: RegistrationAdapters,
    passwords: PasswordHasher,
    clock: Clock,
    queue: RegistrationEmailQueue,
    instant_status: InstantSyncStatus,
    sends_email: bool,
) -> RegistrationServices:
    return RegistrationServices(
        adapters.readiness,
        RequestRegistration(adapters.admission, adapters.readiness, queue, adapters.fingerprint),
        CheckRegistration(adapters.proofs, adapters.admission, adapters.fingerprint),
        CompleteRegistration(
            adapters.proofs,
            passwords,
            adapters.sessions,
            adapters.users,
            clock,
            adapters.admission,
            adapters.fingerprint,
        ),
        RegistrationSessionReads(
            adapters.users,
            replace(
                instant_status,
                users=adapters.users,
                unit_of_work=SqliteUnitOfWorkFactory(
                    adapters.database, clock, timeout=0.1
                ).for_user,
                cadence=PlanCadence(SqlitePlans(adapters.database, allowance_timeout=0.1)),
                evidence=SqliteDeliveryEvidenceLog(adapters.database, read_timeout=0.1),
                sources=replace(
                    instant_status.sources,
                    provider_of=RegistrationProviderKinds(adapters.database).provider_of,
                ),
            ),
            sends_email,
        ),
    )
