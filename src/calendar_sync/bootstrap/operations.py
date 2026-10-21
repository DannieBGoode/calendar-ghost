from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from calendar_sync.application.identity.plans import (
    ChangePlan,
    DefinePlan,
    RemovePlan,
    SetPlansSetting,
    ShowPlans,
)
from calendar_sync.application.operations.installation_hints import (
    InstantSyncSignals,
    instant_sync_signals,
)
from calendar_sync.application.operations.instant_sync import (
    InstantDispatch,
    WatchUpkeep,
)
from calendar_sync.application.operations.operator_overview import OperatorOverview
from calendar_sync.application.operations.plan_assignment import AssignPlans
from calendar_sync.application.operations.ports import (
    WatchNoticeInbox,
)
from calendar_sync.application.operations.scheduled_pass import ScheduledPass, ScheduledServices
from calendar_sync.application.sync.accounts import (
    RecheckAdministratorLapses,
)
from calendar_sync.application.sync.provider_descriptors import ProviderDirectory
from calendar_sync.application.sync.watch_ports import (
    NoticeReader,
    SyncCadencePolicy,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.shared import UserServices
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.infrastructure.notifications import (
    IncidentNotifier,
    NotificationChannel,
    SmtpChannel,
    SmtpServer,
    WebhookChannel,
)
from calendar_sync.infrastructure.scheduling import (
    InstantSyncDispatcher,
    WatchKeeper,
)

if TYPE_CHECKING:
    from calendar_sync.bootstrap.container import Adapters


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
        plan_notices=services.plan_notices,
    )


def _installation_notifier(settings: Settings, mail: SmtpServer | None) -> IncidentNotifier | None:
    channels: list[NotificationChannel] = []
    if settings.incident_webhook_url:
        channels.append(WebhookChannel(settings.incident_webhook_url))
    if mail is not None and settings.smtp_recipient:
        channels.append(SmtpChannel(mail, settings.smtp_recipient))
    return IncidentNotifier(channels) if channels else None
