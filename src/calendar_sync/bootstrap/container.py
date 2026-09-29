from __future__ import annotations

from dataclasses import dataclass, replace

from calendar_sync.application.accounts import (
    DeleteConnectedAccount,
    DisconnectConnectedAccount,
    ListConnectedAccounts,
)
from calendar_sync.application.activity import (
    ActivityQueries,
    GetDashboard,
    InspectActivityEvent,
    OperationsQueries,
)
from calendar_sync.application.health import RuleHealth
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    AccountAuthorization,
    AccountCalendars,
    AdministratorAccess,
    CalendarProvider,
    Clock,
    IdGenerator,
    IncidentNotifications,
    IncidentRepository,
    RuleHealthRecords,
    UnitOfWorkFactory,
)
from calendar_sync.application.preview import PreviewSyncRule
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
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.bootstrap.config import Settings
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    ReconciliationService,
    SyncDecisionService,
)
from calendar_sync.infrastructure.google.oauth import GoogleOAuthService, OAuthClientConfig
from calendar_sync.infrastructure.google.provider import GoogleCalendarProvider
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
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
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.scheduling import SyncScheduler, SystemClock
from calendar_sync.infrastructure.security import CredentialCipher, SqliteAdminAuth


@dataclass(frozen=True, slots=True)
class GoogleConnectionStatus:
    configured: bool
    redirect_uri: str | None
    """Shown only when configured, so the administrator can register it with Google."""


@dataclass(frozen=True, slots=True)
class Container:
    """The use cases and ports the Web API calls; nothing else of the installation."""

    secure_cookies: bool
    google: GoogleConnectionStatus
    administrator: AdministratorAccess
    activity: ActivityQueries
    operations: OperationsQueries
    get_dashboard: GetDashboard
    inspect_activity_event: InspectActivityEvent
    list_sync_rules: ListSyncRules
    create_draft_rule: CreateDraftSyncRule
    enable_sync_rule: EnableSyncRule
    pause_sync_rule: PauseSyncRule
    change_sync_rule_policy: ChangeSyncRulePolicy
    get_sync_rule_details: GetSyncRuleDetails
    remove_sync_rule: RemoveSyncRule
    replace_sync_rule_calendars: ReplaceSyncRuleCalendars
    # Each of these needs the installation master key, and synchronization also Google.
    list_connected_accounts: ListConnectedAccounts | None
    disconnect_connected_account: DisconnectConnectedAccount | None
    delete_connected_account: DeleteConnectedAccount | None
    authorization: AccountAuthorization | None
    account_calendars: AccountCalendars | None
    execute_sync_rule: ExecuteSyncRule | None
    preview_sync_rule: PreviewSyncRule | None
    reconcile_now: ReconcileNow | None
    scheduler: SyncScheduler | None


@dataclass(frozen=True, slots=True)
class Adapters:
    """The adapters one installation's use cases are composed from.

    `build_adapters` makes them from Settings; tests and the development preview substitute some
    before `compose` wires the use cases.
    """

    unit_of_work: UnitOfWorkFactory
    locks: RuleLocks
    clock: Clock
    ids: IdGenerator
    administrator: SqliteAdminAuth
    activity: ActivityQueries
    operations: OperationsQueries
    health_records: RuleHealthRecords
    incidents: IncidentRepository
    notifications: IncidentNotifications | None = None
    accounts: SqliteConnectedAccountStore | None = None
    google_oauth: GoogleOAuthService | None = None
    calendar_provider: CalendarProvider | None = None


def build_container(settings: Settings | None = None) -> Container:
    resolved = settings or Settings.from_environment()
    return compose(resolved, build_adapters(resolved))


def build_adapters(settings: Settings) -> Adapters:
    initialize_database(settings.database_path)
    unit_of_work = SqliteUnitOfWorkFactory(settings.database_path)
    locks = RuleLocks()
    adapters = Adapters(
        unit_of_work=unit_of_work,
        locks=locks,
        clock=SystemClock(),
        ids=UuidIdGenerator(),
        administrator=SqliteAdminAuth(settings.database_path),
        activity=SqliteActivityQueries(settings.database_path),
        operations=SqliteOperationsQueries(settings.database_path),
        health_records=SqliteRuleHealthRecords(settings.database_path),
        incidents=SqliteIncidentRepository(settings.database_path),
    )
    if not settings.master_key:
        return adapters
    accounts = SqliteConnectedAccountStore(
        settings.database_path, CredentialCipher(settings.master_key)
    )
    google_oauth = GoogleOAuthService(
        OAuthClientConfig(
            settings.google_client_id,
            settings.google_client_secret,
            settings.google_redirect_uri,
        ),
        accounts,
        SqliteAuthorizationStates(settings.database_path),
        verifier_key=settings.master_key,
    )
    return replace(
        adapters,
        accounts=accounts,
        google_oauth=google_oauth,
        calendar_provider=GoogleCalendarProvider(google_oauth.service_for),
        notifications=_notifier(settings),
    )


def compose(settings: Settings, adapters: Adapters) -> Container:
    unit_of_work, locks, clock = adapters.unit_of_work, adapters.locks, adapters.clock
    provider = adapters.calendar_provider
    accounts = adapters.accounts
    create_sync_rule = CreateSyncRule(unit_of_work)
    rule_health = RuleHealth(
        unit_of_work,
        adapters.health_records,
        adapters.incidents,
        clock,
        locks,
        adapters.notifications,
    )
    remove_sync_rule = RemoveSyncRule(
        unit_of_work, provider, accounts, clock, locks, incidents=rule_health
    )
    execute_sync_rule = preview_sync_rule = reconcile_now = scheduler = None
    if provider is not None and accounts is not None:
        fingerprinter = ProjectionFingerprinter()
        projector = EventProjector()
        decisions = SyncDecisionService(projector, fingerprinter)
        execute_sync_rule = ExecuteSyncRule(
            unit_of_work, provider, decisions, fingerprinter, clock, locks
        )
        preview_sync_rule = PreviewSyncRule(
            unit_of_work, provider, projector, clock, decisions, locks
        )
        reconcile_now = ReconcileNow(
            execute_sync_rule,
            ReconcileSyncRule(
                unit_of_work,
                provider,
                projector,
                ReconciliationService(fingerprinter),
                clock,
                locks,
            ),
            rule_health,
        )
        scheduler = SyncScheduler(execute_sync_rule, unit_of_work, rule_health, clock=clock)
    google_configured = bool(
        adapters.google_oauth and settings.google_client_id and settings.google_client_secret
    )
    return Container(
        secure_cookies=settings.secure_cookies,
        google=GoogleConnectionStatus(
            configured=google_configured,
            redirect_uri=settings.google_redirect_uri if google_configured else None,
        ),
        administrator=adapters.administrator,
        activity=adapters.activity,
        operations=adapters.operations,
        get_dashboard=GetDashboard(unit_of_work, adapters.operations),
        inspect_activity_event=InspectActivityEvent(adapters.activity, unit_of_work, provider),
        list_sync_rules=ListSyncRules(unit_of_work, locks),
        create_draft_rule=CreateDraftSyncRule(create_sync_rule, adapters.ids),
        enable_sync_rule=EnableSyncRule(unit_of_work, locks),
        pause_sync_rule=PauseSyncRule(unit_of_work, locks),
        change_sync_rule_policy=ChangeSyncRulePolicy(unit_of_work, clock, locks),
        get_sync_rule_details=GetSyncRuleDetails(unit_of_work, locks),
        remove_sync_rule=remove_sync_rule,
        replace_sync_rule_calendars=ReplaceSyncRuleCalendars(
            unit_of_work, remove_sync_rule, create_sync_rule, adapters.ids
        ),
        list_connected_accounts=(
            ListConnectedAccounts(unit_of_work, accounts) if accounts else None
        ),
        disconnect_connected_account=(
            DisconnectConnectedAccount(unit_of_work, accounts, locks) if accounts else None
        ),
        delete_connected_account=(
            DeleteConnectedAccount(unit_of_work, locks) if accounts else None
        ),
        authorization=adapters.google_oauth,
        account_calendars=adapters.google_oauth,
        execute_sync_rule=execute_sync_rule,
        preview_sync_rule=preview_sync_rule,
        reconcile_now=reconcile_now,
        scheduler=scheduler,
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
