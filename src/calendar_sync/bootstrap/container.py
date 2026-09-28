from __future__ import annotations

from dataclasses import dataclass

from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import CalendarProvider, UnitOfWorkFactory
from calendar_sync.application.preview import PreviewSyncRule
from calendar_sync.application.reconciliation import ReconcileSyncRule
from calendar_sync.application.removal import RemoveSyncRule
from calendar_sync.application.rules import (
    ChangeSyncRulePolicy,
    CreateSyncRule,
    GetSyncRuleDetails,
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
from calendar_sync.infrastructure.google.oauth import (
    CredentialCipher,
    GoogleOAuthService,
    SqliteConnectedAccountStore,
)
from calendar_sync.infrastructure.google.provider import GoogleCalendarProvider
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.notifications import (
    IncidentNotifier,
    NotificationChannel,
    SmtpChannel,
    WebhookChannel,
)
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.scheduling import SqliteRuleHealth, SyncScheduler, SystemClock
from calendar_sync.infrastructure.security import SqliteAdminAuth


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    unit_of_work: UnitOfWorkFactory
    create_sync_rule: CreateSyncRule
    rule_locks: RuleLocks
    change_sync_rule_policy: ChangeSyncRulePolicy
    get_sync_rule_details: GetSyncRuleDetails
    remove_sync_rule: RemoveSyncRule
    replace_sync_rule_calendars: ReplaceSyncRuleCalendars
    admin_auth: SqliteAdminAuth
    connected_accounts: SqliteConnectedAccountStore | None
    google_oauth: GoogleOAuthService | None
    calendar_provider: CalendarProvider | None
    execute_sync_rule: ExecuteSyncRule | None
    preview_sync_rule: PreviewSyncRule | None
    reconcile_sync_rule: ReconcileSyncRule | None
    scheduler: SyncScheduler | None


def build_container(settings: Settings | None = None) -> Container:
    resolved = settings or Settings.from_environment()
    initialize_database(resolved.database_path)
    unit_of_work = SqliteUnitOfWorkFactory(resolved.database_path)
    accounts = None
    google_oauth = None
    provider: CalendarProvider | None = None
    execute_sync_rule = None
    preview_sync_rule = None
    reconcile_sync_rule = None
    scheduler = None
    rule_locks = RuleLocks()
    if resolved.master_key:
        accounts = SqliteConnectedAccountStore(
            resolved.database_path, CredentialCipher(resolved.master_key)
        )
        google_oauth = GoogleOAuthService(resolved, accounts)
        fingerprinter = ProjectionFingerprinter()
        provider = GoogleCalendarProvider(google_oauth.service_for)
        projector = EventProjector()
        execute_sync_rule = ExecuteSyncRule(
            unit_of_work,
            provider,
            SyncDecisionService(projector, fingerprinter),
            fingerprinter,
            SystemClock(),
            rule_locks,
        )
        preview_sync_rule = PreviewSyncRule(
            unit_of_work,
            provider,
            projector,
            SystemClock(),
            rule_locks,
        )
        reconcile_sync_rule = ReconcileSyncRule(
            unit_of_work,
            provider,
            projector,
            ReconciliationService(fingerprinter),
            SystemClock(),
            rule_locks,
        )
        channels: list[NotificationChannel] = []
        if resolved.incident_webhook_url:
            channels.append(WebhookChannel(resolved.incident_webhook_url))
        if resolved.smtp_host and resolved.smtp_sender and resolved.smtp_recipient:
            channels.append(
                SmtpChannel(
                    host=resolved.smtp_host,
                    port=resolved.smtp_port,
                    sender=resolved.smtp_sender,
                    recipient=resolved.smtp_recipient,
                    username=resolved.smtp_username,
                    password=resolved.smtp_password,
                    use_starttls=resolved.smtp_starttls,
                )
            )
        scheduler = SyncScheduler(
            execute_sync_rule,
            unit_of_work,
            SqliteRuleHealth(
                resolved.database_path,
                unit_of_work,
                IncidentNotifier(channels) if channels else None,
                locks=rule_locks,
            ),
        )
    create_sync_rule = CreateSyncRule(unit_of_work)
    remove_sync_rule = RemoveSyncRule(unit_of_work, provider, accounts, SystemClock(), rule_locks)
    return Container(
        settings=resolved,
        unit_of_work=unit_of_work,
        create_sync_rule=create_sync_rule,
        rule_locks=rule_locks,
        change_sync_rule_policy=ChangeSyncRulePolicy(unit_of_work, SystemClock(), rule_locks),
        get_sync_rule_details=GetSyncRuleDetails(unit_of_work),
        remove_sync_rule=remove_sync_rule,
        replace_sync_rule_calendars=ReplaceSyncRuleCalendars(
            unit_of_work, remove_sync_rule, create_sync_rule, UuidIdGenerator()
        ),
        admin_auth=SqliteAdminAuth(resolved.database_path),
        connected_accounts=accounts,
        google_oauth=google_oauth,
        calendar_provider=provider,
        execute_sync_rule=execute_sync_rule,
        preview_sync_rule=preview_sync_rule,
        reconcile_sync_rule=reconcile_sync_rule,
        scheduler=scheduler,
    )
