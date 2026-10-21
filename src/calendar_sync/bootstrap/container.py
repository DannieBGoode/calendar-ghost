from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime

from calendar_sync.application.identity.credentials import CredentialChanges
from calendar_sync.application.identity.password_reset import SelfServicePasswordResets
from calendar_sync.application.identity.ports import (
    IntegrationTokenAuthentication,
    IntegrationTokens,
    Invitations,
    PasswordHasher,
    PasswordResetLinks,
    PlanAssignments,
    PlanCatalog,
    RegistrationSettings,
    Sessions,
    SignInThrottle,
    UserDirectory,
)
from calendar_sync.application.identity.reset_admission import ResetAdmission
from calendar_sync.application.operations.activity import (
    ActivityQueries,
    OperationsQueries,
)
from calendar_sync.application.operations.installation_health import (
    GetInstallationHealth,
    HintSources,
    InstallationIncidentWatch,
    InstallationNotifications,
)
from calendar_sync.application.operations.instant_sync import (
    InstantSyncStatus,
    WatchedSources,
)
from calendar_sync.application.operations.operator_overview import OperatorOverview, UserStatuses
from calendar_sync.application.operations.ports import (
    CauseSighting,
    DatabaseStorage,
    InstallationUnitOfWorkFactory,
    LogFiles,
    WatchNoticeInbox,
)
from calendar_sync.application.operations.scheduled_pass import ScheduledPass
from calendar_sync.application.operations.storage import StorageAdministration
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.application.sync.account_ports import (
    AccountCalendars,
    ConnectedAccountRepository,
)
from calendar_sync.application.sync.health_ports import (
    IncidentNotifications,
    IncidentRepository,
    RuleHealthRecords,
)
from calendar_sync.application.sync.instant_sync import (
    AccountBackoff,
)
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.manual_runs import RunThrottle
from calendar_sync.application.sync.plan_holds import (
    PlanNotices,
    SettleLocks,
)
from calendar_sync.application.sync.plan_ports import Allowances
from calendar_sync.application.sync.ports import UnitOfWorkFactory
from calendar_sync.application.sync.provider_descriptors import ProviderDirectory
from calendar_sync.application.sync.provider_ports import CalendarProvider
from calendar_sync.application.sync.run_log import UntalliedProviderCalls
from calendar_sync.application.sync.run_ports import ProviderCallStats, RunIdGenerator
from calendar_sync.application.sync.watch_ports import (
    DeliveryEvidenceLog,
    EveryUserInstant,
    NoticeReader,
    PlanCadence,
    SyncCadencePolicy,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.identity import (
    AdministrationServices,
    IdentityServices,
    _administration,
    _identity,
    _owned_rules,
)
from calendar_sync.bootstrap.identity_email import (
    IdentityEmailAdapters,
    IdentityEmailServices,
    _UnavailableQueue,
    build_identity_email,
    build_reset_admission,
    compose_identity_mail,
)
from calendar_sync.bootstrap.logs import configure_logging
from calendar_sync.bootstrap.operations import (
    PlanServices,
    _installation_notifier,
    _instant_sync,
    _instant_sync_signals,
    _InstantSync,
    _notice_readers,
    _plan_services,
    _scheduled_services,
)
from calendar_sync.bootstrap.registration import RegistrationServices, compose_registration
from calendar_sync.bootstrap.shared import (
    UserServices,
    _mail_server,
    instant_sync_address,
    public_address,
)
from calendar_sync.bootstrap.sync import _compose_user, _no_provider, calendar_providers
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import SCHEDULED_EVERY
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.identifiers import UuidIdGenerator, UuidRunIdGenerator
from calendar_sync.infrastructure.identity_front_gate import client_network
from calendar_sync.infrastructure.identity_mail_worker import IdentityMailWorker
from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
from calendar_sync.infrastructure.log_files import RotatingLogFiles
from calendar_sync.infrastructure.notifications import (
    OwnerNotifier,
)
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.activity_queries import (
    SqliteActivityQueries,
    SqliteOperationsQueries,
)
from calendar_sync.infrastructure.persistence.credentials import SqliteCredentialChanges
from calendar_sync.infrastructure.persistence.health import (
    SqliteIncidentRepository,
    SqliteRuleHealthRecords,
)
from calendar_sync.infrastructure.persistence.installation import (
    SqliteInstallationUnitOfWorkFactory,
)
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.registration import (
    SqliteInvitations,
    SqlitePasswordResetLinks,
    SqliteRegistrationSettings,
)
from calendar_sync.infrastructure.persistence.sqlite.unit_of_work import SqliteUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.storage import SqliteStorage
from calendar_sync.infrastructure.persistence.users import SqliteSessions, SqliteUserDirectory
from calendar_sync.infrastructure.persistence.watch_inbox import (
    SqliteDeliveryEvidenceLog,
    SqliteWatchNoticeInbox,
)
from calendar_sync.infrastructure.provider_calls import ContextProviderCallStats
from calendar_sync.infrastructure.providers.routing import (
    RoutingAccountCalendars,
    RoutingCalendarProvider,
    RoutingCalendarWatcher,
)
from calendar_sync.infrastructure.scheduling import (
    InstantSyncDispatcher,
    SchedulerWatch,
    SyncScheduler,
    WatchKeeper,
)
from calendar_sync.infrastructure.security import CredentialCipher, HistoryCipher, ScryptPasswords
from calendar_sync.infrastructure.throttle import MemoryRunThrottle, MemorySignInThrottle


@dataclass(frozen=True, slots=True)
class Container:
    """What the Web API reads: installation-wide services, and each User's through `for_user`."""

    secure_cookies: bool
    providers: ProviderDirectory
    """Every calendar provider this release knows, and how Users connect the configured ones."""
    identity: IdentityServices
    identity_email: IdentityEmailServices
    registrations: RegistrationServices
    identity_mail_worker: IdentityMailWorker | None
    reset_admission: ResetAdmission
    reset_client_network: Callable[[str], str]
    administration: AdministrationServices
    plans: PlanServices
    token_authentication: IntegrationTokenAuthentication
    storage: StorageAdministration
    account_calendars: AccountCalendars | None
    scheduler: SyncScheduler | None
    scheduler_watch: SchedulerWatch | None
    """Tells the installation's channels when the scheduler stops completing passes."""
    installation_health: GetInstallationHealth
    operator_overview: OperatorOverview
    """Every User's health for administrators, and what it shows about each User to them."""
    sends_email: bool
    """Whether Incident Notifications can also reach each User by email."""
    instant_dispatcher: InstantSyncDispatcher | None
    """Starts rules' instant runs; None unless the installation can offer Instant Sync."""
    watch_keeper: WatchKeeper | None
    """Keeps every User's Calendar Watches; None unless the installation can offer Instant Sync."""
    watch_inbox: WatchNoticeInbox | None
    """Records Watch Notices; None unless the installation can offer Instant Sync, so the notice
    route answers as for an unknown path."""
    notice_readers: Mapping[str, tuple[ProviderKind, NoticeReader]]
    """Each provider's notice reader, by the slug in its notice address."""
    instant_sync_status: InstantSyncStatus
    instant_sync_address: str | None
    """The public https address providers deliver Watch Notices to; None when there is none."""
    user_services: Callable[[UserId], UserServices]

    def for_user(self, user_id: UserId) -> UserServices:
        return self.user_services(user_id)


@dataclass(frozen=True, slots=True)
class Adapters:
    """The adapters one installation's use cases are composed from.

    Those holding Users' records are made per User, so a use case receives only its User's.
    `build_adapters` makes them from Settings; tests and the development preview substitute some
    before `compose` wires the use cases.
    """

    unit_of_work: Callable[[UserId], UnitOfWorkFactory]
    installation_units: InstallationUnitOfWorkFactory
    """Only the scheduler and the Operator Overview read across Users (ADR 0029)."""
    locks: RuleLocks
    clock: Clock
    ids: IdGenerator
    run_ids: RunIdGenerator
    users: UserDirectory
    sessions: Sessions
    passwords: PasswordHasher
    sign_in_throttle: SignInThrottle
    link_throttle: SignInThrottle
    """Unusable Invitation and Password Reset Links per client, apart from failed sign-ins."""
    run_throttle: RunThrottle
    """One per process: each User's manual runs, counted across their requests."""
    identity_email: IdentityEmailAdapters
    reset_admission: ResetAdmission
    registration: RegistrationSettings
    invitations: Invitations
    password_resets: PasswordResetLinks
    self_service_resets: SelfServicePasswordResets
    credential_changes: CredentialChanges
    activity: Callable[[UserId], ActivityQueries]
    operations: Callable[[UserId], OperationsQueries]
    health_records: Callable[[UserId], RuleHealthRecords]
    incidents: Callable[[UserId], IncidentRepository]
    database_storage: DatabaseStorage
    integration_tokens: Callable[[UserId], IntegrationTokens]
    token_authentication: IntegrationTokenAuthentication
    delivery_evidence: DeliveryEvidenceLog
    """Whether each provider's Watch Notices reach the installation's address."""
    watch_inbox: WatchNoticeInbox
    allowances: Allowances
    """What each User may use now, as their Plan allows (ADR 0038)."""
    plan_catalog: PlanCatalog
    plan_assignments: PlanAssignments
    """The one way a User's own Plan changes: administrators now, billing later."""
    notifications: Callable[[UserId], IncidentNotifications | None] = lambda _owner: None
    """Each User's own Incident Notifications, by email when the installation sends it."""
    plan_notices: Callable[[UserId], PlanNotices | None] = lambda _owner: None
    installation_notifications: InstallationNotifications | None = None
    """The installation's SMTP recipient and webhook, which hear only installation incidents."""
    sends_email: bool = False
    accounts: Callable[[UserId], ConnectedAccountRepository] | None = None
    providers: ProviderDirectory = field(default_factory=ProviderDirectory)
    """Each calendar provider's descriptor: its names, troubleshooting sections, connection flow,
    and adapters (ADR 0022)."""
    account_calendars: AccountCalendars | None = None
    """Lists each account's calendars through its provider's adapter."""
    watchers: RoutingCalendarWatcher | None = None
    """Each account's provider's Calendar Watcher, where accounts can be stored."""
    sync_cadence: SyncCadencePolicy = field(default_factory=EveryUserInstant)
    """Each User's Sync Cadence. `build_adapters` reads it from each User's Plan (`PlanCadence`,
    ADR 0038); this default gives every User Instant Sync, as Plans off does (ADR 0028)."""
    watch_backoff: AccountBackoff = field(default_factory=AccountBackoff)
    """One per process: how long each account waits before upkeep asks its provider again,
    shared by every User's upkeep."""
    calendar_provider: CalendarProvider | None = None
    call_stats: ProviderCallStats = field(default_factory=UntalliedProviderCalls)
    """Counts the calendar provider's calls for each run's log lines."""
    log_files: LogFiles | None = None


def build_container(settings: Settings | None = None) -> Container:
    resolved = settings or Settings.from_environment()
    return compose(resolved, build_adapters(resolved))


def service_container() -> Container:
    """The running service's container, configured from the environment.

    Logging is configured first, so every line the service writes follows the configured level.
    """
    settings = Settings.from_environment()
    log_files = (
        RotatingLogFiles(settings.log_directory) if settings.log_directory is not None else None
    )
    # A directory that cannot be used leaves file logging off, and Settings must say so.
    if not configure_logging(settings.log_level, log_files):
        log_files = None
    return compose(settings, replace(build_adapters(settings), log_files=log_files))


def build_adapters(settings: Settings) -> Adapters:
    database = settings.database_path
    initialize_database(database)
    # One clock and one identifier source, shared by every adapter and use case.
    clock = SystemClock()
    ids = UuidIdGenerator()
    # Source Change values are sealed with a key derived from the master key (ADR 0017).
    history = HistoryCipher(settings.master_key) if settings.master_key else None
    tokens = SqliteIntegrationTokens(database, clock, ids)
    users = SqliteUserDirectory(database)
    plans = SqlitePlans(database)
    mail = _mail_server(settings)
    resets = SqlitePasswordResetLinks(database, ids, clock)
    adapters = Adapters(
        identity_email=build_identity_email(settings, ids, clock),
        reset_admission=build_reset_admission(settings, clock),
        unit_of_work=SqliteUnitOfWorkFactory(database, clock, history).for_user,
        installation_units=SqliteInstallationUnitOfWorkFactory(database),
        locks=RuleLocks(),
        clock=clock,
        ids=ids,
        run_ids=UuidRunIdGenerator(),
        users=users,
        sessions=SqliteSessions(database, clock),
        passwords=ScryptPasswords(),
        sign_in_throttle=MemorySignInThrottle(clock),
        link_throttle=MemorySignInThrottle(clock),
        run_throttle=MemoryRunThrottle(clock),
        registration=SqliteRegistrationSettings(database, clock),
        invitations=SqliteInvitations(database, ids, clock),
        password_resets=resets,
        self_service_resets=resets,
        credential_changes=SqliteCredentialChanges(database, clock),
        activity=lambda user: SqliteActivityQueries(database, user, history),
        operations=lambda user: SqliteOperationsQueries(database, user),
        health_records=lambda user: SqliteRuleHealthRecords(database, user),
        incidents=lambda user: SqliteIncidentRepository(database, user, ids),
        database_storage=SqliteStorage(database),
        integration_tokens=tokens.for_user,
        token_authentication=tokens,
        delivery_evidence=SqliteDeliveryEvidenceLog(database),
        watch_inbox=SqliteWatchNoticeInbox(database),
        allowances=plans,
        plan_catalog=plans,
        plan_assignments=plans,
        notifications=lambda owner: (
            OwnerNotifier(users, owner, mail, public_address(settings)) if mail else None
        ),
        plan_notices=lambda owner: (
            OwnerNotifier(users, owner, mail, public_address(settings)) if mail else None
        ),
        installation_notifications=_installation_notifier(settings, mail),
        sends_email=mail is not None,
        sync_cadence=PlanCadence(plans),
    )
    # Connecting a new account stays within its User's Plan (ADR 0038).
    accounts = (
        SqliteConnectedAccountStore(
            database, CredentialCipher(settings.master_key), clock, ids, allowances=plans
        )
        if settings.master_key
        else None
    )
    providers = calendar_providers(settings, accounts, clock)
    if accounts is None:
        return replace(adapters, providers=providers)
    return replace(
        adapters,
        accounts=accounts.for_user,
        providers=providers,
        account_calendars=RoutingAccountCalendars.of(accounts, providers),
        calendar_provider=RoutingCalendarProvider.of(accounts, providers),
        watchers=RoutingCalendarWatcher.of(accounts, providers),
        call_stats=ContextProviderCallStats(),
    )


def compose(settings: Settings, adapters: Adapters) -> Container:
    settle_locks = SettleLocks()

    def user_services(user_id: UserId) -> UserServices:
        # Read when called, after the scheduler exists: every User's status reads its heartbeat.
        return _compose_user(user_id, adapters, scheduler, instant_status, settle_locks)

    cadence = adapters.sync_cadence
    scheduled_pass = ScheduledPass(
        adapters.installation_units,
        lambda owner: _scheduled_services(user_services(owner)),
        adapters.clock,
        cadence=cadence,
        # PR 3 activates this only with visible grace, holds, and keep choice recovery.
        plan_holds=None,
    )
    runs_rules = adapters.calendar_provider is not None and adapters.accounts is not None
    scheduler = (
        SyncScheduler(
            scheduled_pass,
            interval_seconds=int(SCHEDULED_EVERY.total_seconds()),
            clock=adapters.clock,
        )
        if runs_rules
        else None
    )
    address = instant_sync_address(settings) if runs_rules else None
    instant_status = InstantSyncStatus(
        adapters.users,
        adapters.unit_of_work,
        cadence,
        adapters.delivery_evidence,
        WatchedSources(
            adapters.watchers.provider_of if adapters.watchers is not None else _no_provider,
            adapters.watch_backoff.known_unwatchable,
        ),
        address,
        adapters.clock,
    )
    instant = (
        _instant_sync(adapters, scheduled_pass, user_services, cadence, address)
        if address is not None
        else _InstantSync()
    )
    # Installation Health counts the verdicts People shows, so the two never disagree.
    statuses = UserStatuses(adapters.installation_units, adapters.locks, adapters.clock, scheduler)
    overview = OperatorOverview(
        adapters.users,
        statuses,
        adapters.installation_units,
        adapters.clock,
        adapters.allowances,
        adapters.plan_catalog,
        adapters.plan_assignments,
    )
    identity_email, identity_mail_worker = compose_identity_mail(adapters)
    return Container(
        identity_email=identity_email,
        registrations=compose_registration(
            adapters.identity_email.registrations,
            adapters.users,
            adapters.passwords,
            adapters.sessions,
            adapters.clock,
            identity_mail_worker or _UnavailableQueue(),
        ),
        identity_mail_worker=identity_mail_worker,
        reset_admission=adapters.reset_admission,
        reset_client_network=client_network,
        secure_cookies=settings.secure_cookies,
        providers=adapters.providers,
        identity=_identity(adapters),
        administration=_administration(
            adapters, lambda owner: _owned_rules(owner, adapters, user_services(owner))
        ),
        plans=_plan_services(adapters, overview),
        token_authentication=adapters.token_authentication,
        storage=StorageAdministration(
            adapters.database_storage, adapters.locks, adapters.clock, adapters.log_files
        ),
        account_calendars=adapters.account_calendars,
        scheduler=scheduler,
        scheduler_watch=(
            SchedulerWatch(
                scheduler,
                adapters.installation_notifications,
                adapters.clock,
                incidents=InstallationIncidentWatch(adapters.providers.client_secrets),
            )
            if scheduler is not None and adapters.installation_notifications is not None
            else None
        ),
        installation_health=GetInstallationHealth(
            adapters.users,
            lambda users: {user: status.health for user, status in statuses.of(users).items()},
            scheduler,
            adapters.clock,
            HintSources(
                _failure_causes(adapters.installation_units),
                adapters.providers.guides,
                _instant_sync_signals(adapters, public_address(settings)),
            ),
            adapters.providers.client_secrets,
        ),
        operator_overview=overview,
        sends_email=adapters.sends_email,
        instant_dispatcher=instant.dispatcher,
        watch_keeper=instant.keeper,
        watch_inbox=instant.inbox,
        notice_readers=_notice_readers(adapters.providers),
        instant_sync_status=instant_status,
        instant_sync_address=address,
        user_services=user_services,
    )


def _failure_causes(
    installation: InstallationUnitOfWorkFactory,
) -> Callable[[datetime], Sequence[CauseSighting]]:
    """Every User's failures with a Cause from a time on, for Installation Hints."""

    def read(since: datetime) -> Sequence[CauseSighting]:
        with installation() as reading:
            return reading.failure_causes(since)

    return read
