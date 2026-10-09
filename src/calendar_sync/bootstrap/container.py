from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from calendar_sync.application.accounts import (
    CheckAccountAccess,
    DeleteConnectedAccount,
    DisconnectConnectedAccount,
    DiscoverCalendars,
    ListConnectedAccounts,
)
from calendar_sync.application.activity import (
    ActivityQueries,
    InspectActivityEvent,
    OperationsQueries,
)
from calendar_sync.application.health import RuleHealth
from calendar_sync.application.identity import (
    ChangeOwnPassword,
    SetOwnEmail,
    SetUpInstallation,
    SignIn,
)
from calendar_sync.application.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    AccountAuthorization,
    AccountCalendars,
    CalendarProvider,
    Clock,
    ConnectedAccountRepository,
    DatabaseStorage,
    IdGenerator,
    IncidentNotifications,
    IncidentRepository,
    InstallationUnitOfWorkFactory,
    IntegrationTokenAuthentication,
    IntegrationTokens,
    LogFiles,
    PasswordHasher,
    ProviderCallStats,
    RuleHealthRecords,
    RunIdGenerator,
    SchedulerHeartbeat,
    Sessions,
    SignInThrottle,
    UnitOfWorkFactory,
    UserDirectory,
)
from calendar_sync.application.preview import PreviewSyncRule
from calendar_sync.application.providers import ProviderKind
from calendar_sync.application.reconciliation import ReconcileNow, ReconcileSyncRule
from calendar_sync.application.removal import RemoveSyncRule
from calendar_sync.application.rules import (
    ChangeSyncRulePolicy,
    CreateDraftSyncRule,
    CreateSyncRule,
    EnableSyncRule,
    GetSyncRuleDetails,
    ListSyncRules,
    PauseSyncRule,
    ReplaceSyncRuleCalendars,
)
from calendar_sync.application.run_log import UntalliedProviderCalls
from calendar_sync.application.status import GetInstallationStatus
from calendar_sync.application.storage import StorageAdministration
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.logs import configure_logging
from calendar_sync.domain.access import UserId
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    ReconciliationService,
    SyncDecisionService,
)
from calendar_sync.infrastructure.google.oauth import GoogleOAuthService, OAuthClientConfig
from calendar_sync.infrastructure.google.provider import GoogleCalendarProvider
from calendar_sync.infrastructure.identifiers import UuidIdGenerator, UuidRunIdGenerator
from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
from calendar_sync.infrastructure.log_files import RotatingLogFiles
from calendar_sync.infrastructure.notifications import (
    IncidentNotifier,
    NotificationChannel,
    SmtpChannel,
    WebhookChannel,
)
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.activity_queries import (
    SqliteActivityQueries,
    SqliteOperationsQueries,
)
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.persistence.health import (
    SqliteIncidentRepository,
    SqliteRuleHealthRecords,
)
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteInstallationUnitOfWorkFactory,
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.persistence.storage import SqliteStorage
from calendar_sync.infrastructure.persistence.users import SqliteSessions, SqliteUserDirectory
from calendar_sync.infrastructure.provider_calls import ContextProviderCallStats
from calendar_sync.infrastructure.providers.routing import (
    RoutingAccountCalendars,
    RoutingCalendarProvider,
)
from calendar_sync.infrastructure.scheduling import (
    ScheduledServices,
    SyncScheduler,
    SystemClock,
)
from calendar_sync.infrastructure.security import CredentialCipher, HistoryCipher, ScryptPasswords
from calendar_sync.infrastructure.throttle import MemorySignInThrottle


@dataclass(frozen=True, slots=True)
class GoogleConnectionStatus:
    configured: bool
    redirect_uri: str | None
    """Shown only when configured, so the administrator can register it with Google."""


@dataclass(frozen=True, slots=True)
class UserServices:
    """The use cases one User's requests call. Each sees only that User's records (ADR 0029)."""

    user_id: UserId
    activity: ActivityQueries
    operations: OperationsQueries
    get_installation_status: GetInstallationStatus
    integration_tokens: IntegrationTokens
    inspect_activity_event: InspectActivityEvent
    list_sync_rules: ListSyncRules
    create_draft_rule: CreateDraftSyncRule
    enable_sync_rule: EnableSyncRule
    pause_sync_rule: PauseSyncRule
    change_sync_rule_policy: ChangeSyncRulePolicy
    get_sync_rule_details: GetSyncRuleDetails
    remove_sync_rule: RemoveSyncRule
    replace_sync_rule_calendars: ReplaceSyncRuleCalendars
    rule_health: RuleHealth
    lapsed_authorizations: LapsedAuthorizations
    # Each of these needs the installation master key, and synchronization also Google.
    list_connected_accounts: ListConnectedAccounts | None
    disconnect_connected_account: DisconnectConnectedAccount | None
    delete_connected_account: DeleteConnectedAccount | None
    check_account_access: CheckAccountAccess | None
    discover_calendars: DiscoverCalendars | None
    execute_sync_rule: ExecuteSyncRule | None
    preview_sync_rule: PreviewSyncRule | None
    reconcile_now: ReconcileNow | None


@dataclass(frozen=True, slots=True)
class IdentityServices:
    """Who is signed in: setup, sign-in, sessions, and a User's own credentials."""

    users: UserDirectory
    sessions: Sessions
    set_up: SetUpInstallation
    sign_in: SignIn
    set_own_email: SetOwnEmail
    change_own_password: ChangeOwnPassword


@dataclass(frozen=True, slots=True)
class Container:
    """What the Web API reads: installation-wide services, and each User's through `for_user`."""

    secure_cookies: bool
    google: GoogleConnectionStatus
    identity: IdentityServices
    token_authentication: IntegrationTokenAuthentication
    storage: StorageAdministration
    authorization: AccountAuthorization | None
    account_calendars: AccountCalendars | None
    scheduler: SyncScheduler | None
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
    """Only the scheduler reads across Users (ADR 0029)."""
    locks: RuleLocks
    clock: Clock
    ids: IdGenerator
    run_ids: RunIdGenerator
    users: UserDirectory
    sessions: Sessions
    passwords: PasswordHasher
    sign_in_throttle: SignInThrottle
    activity: Callable[[UserId], ActivityQueries]
    operations: Callable[[UserId], OperationsQueries]
    health_records: Callable[[UserId], RuleHealthRecords]
    incidents: Callable[[UserId], IncidentRepository]
    database_storage: DatabaseStorage
    integration_tokens: Callable[[UserId], IntegrationTokens]
    token_authentication: IntegrationTokenAuthentication
    notifications: IncidentNotifications | None = None
    accounts: Callable[[UserId], ConnectedAccountRepository] | None = None
    authorization: AccountAuthorization | None = None
    """Connects and reauthorizes accounts through the provider's OAuth flow."""
    account_calendars: AccountCalendars | None = None
    """Lists each account's calendars through its provider's adapter."""
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
    adapters = Adapters(
        unit_of_work=SqliteUnitOfWorkFactory(database, clock, history).for_user,
        installation_units=SqliteInstallationUnitOfWorkFactory(database),
        locks=RuleLocks(),
        clock=clock,
        ids=ids,
        run_ids=UuidRunIdGenerator(),
        users=SqliteUserDirectory(database),
        sessions=SqliteSessions(database, clock),
        passwords=ScryptPasswords(),
        sign_in_throttle=MemorySignInThrottle(clock),
        activity=lambda user: SqliteActivityQueries(database, user, history),
        operations=lambda user: SqliteOperationsQueries(database, user),
        health_records=lambda user: SqliteRuleHealthRecords(database, user),
        incidents=lambda user: SqliteIncidentRepository(database, user, ids),
        database_storage=SqliteStorage(database),
        integration_tokens=tokens.for_user,
        token_authentication=tokens,
    )
    if not settings.master_key:
        return adapters
    accounts = SqliteConnectedAccountStore(
        database, CredentialCipher(settings.master_key), clock, ids
    )
    google_oauth = GoogleOAuthService(
        OAuthClientConfig(
            settings.google_client_id,
            settings.google_client_secret,
            settings.google_redirect_uri,
        ),
        accounts,
        SqliteAuthorizationStates(database, clock),
        verifier_key=settings.master_key,
    )
    return replace(
        adapters,
        accounts=accounts.for_user,
        authorization=google_oauth,
        account_calendars=RoutingAccountCalendars(accounts, {ProviderKind.GOOGLE: google_oauth}),
        calendar_provider=RoutingCalendarProvider(
            accounts,
            {ProviderKind.GOOGLE: GoogleCalendarProvider(google_oauth.service_for, clock)},
        ),
        call_stats=ContextProviderCallStats(),
        notifications=_notifier(settings),
    )


def compose(settings: Settings, adapters: Adapters) -> Container:
    def user_services(user_id: UserId) -> UserServices:
        # Read when called, after the scheduler exists: every User's status reads its heartbeat.
        return _compose_user(user_id, adapters, scheduler)

    scheduler = (
        SyncScheduler(
            adapters.installation_units,
            lambda owner: _scheduled_services(user_services(owner)),
            clock=adapters.clock,
        )
        if adapters.calendar_provider is not None and adapters.accounts is not None
        else None
    )
    google_configured = bool(
        adapters.authorization and settings.google_client_id and settings.google_client_secret
    )
    return Container(
        secure_cookies=settings.secure_cookies,
        google=GoogleConnectionStatus(
            configured=google_configured,
            redirect_uri=settings.google_redirect_uri if google_configured else None,
        ),
        identity=_identity(adapters),
        token_authentication=adapters.token_authentication,
        storage=StorageAdministration(
            adapters.database_storage, adapters.locks, adapters.clock, adapters.log_files
        ),
        authorization=adapters.authorization,
        account_calendars=adapters.account_calendars,
        scheduler=scheduler,
        user_services=user_services,
    )


def _identity(adapters: Adapters) -> IdentityServices:
    users, passwords, sessions = adapters.users, adapters.passwords, adapters.sessions
    return IdentityServices(
        users=users,
        sessions=sessions,
        set_up=SetUpInstallation(users, passwords, sessions, adapters.ids, adapters.clock),
        sign_in=SignIn(users, passwords, sessions, adapters.sign_in_throttle, adapters.clock),
        set_own_email=SetOwnEmail(users, passwords),
        change_own_password=ChangeOwnPassword(users, passwords, sessions),
    )


def _scheduled_services(services: UserServices) -> ScheduledServices:
    assert services.execute_sync_rule is not None
    return ScheduledServices(services.execute_sync_rule, services.rule_health)


def _compose_user(
    user_id: UserId, adapters: Adapters, heartbeat: SchedulerHeartbeat | None
) -> UserServices:
    unit_of_work, locks, clock = adapters.unit_of_work(user_id), adapters.locks, adapters.clock
    provider = adapters.calendar_provider
    accounts = adapters.accounts(user_id) if adapters.accounts is not None else None
    operations = adapters.operations(user_id)
    create_sync_rule = CreateSyncRule(unit_of_work)
    list_sync_rules = ListSyncRules(unit_of_work, locks)
    rule_health = RuleHealth(
        unit_of_work,
        adapters.health_records(user_id),
        adapters.incidents(user_id),
        clock,
        locks,
        adapters.notifications,
    )
    call_stats = adapters.call_stats
    remove_sync_rule = RemoveSyncRule(
        unit_of_work, provider, accounts, clock, locks, incidents=rule_health, call_stats=call_stats
    )
    execute_sync_rule = preview_sync_rule = reconcile_now = None
    if provider is not None and accounts is not None:
        fingerprinter = ProjectionFingerprinter()
        projector = EventProjector()
        decisions = SyncDecisionService(projector, fingerprinter)
        execute_sync_rule = ExecuteSyncRule(
            unit_of_work,
            provider,
            decisions,
            fingerprinter,
            clock,
            adapters.run_ids,
            locks,
            call_stats=call_stats,
        )
        preview_sync_rule = PreviewSyncRule(
            unit_of_work, provider, projector, clock, decisions, locks, incidents=rule_health
        )
        reconcile_now = ReconcileNow(
            execute_sync_rule,
            ReconcileSyncRule(
                unit_of_work,
                provider,
                projector,
                ReconciliationService(fingerprinter),
                clock,
                adapters.run_ids,
                locks,
                call_stats=call_stats,
            ),
            rule_health,
        )
    calendars = adapters.account_calendars
    return UserServices(
        user_id=user_id,
        activity=adapters.activity(user_id),
        operations=operations,
        get_installation_status=GetInstallationStatus(
            list_sync_rules, operations, clock, heartbeat
        ),
        integration_tokens=adapters.integration_tokens(user_id),
        inspect_activity_event=InspectActivityEvent(
            adapters.activity(user_id), unit_of_work, provider
        ),
        list_sync_rules=list_sync_rules,
        create_draft_rule=CreateDraftSyncRule(create_sync_rule, adapters.ids),
        enable_sync_rule=EnableSyncRule(unit_of_work, locks),
        pause_sync_rule=PauseSyncRule(unit_of_work, locks),
        change_sync_rule_policy=ChangeSyncRulePolicy(unit_of_work, clock, locks),
        get_sync_rule_details=GetSyncRuleDetails(unit_of_work, locks),
        remove_sync_rule=remove_sync_rule,
        replace_sync_rule_calendars=ReplaceSyncRuleCalendars(
            unit_of_work, remove_sync_rule, create_sync_rule, adapters.ids
        ),
        rule_health=rule_health,
        lapsed_authorizations=rule_health.lapses,
        list_connected_accounts=(
            ListConnectedAccounts(unit_of_work, accounts) if accounts else None
        ),
        disconnect_connected_account=(
            DisconnectConnectedAccount(unit_of_work, accounts, locks) if accounts else None
        ),
        delete_connected_account=(
            DeleteConnectedAccount(unit_of_work, locks) if accounts else None
        ),
        check_account_access=(
            CheckAccountAccess(calendars, accounts, rule_health.lapses)
            if calendars and accounts
            else None
        ),
        discover_calendars=DiscoverCalendars(calendars, unit_of_work) if calendars else None,
        execute_sync_rule=execute_sync_rule,
        preview_sync_rule=preview_sync_rule,
        reconcile_now=reconcile_now,
    )


def _notifier(settings: Settings) -> IncidentNotifier | None:
    channels: list[NotificationChannel] = []
    if settings.incident_webhook_url:
        channels.append(WebhookChannel(settings.incident_webhook_url))
    if settings.smtp_host and settings.smtp_sender and settings.smtp_recipient:
        channels.append(
            SmtpChannel(
                host=settings.smtp_host,
                port=settings.smtp_port,
                sender=settings.smtp_sender,
                recipient=settings.smtp_recipient,
                username=settings.smtp_username,
                password=settings.smtp_password,
                use_starttls=settings.smtp_starttls,
            )
        )
    return IncidentNotifier(channels) if channels else None
