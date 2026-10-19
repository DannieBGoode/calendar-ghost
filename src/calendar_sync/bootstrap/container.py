from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from urllib.parse import urlsplit

from calendar_sync.application.identity.administration import (
    AcceptInvitation,
    ChangeRole,
    ChangeUserState,
    CheckInvitation,
    CheckPasswordReset,
    DeleteOwnAccount,
    DeleteUser,
    InviteUser,
    IssuePasswordReset,
    LinkAttempts,
    ListInvitations,
    OwnedRules,
    ResetPassword,
    RevokeInvitation,
    SetRegistrationPolicy,
    ShowOwnAccountDeletion,
    ShowRegistration,
)
from calendar_sync.application.identity.integration_tokens import IssueIntegrationToken
from calendar_sync.application.identity.plans import (
    ChangePlan,
    DefinePlan,
    RemovePlan,
    SetPlansSetting,
    ShowPlans,
)
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
from calendar_sync.application.identity.sign_in import (
    ChangeOwnPassword,
    SetInstantSync,
    SetNotificationEmail,
    SetOwnEmail,
    SetUpInstallation,
    SignIn,
)
from calendar_sync.application.operations.activity import (
    ActivityQueries,
    InspectActivityEvent,
    OperationsQueries,
)
from calendar_sync.application.operations.installation_health import (
    GetInstallationHealth,
    HintSources,
    InstallationIncidentWatch,
    InstallationNotifications,
)
from calendar_sync.application.operations.installation_hints import (
    InstantSyncSignals,
    instant_sync_signals,
)
from calendar_sync.application.operations.instant_sync import (
    InstantDispatch,
    InstantSyncStatus,
    WatchedSources,
    WatchUpkeep,
)
from calendar_sync.application.operations.operator_overview import OperatorOverview, UserStatuses
from calendar_sync.application.operations.own_plan import ShowOwnPlan
from calendar_sync.application.operations.plan_assignment import AssignPlans
from calendar_sync.application.operations.ports import (
    CauseSighting,
    DatabaseStorage,
    InstallationUnitOfWorkFactory,
    LogFiles,
    SchedulerHeartbeat,
    WatchNoticeInbox,
)
from calendar_sync.application.operations.scheduled_pass import ScheduledPass, ScheduledServices
from calendar_sync.application.operations.status import GetInstallationStatus
from calendar_sync.application.operations.storage import StorageAdministration
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.application.sync.accounts import (
    CheckAccountAccess,
    DeleteConnectedAccount,
    DisconnectConnectedAccount,
    DiscoverCalendars,
    ListConnectedAccounts,
    RecheckAdministratorLapses,
)
from calendar_sync.application.sync.health import RuleHealth
from calendar_sync.application.sync.instant_sync import (
    AccountBackoff,
    UpkeepWatches,
    WatchProviders,
)
from calendar_sync.application.sync.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.manual_runs import AdmitManualRun, RunThrottle
from calendar_sync.application.sync.ports import (
    AccountCalendars,
    Allowances,
    CalendarProvider,
    ConnectedAccountRepository,
    IncidentNotifications,
    IncidentRepository,
    ProviderCallStats,
    RuleHealthRecords,
    RunIdGenerator,
    UnitOfWorkFactory,
)
from calendar_sync.application.sync.preview import PreviewSyncRule
from calendar_sync.application.sync.provider_descriptors import ProviderDirectory
from calendar_sync.application.sync.reconciliation import ReconcileNow, ReconcileSyncRule
from calendar_sync.application.sync.removal import RemoveSyncRule
from calendar_sync.application.sync.rules import (
    ChangeSyncRulePolicy,
    CreateDraftSyncRule,
    CreateSyncRule,
    EnableSyncRule,
    GetSyncRuleDetails,
    ListSyncRules,
    PauseSyncRule,
    ReplaceSyncRuleCalendars,
)
from calendar_sync.application.sync.run_log import UntalliedProviderCalls
from calendar_sync.application.sync.synchronization import ExecuteSyncRule, SyncNow
from calendar_sync.application.sync.watch_ports import (
    DeliveryEvidenceLog,
    EveryUserInstant,
    NoticeReader,
    PlanCadence,
    SyncCadencePolicy,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.logs import configure_logging
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import SCHEDULED_EVERY
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    ReconciliationService,
    SyncDecisionService,
)
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.google.descriptor import google_provider
from calendar_sync.infrastructure.identifiers import UuidIdGenerator, UuidRunIdGenerator
from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
from calendar_sync.infrastructure.log_files import RotatingLogFiles
from calendar_sync.infrastructure.microsoft.descriptor import microsoft_provider
from calendar_sync.infrastructure.microsoft.oauth import MicrosoftClient
from calendar_sync.infrastructure.notifications import (
    IncidentNotifier,
    NotificationChannel,
    OwnerNotifier,
    SmtpChannel,
    SmtpServer,
    WebhookChannel,
)
from calendar_sync.infrastructure.oauth import OAuthClientConfig
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.activity_queries import (
    SqliteActivityQueries,
    SqliteOperationsQueries,
)
from calendar_sync.infrastructure.persistence.authorization_states import SqliteAuthorizationStates
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
from calendar_sync.infrastructure.persistence.sqlite import SqliteUnitOfWorkFactory
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
class UserServices:
    """The use cases one User's requests call. Each sees only that User's records (ADR 0029)."""

    user_id: UserId
    activity: ActivityQueries
    operations: OperationsQueries
    get_installation_status: GetInstallationStatus
    integration_tokens: IntegrationTokens
    issue_integration_token: IssueIntegrationToken
    """Issues a token within the User's Plan; installation:read only for administrators."""
    show_own_plan: ShowOwnPlan
    """What the User's Plan allows them and how much of it they have, for Your plan."""
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
    instant_sync_status: InstantSyncStatus
    """Whether Instant Sync is on for a User, and why each of their rules syncs as it does."""
    watch_upkeep: UpkeepWatches | None
    """Keeps this User's Calendar Watches; None where accounts cannot be stored."""
    admit_manual_run: AdmitManualRun
    """Admits each Sync Now, Reconcile Now, and Rule Preview, counted while a Plan limits the
    User."""
    # Each of these needs the installation master key, and synchronization also a provider.
    list_connected_accounts: ListConnectedAccounts | None
    disconnect_connected_account: DisconnectConnectedAccount | None
    delete_connected_account: DeleteConnectedAccount | None
    check_account_access: CheckAccountAccess | None
    discover_calendars: DiscoverCalendars | None
    execute_sync_rule: ExecuteSyncRule | None
    sync_now: SyncNow | None
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
    set_notification_email: SetNotificationEmail
    set_instant_sync: SetInstantSync
    change_own_password: ChangeOwnPassword


@dataclass(frozen=True, slots=True)
class AdministrationServices:
    """What Installation Administrators do with Users, and the links people use to join or to
    choose a new password."""

    show_registration: ShowRegistration
    set_registration_policy: SetRegistrationPolicy
    invite_user: InviteUser
    list_invitations: ListInvitations
    revoke_invitation: RevokeInvitation
    check_invitation: CheckInvitation
    accept_invitation: AcceptInvitation
    issue_password_reset: IssuePasswordReset
    check_password_reset: CheckPasswordReset
    reset_password: ResetPassword
    change_role: ChangeRole
    change_user_state: ChangeUserState
    delete_user: DeleteUser
    delete_own_account: DeleteOwnAccount
    show_own_account_deletion: ShowOwnAccountDeletion


@dataclass(frozen=True, slots=True)
class PlanServices:
    """What Installation Administrators do with Plans and the Plans setting (ADR 0038)."""

    show_plans: ShowPlans
    define_plan: DefinePlan
    change_plan: ChangePlan
    remove_plan: RemovePlan
    set_plans_setting: SetPlansSetting
    assign_plans: AssignPlans
    """Gives one Plan to many people at once, after a dry run that says who would be over."""


@dataclass(frozen=True, slots=True)
class Container:
    """What the Web API reads: installation-wide services, and each User's through `for_user`."""

    secure_cookies: bool
    providers: ProviderDirectory
    """Every calendar provider this release knows, and how Users connect the configured ones."""
    identity: IdentityServices
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
    registration: RegistrationSettings
    invitations: Invitations
    password_resets: PasswordResetLinks
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
    adapters = Adapters(
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
        registration=SqliteRegistrationSettings(database),
        invitations=SqliteInvitations(database, ids),
        password_resets=SqlitePasswordResetLinks(database, ids),
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


def calendar_providers(
    settings: Settings, accounts: SqliteConnectedAccountStore | None, clock: Clock
) -> ProviderDirectory:
    """Every calendar provider's descriptor, as its own package composes it (ADR 0022). Adding a
    provider adds its package and one line here."""
    states = SqliteAuthorizationStates(settings.database_path, clock)
    return ProviderDirectory(
        (
            google_provider(
                OAuthClientConfig(
                    settings.google_client_id,
                    settings.google_client_secret,
                    settings.google_redirect_uri,
                ),
                accounts,
                states,
                settings.master_key,
                clock,
            ),
            microsoft_provider(
                MicrosoftClient(
                    OAuthClientConfig(
                        settings.microsoft_client_id,
                        settings.microsoft_client_secret,
                        settings.microsoft_redirect_uri,
                    ),
                    settings.microsoft_tenant,
                ),
                accounts,
                states,
                settings.master_key,
                clock,
                secret_expires=settings.microsoft_client_secret_expires,
            ),
        )
    )


def compose(settings: Settings, adapters: Adapters) -> Container:
    def user_services(user_id: UserId) -> UserServices:
        # Read when called, after the scheduler exists: every User's status reads its heartbeat.
        return _compose_user(user_id, adapters, scheduler, instant_status)

    cadence = adapters.sync_cadence
    scheduled_pass = ScheduledPass(
        adapters.installation_units,
        lambda owner: _scheduled_services(user_services(owner)),
        adapters.clock,
        cadence=cadence,
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
    return Container(
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


@dataclass(frozen=True, slots=True)
class _InstantSync:
    """Instant Sync's loops and notice intake; none unless the installation can offer it."""

    dispatcher: InstantSyncDispatcher | None = None
    keeper: WatchKeeper | None = None
    inbox: WatchNoticeInbox | None = None


def _instant_sync(
    adapters: Adapters,
    scheduled_pass: ScheduledPass,
    user_services: Callable[[UserId], UserServices],
    cadence: SyncCadencePolicy,
    address: str,
) -> _InstantSync:
    """Instant runs share the scheduled pass's path, each User's services, and rule locks."""
    upkeep = WatchUpkeep(
        adapters.installation_units,
        lambda owner: user_services(owner).watch_upkeep,
        cadence,
        address,
        adapters.clock,
    )
    dispatch = InstantDispatch(
        adapters.installation_units,
        scheduled_pass,
        adapters.unit_of_work,
        cadence,
        adapters.clock,
    )
    return _InstantSync(
        InstantSyncDispatcher(dispatch, clock=adapters.clock),
        WatchKeeper(upkeep),
        adapters.watch_inbox,
    )


def _notice_readers(
    providers: ProviderDirectory,
) -> Mapping[str, tuple[ProviderKind, NoticeReader]]:
    """Each provider's notice reader, by the slug in its notice address."""
    return {
        descriptor.guide.slug: (descriptor.kind, descriptor.notice_reader)
        for descriptor in providers.descriptors
        if descriptor.notice_reader is not None
    }


def _owned_rules(owner: UserId, adapters: Adapters, services: UserServices) -> OwnedRules:
    """What deleting `owner` needs: their units, Rule Removal, and stopping their watches."""
    upkeep = services.watch_upkeep
    return OwnedRules(
        adapters.unit_of_work(owner),
        services.remove_sync_rule,
        upkeep.stop_all if upkeep is not None else _no_watches,
    )


def _watch_upkeep(
    adapters: Adapters, unit_of_work: UnitOfWorkFactory, lapses: LapsedAuthorizations
) -> UpkeepWatches | None:
    """One User's watch upkeep, wherever accounts can be stored and so watched."""
    watchers = adapters.watchers
    if watchers is None:
        return None
    return UpkeepWatches(
        unit_of_work,
        WatchProviders(
            watchers,
            watchers.provider_of,
            adapters.providers.slug_of,
            backoff=adapters.watch_backoff,
        ),
        adapters.delivery_evidence,
        adapters.clock,
        lapses=lapses,
        call_stats=adapters.call_stats,
    )


def _account_watches(upkeep: UpkeepWatches | None) -> Callable[[ConnectedAccountId], None]:
    """Stops one account's watches before disconnecting it discards their credentials."""
    if upkeep is None:
        return _no_account_watches
    return upkeep.stop_all


def _no_watches() -> None:
    """Where no provider can watch, nothing is watched to stop."""


def _no_account_watches(_account: ConnectedAccountId) -> None:
    """Where no provider can watch, nothing is watched to stop."""


def _no_provider(_account: ConnectedAccountId) -> ProviderKind | None:
    """Without the master key no account is stored, so none has a provider."""
    return None


def _failure_causes(
    installation: InstallationUnitOfWorkFactory,
) -> Callable[[datetime], Sequence[CauseSighting]]:
    """Every User's failures with a Cause from a time on, for Installation Hints."""

    def read(since: datetime) -> Sequence[CauseSighting]:
        with installation() as reading:
            return reading.failure_causes(since)

    return read


def _instant_sync_signals(
    adapters: Adapters, address: str | None
) -> Callable[[], InstantSyncSignals]:
    """Who wants Instant Sync and whether providers reach the public address, for Installation
    Hints."""

    def read() -> InstantSyncSignals:
        with adapters.installation_units() as reading:
            owners = reading.instant_sync_owners()
        evidence = adapters.delivery_evidence.evidence(address) if address else {}
        return instant_sync_signals(owners, adapters.sync_cadence, address, evidence)

    return read


def _identity(adapters: Adapters) -> IdentityServices:
    users, passwords, sessions = adapters.users, adapters.passwords, adapters.sessions
    return IdentityServices(
        users=users,
        sessions=sessions,
        set_up=SetUpInstallation(users, passwords, sessions, adapters.ids, adapters.clock),
        sign_in=SignIn(users, passwords, sessions, adapters.sign_in_throttle, adapters.clock),
        set_own_email=SetOwnEmail(users, passwords),
        set_notification_email=SetNotificationEmail(users),
        set_instant_sync=SetInstantSync(users),
        change_own_password=ChangeOwnPassword(users, passwords, sessions),
    )


def _administration(
    adapters: Adapters, owned: Callable[[UserId], OwnedRules]
) -> AdministrationServices:
    users, clock, sessions = adapters.users, adapters.clock, adapters.sessions
    settings, invitations, resets = (
        adapters.registration,
        adapters.invitations,
        adapters.password_resets,
    )
    passwords = adapters.passwords
    attempts = LinkAttempts(adapters.link_throttle)
    return AdministrationServices(
        show_registration=ShowRegistration(users, settings),
        set_registration_policy=SetRegistrationPolicy(users, settings),
        invite_user=InviteUser(users, settings, invitations, clock),
        list_invitations=ListInvitations(users, invitations, clock),
        revoke_invitation=RevokeInvitation(users, invitations, clock),
        check_invitation=CheckInvitation(settings, invitations, clock, attempts),
        accept_invitation=AcceptInvitation(
            users, settings, invitations, passwords, sessions, adapters.ids, clock, attempts
        ),
        issue_password_reset=IssuePasswordReset(users, resets, clock),
        check_password_reset=CheckPasswordReset(resets, clock, attempts),
        reset_password=ResetPassword(resets, passwords, sessions, clock, attempts),
        change_role=ChangeRole(users),
        change_user_state=ChangeUserState(users, sessions),
        delete_user=DeleteUser(users, sessions, owned),
        delete_own_account=DeleteOwnAccount(users, passwords, sessions, owned, settings, clock),
        show_own_account_deletion=ShowOwnAccountDeletion(users),
    )


def _plan_services(adapters: Adapters, overview: OperatorOverview) -> PlanServices:
    """Every Plan use case reads and writes the installation's one Plans store; giving a Plan to
    many people counts what they use through the Operator Overview."""
    users, catalog, clock = adapters.users, adapters.plan_catalog, adapters.clock
    return PlanServices(
        show_plans=ShowPlans(users, catalog),
        define_plan=DefinePlan(users, catalog, clock),
        change_plan=ChangePlan(users, catalog, clock),
        remove_plan=RemovePlan(users, catalog),
        set_plans_setting=SetPlansSetting(users, catalog, clock),
        assign_plans=AssignPlans(users, overview, adapters.plan_assignments, clock),
    )


def _scheduled_services(services: UserServices) -> ScheduledServices:
    assert services.execute_sync_rule is not None
    check = services.check_account_access
    return ScheduledServices(
        services.execute_sync_rule,
        services.rule_health,
        RecheckAdministratorLapses(check, services.rule_health.incidents) if check else None,
    )


def _compose_user(
    user_id: UserId,
    adapters: Adapters,
    heartbeat: SchedulerHeartbeat | None,
    instant: InstantSyncStatus,
) -> UserServices:
    unit_of_work, locks, clock = adapters.unit_of_work(user_id), adapters.locks, adapters.clock
    provider = adapters.calendar_provider
    accounts = adapters.accounts(user_id) if adapters.accounts is not None else None
    operations = adapters.operations(user_id)
    tokens = adapters.integration_tokens(user_id)
    create_sync_rule = CreateSyncRule(unit_of_work)
    list_sync_rules = ListSyncRules(unit_of_work, locks)
    rule_health = RuleHealth(
        unit_of_work,
        adapters.health_records(user_id),
        adapters.incidents(user_id),
        clock,
        locks,
        adapters.notifications(user_id),
    )
    call_stats = adapters.call_stats
    watch_upkeep = _watch_upkeep(adapters, unit_of_work, rule_health.lapses)
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
            incidents=rule_health,
        )
    calendars = adapters.account_calendars
    return UserServices(
        user_id=user_id,
        activity=adapters.activity(user_id),
        operations=operations,
        get_installation_status=GetInstallationStatus(
            list_sync_rules, operations, clock, heartbeat
        ),
        integration_tokens=tokens,
        issue_integration_token=IssueIntegrationToken(
            user_id, adapters.users, tokens, adapters.allowances
        ),
        show_own_plan=ShowOwnPlan(adapters.allowances, unit_of_work, accounts, tokens, user_id),
        inspect_activity_event=InspectActivityEvent(
            adapters.activity(user_id), unit_of_work, provider
        ),
        list_sync_rules=list_sync_rules,
        create_draft_rule=CreateDraftSyncRule(create_sync_rule, adapters.ids),
        enable_sync_rule=EnableSyncRule(unit_of_work, locks, adapters.allowances, user_id),
        pause_sync_rule=PauseSyncRule(unit_of_work, locks),
        change_sync_rule_policy=ChangeSyncRulePolicy(unit_of_work, clock, locks),
        get_sync_rule_details=GetSyncRuleDetails(unit_of_work, locks, adapters.allowances, user_id),
        remove_sync_rule=remove_sync_rule,
        replace_sync_rule_calendars=ReplaceSyncRuleCalendars(
            unit_of_work, remove_sync_rule, adapters.ids
        ),
        rule_health=rule_health,
        lapsed_authorizations=rule_health.lapses,
        instant_sync_status=instant,
        watch_upkeep=watch_upkeep,
        admit_manual_run=AdmitManualRun(adapters.allowances, adapters.run_throttle, user_id),
        list_connected_accounts=(
            ListConnectedAccounts(unit_of_work, accounts) if accounts else None
        ),
        disconnect_connected_account=(
            DisconnectConnectedAccount(
                unit_of_work, accounts, locks, _account_watches(watch_upkeep)
            )
            if accounts
            else None
        ),
        delete_connected_account=(
            DeleteConnectedAccount(unit_of_work, locks) if accounts else None
        ),
        check_account_access=(
            CheckAccountAccess(calendars, accounts, rule_health.lapses)
            if calendars and accounts
            else None
        ),
        discover_calendars=(
            DiscoverCalendars(calendars, unit_of_work, accounts, rule_health.lapses)
            if calendars and accounts
            else None
        ),
        execute_sync_rule=execute_sync_rule,
        sync_now=(SyncNow(execute_sync_rule, rule_health, clock) if execute_sync_rule else None),
        preview_sync_rule=preview_sync_rule,
        reconcile_now=reconcile_now,
    )


def public_address(settings: Settings) -> str | None:
    """Where people reach the Web UI, for links in email: an http or https address at the root
    of its host, with no path, query, or fragment, without its trailing slash. The Web UI is
    served at the root of its address, so anything else gives no link."""
    configured = settings.public_url.strip()
    try:
        parsed = urlsplit(configured)
    except ValueError:
        # Not even an address, such as an unclosed IPv6 bracket: as if unset.
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    return configured.rstrip("/")


def instant_sync_address(settings: Settings) -> str | None:
    """Where providers deliver Watch Notices: the public address, only when it is https, as
    providers deliver nowhere else (ADR 0036)."""
    address = public_address(settings)
    if address is None or urlsplit(address).scheme != "https":
        return None
    return address


def _mail_server(settings: Settings) -> SmtpServer | None:
    """The installation's mail server, once it has a host and a sender to send as."""
    if not (settings.smtp_host and settings.smtp_sender):
        return None
    return SmtpServer(
        host=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.smtp_sender,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_starttls=settings.smtp_starttls,
    )


def _installation_notifier(settings: Settings, mail: SmtpServer | None) -> IncidentNotifier | None:
    channels: list[NotificationChannel] = []
    if settings.incident_webhook_url:
        channels.append(WebhookChannel(settings.incident_webhook_url))
    if mail is not None and settings.smtp_recipient:
        channels.append(SmtpChannel(mail, settings.smtp_recipient))
    return IncidentNotifier(channels) if channels else None
