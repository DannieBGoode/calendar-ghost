from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from calendar_sync.application.identity.integration_tokens import IssueIntegrationToken
from calendar_sync.application.identity.ports import (
    IntegrationTokens,
)
from calendar_sync.application.operations.activity import (
    ActivityQueries,
    InspectActivityEvent,
    OperationsQueries,
)
from calendar_sync.application.operations.instant_sync import (
    InstantSyncStatus,
)
from calendar_sync.application.operations.own_plan import ShowOwnPlan
from calendar_sync.application.operations.status import GetInstallationStatus
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
)
from calendar_sync.application.sync.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.sync.manual_runs import AdmitManualRun
from calendar_sync.application.sync.plan_holds import (
    ChooseKeptRules,
    PlanHolds,
    PlanNotices,
)
from calendar_sync.application.sync.preview import PreviewSyncRule
from calendar_sync.application.sync.reconciliation import ReconcileNow
from calendar_sync.application.sync.removal import RemoveSyncRule
from calendar_sync.application.sync.rules import (
    ChangeSyncRulePolicy,
    CreateDraftSyncRule,
    EnableSyncRule,
    GetSyncRuleDetails,
    ListSyncRules,
    PauseSyncRule,
    ReplaceSyncRuleCalendars,
)
from calendar_sync.application.sync.synchronization import ExecuteSyncRule, SyncNow
from calendar_sync.bootstrap.config import Settings
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.notifications import (
    SmtpServer,
)


@dataclass(frozen=True, slots=True)
class UserServices:
    """The use cases one User's requests call. Each sees only that User's records (ADR 0029)."""

    user_id: UserId
    plan_holds: PlanHolds
    choose_kept_rules: ChooseKeptRules
    plan_notices: PlanNotices | None
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
    """Admits each Sync Now, Reconcile Now, and Rule Preview, counted while the User's Plan
    limits anything."""
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
