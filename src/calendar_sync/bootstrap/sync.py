from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from calendar_sync.application.identity.integration_tokens import IssueIntegrationToken
from calendar_sync.application.operations.activity import (
    InspectActivityEvent,
)
from calendar_sync.application.operations.instant_sync import (
    InstantSyncStatus,
)
from calendar_sync.application.operations.own_plan import ShowOwnPlan
from calendar_sync.application.operations.ports import (
    SchedulerHeartbeat,
)
from calendar_sync.application.operations.status import GetInstallationStatus
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.accounts import (
    CheckAccountAccess,
    DeleteConnectedAccount,
    DisconnectConnectedAccount,
    DiscoverCalendars,
    ListConnectedAccounts,
)
from calendar_sync.application.sync.health import RuleHealth
from calendar_sync.application.sync.instant_sync import (
    UpkeepWatches,
    WatchProviders,
)
from calendar_sync.application.sync.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.sync.manual_runs import AdmitManualRun
from calendar_sync.application.sync.plan_holds import (
    ChooseKeptRules,
    PlanHolds,
    SettleLocks,
)
from calendar_sync.application.sync.ports import UnitOfWorkFactory
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
from calendar_sync.application.sync.synchronization import ExecuteSyncRule, SyncNow
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.shared import UserServices
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    ReconciliationService,
    SyncDecisionService,
)
from calendar_sync.infrastructure.google.descriptor import google_provider
from calendar_sync.infrastructure.microsoft.descriptor import microsoft_provider
from calendar_sync.infrastructure.microsoft.oauth import MicrosoftClient
from calendar_sync.infrastructure.oauth import OAuthClientConfig
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import SqliteAuthorizationStates

if TYPE_CHECKING:
    from calendar_sync.bootstrap.container import Adapters


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


def _no_account_watches(_account: ConnectedAccountId) -> None:
    """Where no provider can watch, nothing is watched to stop."""


def _no_provider(_account: ConnectedAccountId) -> ProviderKind | None:
    """Without the master key no account is stored, so none has a provider."""
    return None


def _compose_user(
    user_id: UserId,
    adapters: Adapters,
    heartbeat: SchedulerHeartbeat | None,
    instant: InstantSyncStatus,
    settle_locks: SettleLocks,
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
    holds = PlanHolds(unit_of_work, user_id, adapters.allowances, locks, settle_locks, clock)
    return UserServices(
        user_id=user_id,
        plan_holds=holds,
        choose_kept_rules=ChooseKeptRules(holds),
        plan_notices=adapters.plan_notices(user_id),
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
