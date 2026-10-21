"""The Operator Overview: each User's Installation Status as their own Overview computes it, with
every calendar shown by a neutral label instead of its name (ADR 0030).

It reads across Users through the installation-wide unit of work, which holds no calendar or
account name, so neither can reach what an Installation Administrator sees.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

from calendar_sync.application.identity.administration import (
    AdministratorRequired,
    UserNotFound,
    require_administrator,
)
from calendar_sync.application.identity.errors import PlanNotFound
from calendar_sync.application.identity.ports import (
    AssignmentChange,
    PlanAssignments,
    PlanCatalog,
    UserDirectory,
    UserQuery,
)
from calendar_sync.application.operations.ports import (
    InstallationUnitOfWorkFactory,
    ResourceUse,
    SchedulerHeartbeat,
    SchedulerProgress,
    StatusRecords,
)
from calendar_sync.application.operations.status import (
    InstallationStatus,
    StatusVerdict,
    assess_installation,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.plan_ports import Allowances
from calendar_sync.application.sync.resource_use import first_counted_day
from calendar_sync.application.sync.rules import SyncRuleSummary
from calendar_sync.domain.access import User, UserId
from calendar_sync.domain.model import CalendarEndpoint, SyncRule
from calendar_sync.domain.plans import (
    Allowance,
    OverLimit,
    Plan,
    PlanKey,
    PlanReach,
    PlanUse,
    allowance_for,
    plan_reach,
)

logger = logging.getLogger(__name__)

CALENDAR_LABEL = "Calendar {number}"


def calendar_numbers(rules: Iterable[SyncRule]) -> dict[CalendarEndpoint, int]:
    """A number for each calendar the rules use, in the order the rules were created, each rule's
    source before its destination, so a User's calendars keep their numbers from one visit to the
    next."""
    numbers: dict[CalendarEndpoint, int] = {}
    for rule in rules:
        for endpoint in (rule.source, rule.destination):
            numbers.setdefault(endpoint, len(numbers) + 1)
    return numbers


def calendar_labels(rules: Iterable[SyncRule]) -> dict[CalendarEndpoint, str]:
    """The neutral label, "Calendar 1", that stands in for each calendar's name."""
    return {
        endpoint: CALENDAR_LABEL.format(number=number)
        for endpoint, number in calendar_numbers(rules).items()
    }


@dataclass(slots=True)
class UserStatuses:
    """Each User's Installation Status, as `GetInstallationStatus` computes it for them, with
    calendars by their labels. A page of Users is read at once, never one rule at a time."""

    installation: InstallationUnitOfWorkFactory
    locks: RuleLocks
    clock: Clock
    scheduler: SchedulerHeartbeat | None

    def of(self, users: Collection[UserId]) -> dict[UserId, InstallationStatus]:
        with self.installation() as installation:
            records = installation.status_records(users)
        scheduler = self.scheduler.progress() if self.scheduler is not None else None
        now = self.clock.now()
        return {user: self._assess(records[user], scheduler, now) for user in records}

    def _assess(
        self, records: StatusRecords, scheduler: SchedulerProgress | None, now: datetime
    ) -> InstallationStatus:
        numbers = calendar_numbers(recorded.rule for recorded in records.rules)
        labels = {
            endpoint: CALENDAR_LABEL.format(number=number) for endpoint, number in numbers.items()
        }
        # In identifier order, as ListSyncRules lists them, so problems of equal urgency come
        # in the order the User's own Overview shows them.
        summaries = [
            SyncRuleSummary(
                recorded.rule,
                recorded.last_sync,
                recorded.latest_preview,
                self.locks.current_work(recorded.rule.id),
                labels,
            )
            for recorded in sorted(records.rules, key=lambda recorded: recorded.rule.id.value)
        ]
        status = assess_installation(summaries, records.overview, records.incidents, scheduler, now)
        return replace(status, calendar_numbers=numbers)


@dataclass(frozen=True, slots=True)
class PersonPlan:
    """A person's Plan, as the Operator Overview shows it (ADR 0038)."""

    allowance: Allowance
    """What their Plan allows them now, and their own Plan."""
    has: Plan | None
    """The Plan they have, whether or not it limits them now: their own, or else the Default
    Plan; None when they have neither. People finds them by it, as the Plan counts them."""
    over: tuple[OverLimit, ...] = ()
    """Each limit of that Plan they have more of than it allows, as after it was lowered;
    none for someone no Plan limits, such as an administrator or a disabled person."""
    use: PlanUse | None = None
    """How much they have of what that Plan counts, whoever they are; None when they have no
    Plan. An administrator sees the token count too (ADR 0030, amended)."""
    assigned_by: str | None = None
    """The email of the administrator who gave them their own Plan; None while they have the
    Default Plan, and when billing gave it or that administrator was deleted or has no email."""
    assigned_at: datetime | None = None
    """When their own Plan was last given; None while they have the Default Plan, or when
    nothing recorded it."""

    @property
    def on_default(self) -> bool:
        """Whether the Plan they have is the Default Plan, since they have none of their own."""
        return self.has is not None and self.allowance.assigned is None


def person_plan(
    user: User, allowance: Allowance, default: Plan | None, use: PlanUse | None
) -> PersonPlan:
    """`user`'s Plan: their own, or else `default`, with `use`, and what `use` has over its
    limits while it limits them, whether or not Plans are on, so an administrator sees it
    before turning them on."""
    has = allowance.assigned if allowance.assigned is not None else default
    if has is None:
        return PersonPlan(allowance, None)
    over = use.over(has.limits) if use is not None and user.limited_by_plans else ()
    return PersonPlan(allowance, has, over, use)


def _given(
    plan: PersonPlan, change: AssignmentChange | None, emails: Mapping[UserId, str | None]
) -> PersonPlan:
    """`plan` with who gave it, by `emails`, and when, while it is their own."""
    if change is None or plan.allowance.assigned is None:
        return plan
    giver = emails.get(change.actor) if change.actor is not None else None
    return replace(plan, assigned_by=giver, assigned_at=change.at)


@dataclass(frozen=True, slots=True)
class UserOverview:
    """What the Operator Overview shows about one User, to an administrator and to that User."""

    user: User
    status: InstallationStatus
    resources: ResourceUse
    calls_since: date
    """The first UTC day the provider calls in `resources` count."""
    plan: PersonPlan | None = None
    """Their Plan; None while no Plan exists, or when Plans cannot be read (ADR 0038)."""


@dataclass(frozen=True, slots=True)
class OverviewQuery:
    users: UserQuery = field(default_factory=UserQuery)
    verdict: StatusVerdict | None = None
    """Only Users whose Installation Status has this verdict."""
    by_verdict: bool = False
    """Most urgent verdict first, or last when the query is descending; then by `users.sort`."""
    over: bool = False
    """Only Users over a limit of the Plan they have, whether or not Plans are on; nobody while
    Plans cannot be read (ADR 0038)."""


@dataclass(frozen=True, slots=True)
class OverviewPage:
    users: tuple[UserOverview, ...]
    total: int
    """How many Users match, across every page."""


# Most urgent first, in the order CONTEXT.md lists the verdicts.
_URGENCY = {verdict: rank for rank, verdict in enumerate(StatusVerdict)}


def _over(plan: PersonPlan | None) -> bool:
    """Whether someone has more than the Plan they have allows of any limit."""
    return plan is not None and bool(plan.over)


def _by_verdict(
    users: Sequence[User], statuses: Mapping[UserId, InstallationStatus], query: OverviewQuery
) -> list[User]:
    """`users` whose verdict the query asks for, the most urgent first when it sorts by it."""
    matching = [user for user in users if query.verdict in (None, statuses[user.id].health)]
    if query.by_verdict:
        matching.sort(
            key=lambda user: _URGENCY[statuses[user.id].health], reverse=query.users.descending
        )
    return matching


@dataclass(slots=True)
class OperatorOverview:
    """The Installation Administrator's view of every User's health: the list under People and
    each person's page. Both come from `_overviews`, so they cannot differ."""

    users: UserDirectory
    statuses: UserStatuses
    installation: InstallationUnitOfWorkFactory
    clock: Clock
    allowances: Allowances
    plans: PlanCatalog
    assignments: PlanAssignments

    def page(self, actor: UserId, query: OverviewQuery) -> OverviewPage:
        require_administrator(self.users, actor)
        if query.verdict is None and not query.by_verdict and not query.over:
            found = self.users.find(query.users)
            return OverviewPage(self._overviews(found.users), found.total)
        # A verdict and being over a limit are computed, not stored, so filtering or sorting by
        # them reads everyone who matches the rest of the query, then pages; resource use is read
        # only for the page shown.
        # Every match in one read, so someone who joins meanwhile is neither missed nor counted
        # without being assessed.
        matching = list(self.users.find(replace(query.users, offset=0, limit=None)).users)
        plans = None
        if query.over:
            plans = self._person_plans(matching)
            matching = [user for user in matching if _over(plans.get(user.id))]
        statuses = None
        if query.verdict is not None or query.by_verdict:
            statuses = self.statuses.of([user.id for user in matching])
            matching = _by_verdict(matching, statuses, query)
        start = query.users.offset
        end = None if query.users.limit is None else start + query.users.limit
        shown = matching[start:end]
        return OverviewPage(self._overviews(shown, statuses, plans), len(matching))

    def of(self, actor: UserId, subject: UserId) -> UserOverview:
        """One User's overview, for an Installation Administrator. Anyone else is told, as for
        a User who does not exist, that there is no such User, so nothing is revealed."""
        try:
            require_administrator(self.users, actor)
        except AdministratorRequired as refused:
            raise UserNotFound(f"user {subject.value} does not exist") from refused
        return self._overview(subject)

    def _overview(self, subject: UserId) -> UserOverview:
        user = self.users.get(subject)
        if user is None:
            raise UserNotFound(f"user {subject.value} does not exist")
        return self._overviews([user])[0]

    def _overviews(
        self,
        users: Sequence[User],
        statuses: Mapping[UserId, InstallationStatus] | None = None,
        plans: Mapping[UserId, PersonPlan] | None = None,
    ) -> tuple[UserOverview, ...]:
        """What the overview shows about each of `users`, with the statuses and Plans already
        read."""
        ids = [user.id for user in users]
        since = first_counted_day(self.clock.now().astimezone(UTC).date())
        statuses = statuses if statuses is not None else self.statuses.of(ids)
        with self.installation() as installation:
            resources = installation.resource_use(ids, since)
        plans = plans if plans is not None else self._person_plans(users)
        return tuple(
            UserOverview(user, statuses[user.id], resources[user.id], since, plans.get(user.id))
            for user in users
        )

    def _person_plans(self, users: Sequence[User]) -> Mapping[UserId, PersonPlan]:
        """Each User's Plan, read at once for them all, once any Plan exists. None while no
        Plan exists, and none when Plans cannot be read: a Plans fault never fails People or a
        person's page."""
        try:
            return self._read_person_plans(users) if self.plans.any_plans() else {}
        except Exception as error:
            # Only the class: the error's text could name more than the Users shown.
            logger.warning(
                "The Operator Overview could not read Plans, so it shows none (%s)",
                error.__class__.__name__,
            )
            return {}

    def _read_person_plans(self, users: Sequence[User]) -> dict[UserId, PersonPlan]:
        ids = [user.id for user in users]
        allowances = self.allowances.of_users(ids)
        chosen = self.plans.settings().default
        default = self.plans.get(chosen) if chosen is not None else None
        changes = self.assignments.last_changes(ids)
        givers = self._emails({change.actor for change in changes.values()})
        with self.installation() as installation:
            use = installation.plan_use(ids)
        return {
            user.id: _given(
                person_plan(user, allowances[user.id], default, use.get(user.id)),
                changes.get(user.id),
                givers,
            )
            for user in users
        }

    def _emails(self, users: Iterable[UserId | None]) -> dict[UserId, str | None]:
        """The email of each of `users` still here, each read once."""
        found = (self.users.get(user) for user in users if user is not None)
        return {user.id: user.email for user in found if user is not None}

    def plans_of(self, actor: UserId, users: Sequence[User]) -> dict[UserId, PersonPlan]:
        """Each of `users`' Plan, as their pages show it, for giving them another. Unlike People,
        it fails when Plans cannot be read, as every Plans route does (ADR 0038)."""
        require_administrator(self.users, actor)
        return self._read_person_plans(users)

    def plans_given(
        self, actor: UserId, users: Sequence[User], plans: Mapping[UserId, PlanKey | None]
    ) -> dict[UserId, PersonPlan]:
        """What each of `users`' Plan would be were the one `plans` names their own, None or the
        default's key for the Default Plan, read now and changing nothing: so an administrator
        sees who would be over before giving it. Raises PlanNotFound before anything is counted,
        and fails when Plans cannot be read."""
        require_administrator(self.users, actor)
        setting = self.plans.settings()
        own = self._own_plans(plans.values(), setting.default)
        default = self.plans.get(setting.default) if setting.default is not None else None
        with self.installation() as installation:
            use = installation.plan_use([user.id for user in users])
        return {
            user.id: person_plan(
                user,
                allowance_for(
                    plans_on=setting.enabled,
                    administers=user.administers,
                    own=own[plans[user.id]],
                    default=default,
                ),
                default,
                use.get(user.id),
            )
            for user in users
        }

    def _own_plans(
        self, keys: Iterable[PlanKey | None], default: PlanKey | None
    ) -> dict[PlanKey | None, Plan | None]:
        """The Plan each of `keys` gives as someone's own: none for None and for the default's
        key, because giving the Default Plan is following it, as the store records it (ADR 0038).
        Raises PlanNotFound."""
        own: dict[PlanKey | None, Plan | None] = {None: None, default: None}
        for key in keys:
            if key is not None and key not in own:
                plan = self.plans.get(key)
                if plan is None:
                    raise PlanNotFound(f"plan {key.value} does not exist")
                own[key] = plan
        return own

    def reach_of(self, actor: UserId, plans: Iterable[Plan]) -> dict[PlanKey, PlanReach]:
        """How much the people each of `plans` limits use, for People's Plans tab: those People
        finds by the Plan whom it limits, counted as their pages count them. Unlike People, it
        fails when it cannot be read, as every Plans route does (ADR 0038)."""
        require_administrator(self.users, actor)
        limited = {
            plan: [
                user.id
                for user in self.users.find(UserQuery(plan=plan.key, limit=None)).users
                if user.limited_by_plans
            ]
            for plan in plans
        }
        with self.installation() as installation:
            use = installation.plan_use({user for users in limited.values() for user in users})
        return {
            plan.key: plan_reach(plan.limits, (use[user] for user in users))
            for plan, users in limited.items()
        }
