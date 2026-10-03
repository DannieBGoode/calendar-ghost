"""Runs log what they are doing with identifiers, counts, and durations, never event content."""

from __future__ import annotations

import logging
import re
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

import pytest

from calendar_sync.application.errors import (
    ProviderFailure,
    ProviderFailureKind,
    RemovalInterrupted,
    RuleNotExecutable,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    CreatedProjection,
    ProjectionDeleter,
    ProviderCallTally,
    ProviderChangeSet,
)
from calendar_sync.application.reconciliation import ReconcileSyncRule
from calendar_sync.application.removal import RemoveSyncRule
from calendar_sync.application.run_log import UntalliedProviderCalls, duration
from calendar_sync.application.sync_run import SyncRunLog
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarEvent,
    ConnectedAccountId,
    EventProjection,
    EventRef,
    ProjectionContent,
    ProjectionHandling,
    SyncAction,
    SyncRuleId,
    SyncRuleState,
    TransformationPolicy,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    ReconciliationService,
    SyncDecisionService,
)
from calendar_sync.infrastructure.identifiers import UuidRunIdGenerator
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import NOW, endpoint, event, rule, series

RUN = r"[0-9a-f]{32}"


@pytest.fixture
def logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG, logger="calendar_sync")
    return caplog


def lines(caplog: pytest.LogCaptureFixture, start: str) -> list[str]:
    return [
        record.getMessage() for record in caplog.records if record.getMessage().startswith(start)
    ]


@dataclass
class SteppedClock:
    """A clock that moves only when the test or a slow fake moves it."""

    current: datetime = NOW

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


@dataclass
class SlowCalendars(FakeCalendars):
    """Each projection Google creates takes 20 seconds of the rule's run."""

    clock: SteppedClock = field(default_factory=SteppedClock)

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection:
        self.clock.advance(20)
        return super().create_projection(destination, source, rule_id, projection, operation_key)


@dataclass
class CountedCalls:
    """Call statistics a test sets, standing in for the Google adapter's measurement."""

    tally: ProviderCallTally = field(default_factory=ProviderCallTally)
    measured: int = 0

    def measure(self) -> AbstractContextManager[ProviderCallTally]:
        # Not @contextmanager, which cannot re-raise frozen errors such as RemovalInterrupted.
        self.measured += 1
        return nullcontext(self.tally)


def use_case(
    factory: InMemoryUnitOfWorkFactory,
    calendars: FakeCalendars,
    clock: SteppedClock | None = None,
    calls: CountedCalls | None = None,
) -> ExecuteSyncRule:
    fingerprinter = ProjectionFingerprinter()
    return ExecuteSyncRule(
        factory,
        calendars,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        clock or SteppedClock(),
        UuidRunIdGenerator(),
        call_stats=calls or UntalliedProviderCalls(),
    )


def test_a_first_run_logs_its_start_listing_and_finish(logs: pytest.LogCaptureFixture) -> None:
    calendars = FakeCalendars()
    calendars.put(event("one"))
    calendars.put(event("two"))
    calls = CountedCalls(ProviderCallTally(1630, 812.4, 1.31, 2, 1, 1))

    result = use_case(enabled_rule_factory(), calendars, calls=calls).execute(rule().id)

    assert calls.measured == 1
    assert lines(logs, "run started") == [
        f"run started rule=rule-1 run={result.run_id} mode=full reason=first-run"
    ]
    assert lines(logs, "listing done") == [
        f"listing done rule=rule-1 run={result.run_id} source events=2 destination events=0"
    ]
    assert lines(logs, "run finished") == [
        f"run finished rule=rule-1 run={result.run_id} in 0s created=2 updated=0 deleted=0 "
        "ignored=0 conflicts=0 provider_calls=1630 token_refreshes=1 rate_limited=2 "
        "server_errors=1 slowest_call=1.3s"
    ]


def test_the_start_line_says_why_the_run_lists_what_it_lists(
    logs: pytest.LogCaptureFixture,
) -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    execute = sync_use_case(factory, calendars)
    execute.execute(rule().id)
    logs.clear()

    execute.execute(rule().id)
    execute.execute(rule().id, full=True)
    with factory() as uow:
        uow.rules.save(replace(rule(), reprojection_required=True))
        uow.commit()
    execute.execute(rule().id)

    started = [re.sub(f"run={RUN}", "run=…", line) for line in lines(logs, "run started")]
    assert started == [
        "run started rule=rule-1 run=… mode=incremental reason=changes",
        "run started rule=rule-1 run=… mode=full reason=daily-pass",
        "run started rule=rule-1 run=… mode=reprojection reason=reprojection",
    ]
    assert [re.sub(f"run={RUN}", "run=…", line) for line in lines(logs, "reprojecting")] == [
        "reprojecting remaining rule=rule-1 run=… mappings=0"
    ]


def test_a_rejected_cursor_is_logged_with_the_full_listing_it_causes(
    logs: pytest.LogCaptureFixture,
) -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    execute = sync_use_case(enabled_rule_factory(), calendars)
    execute.execute(rule().id)
    calendars.expired.add(rule().source)
    logs.clear()

    result = execute.execute(rule().id)

    assert lines(logs, "cursor rejected") == [
        f"cursor rejected rule=rule-1 run={result.run_id} feed=source; listed in full"
    ]


def test_progress_is_logged_at_most_every_thirty_seconds(logs: pytest.LogCaptureFixture) -> None:
    clock = SteppedClock()
    log = SyncRunLog(SyncRuleId("rule-1"), clock, ProviderCallTally(calls=12), NOW)
    log.begin("run-1", "full", "first-run")
    counts = {action: 0 for action in SyncAction}
    counts[SyncAction.IGNORE] = 3

    for seconds in (10, 19, 1, 15, 15, 400):
        clock.advance(seconds)
        log.progress(counts, handled=5, total=None)

    assert lines(logs, "run progress") == [
        "run progress rule=rule-1 run=run-1 decided=3 handled=5 created=0 updated=0 deleted=0 "
        "ignored=3 conflicts=0 elapsed=30s provider_calls=12",
        "run progress rule=rule-1 run=run-1 decided=3 handled=5 created=0 updated=0 deleted=0 "
        "ignored=3 conflicts=0 elapsed=1m00s provider_calls=12",
        "run progress rule=rule-1 run=run-1 decided=3 handled=5 created=0 updated=0 deleted=0 "
        "ignored=3 conflicts=0 elapsed=7m40s provider_calls=12",
    ]


def test_a_long_run_reports_its_progress_as_it_decides(logs: pytest.LogCaptureFixture) -> None:
    clock = SteppedClock()
    calendars = SlowCalendars(clock=clock)
    for index in range(4):
        calendars.put(event(f"event-{index}"))

    result = use_case(enabled_rule_factory(), calendars, clock).execute(rule().id)

    # Each write takes 20 seconds; progress is checked at each decision and each handled event.
    assert lines(logs, "run progress") == [
        f"run progress rule=rule-1 run={result.run_id} decided=2 handled=2/4 created=2 "
        "updated=0 deleted=0 ignored=0 conflicts=0 elapsed=40s provider_calls=0",
        f"run progress rule=rule-1 run={result.run_id} decided=4 handled=4/4 created=4 "
        "updated=0 deleted=0 ignored=0 conflicts=0 elapsed=1m20s provider_calls=0",
    ]
    assert lines(logs, "run finished")[0].startswith(
        f"run finished rule=rule-1 run={result.run_id} in 1m20s created=4 "
    )


def test_a_failed_run_logs_its_failure_kind_and_duration(logs: pytest.LogCaptureFixture) -> None:
    calendars = FailingCalendars(ProviderFailure(ProviderFailureKind.RATE_LIMIT, "quota"))
    calendars.put(event())

    with pytest.raises(ProviderFailure):
        sync_use_case(enabled_rule_factory(), calendars).execute(rule().id)

    [failed] = [record for record in logs.records if record.getMessage().startswith("run failed")]
    assert failed.levelno == logging.WARNING
    assert re.fullmatch(
        f"run failed rule=rule-1 run={RUN} kind=rate_limit after 0s provider_calls=0 "
        "token_refreshes=0 rate_limited=0 server_errors=0 slowest_call=0.0s",
        failed.getMessage(),
    )


def test_an_unexpected_error_is_logged_as_an_infrastructure_failure(
    logs: pytest.LogCaptureFixture,
) -> None:
    calendars = FailingCalendars(RuntimeError("disk full"))
    calendars.put(event())

    with pytest.raises(RuntimeError):
        sync_use_case(enabled_rule_factory(), calendars).execute(rule().id)

    assert "kind=infrastructure" in lines(logs, "run failed")[0]


def test_a_run_stopped_by_a_rule_change_is_logged_as_information(
    logs: pytest.LogCaptureFixture,
) -> None:
    # A run stops this way when the rule is paused or edited while it runs.
    stopping = FailingCalendars(RuleNotExecutable("sync rule changed during synchronization"))

    with pytest.raises(RuleNotExecutable):
        sync_use_case(enabled_rule_factory(), stopping).execute(rule().id)
    with pytest.raises(RuleNotExecutable):
        sync_use_case(
            enabled_rule_factory(rule(state=SyncRuleState.PAUSED)), FakeCalendars()
        ).execute(rule().id)

    stopped = [record for record in logs.records if record.getMessage().startswith("run ")]
    assert [record.levelno for record in stopped][-2:] == [logging.INFO, logging.INFO]
    assert re.fullmatch(
        f"run stopped rule=rule-1 run={RUN} after 0s: rule changed", stopped[-2].getMessage()
    )
    assert stopped[-1].getMessage() == "run not started rule=rule-1: rule is not enabled"


def test_no_event_content_reaches_the_logs(logs: pytest.LogCaptureFixture) -> None:
    family = endpoint("account-family", "family@example.com")
    work = endpoint("account-work", "work.calendar@example.org")
    secret_rule = replace(
        rule(),
        source=family,
        destination=work,
        transformation=TransformationPolicy(ProjectionContent.DETAILS),
    )
    calendars = FakeCalendars()
    calendars.put(event("dentist", calendar=family, title="Dentist with Dr. Secretface"))
    calendars.put(series("therapy", calendar=family, title="Therapy session Wednesdays"))
    factory = enabled_rule_factory(secret_rule)
    execute = sync_use_case(factory, calendars)

    execute.execute(secret_rule.id)
    execute.execute(secret_rule.id, full=True)
    reconcile_use_case(factory, calendars).execute(secret_rule.id)

    assert lines(logs, "run finished")
    text = logs.text
    for content in (
        "Secretface",
        "Therapy session",
        "Sensitive description",
        "Sensitive location",
        "family@example.com",
        "work.calendar@example.org",
        "dentist",
        "therapy",
    ):
        assert content not in text


def reconcile_use_case(
    factory: InMemoryUnitOfWorkFactory,
    calendars: FakeCalendars,
    calls: CountedCalls | None = None,
) -> ReconcileSyncRule:
    return ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        SteppedClock(),
        UuidRunIdGenerator(),
        call_stats=calls or UntalliedProviderCalls(),
    )


def test_reconciliation_logs_its_start_and_finish(logs: pytest.LogCaptureFixture) -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    logs.clear()

    reconcile_use_case(factory, calendars, CountedCalls(ProviderCallTally(calls=7))).execute(
        rule().id
    )

    [started] = lines(logs, "reconciliation started")
    assert re.fullmatch(f"reconciliation started rule=rule-1 run={RUN}", started)
    [finished] = lines(logs, "reconciliation finished")
    assert re.fullmatch(
        f"reconciliation finished rule=rule-1 run={RUN} in 0s checked=1 drift=0 conflicts=0 "
        "provider_calls=7 token_refreshes=0 rate_limited=0 server_errors=0 slowest_call=0.0s",
        finished,
    )


def test_a_failed_reconciliation_is_logged_as_a_warning(logs: pytest.LogCaptureFixture) -> None:
    calendars = FailingCalendars(ProviderFailure(ProviderFailureKind.TEMPORARY, "busy"))
    calendars.put(event())

    with pytest.raises(ProviderFailure):
        reconcile_use_case(enabled_rule_factory(), calendars).execute(rule().id)

    [failed] = [
        record for record in logs.records if record.getMessage().startswith("reconciliation failed")
    ]
    assert failed.levelno == logging.WARNING
    assert re.fullmatch(
        f"reconciliation failed rule=rule-1 run={RUN} kind=temporary after 0s provider_calls=0 "
        "token_refreshes=0 rate_limited=0 server_errors=0 slowest_call=0.0s",
        failed.getMessage(),
    )


@dataclass
class Connected:
    def is_connected(self, account_id: ConnectedAccountId) -> bool:
        return True


def removal(factory: InMemoryUnitOfWorkFactory, calendars: ProjectionDeleter) -> RemoveSyncRule:
    return RemoveSyncRule(
        factory,
        calendars,
        Connected(),
        SteppedClock(),
        RuleLocks(),
        call_stats=CountedCalls(ProviderCallTally(calls=3)),
        sleep=lambda _: None,
    )


def test_removal_logs_its_start_and_finish(logs: pytest.LogCaptureFixture) -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)

    removal(factory, calendars).execute(rule().id, ProjectionHandling.DELETE)

    assert lines(logs, "removal started") == [
        "removal started rule=rule-1 handling=delete mappings=1"
    ]
    assert lines(logs, "removal finished") == [
        "removal finished rule=rule-1 in 0s deleted=1 detached=0 conflicts=0 provider_calls=3 "
        "token_refreshes=0 rate_limited=0 server_errors=0 slowest_call=0.0s"
    ]


def test_an_interrupted_removal_is_logged_as_a_warning(logs: pytest.LogCaptureFixture) -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    failing = DenyingDeletes(calendars)

    with pytest.raises(RemovalInterrupted):
        removal(factory, failing).execute(rule().id, ProjectionHandling.DELETE)

    [interrupted] = [
        record for record in logs.records if record.getMessage().startswith("removal interrupted")
    ]
    assert interrupted.levelno == logging.WARNING
    assert interrupted.getMessage() == (
        "removal interrupted rule=rule-1 kind=authorization after 0s handled=0 remaining=1 "
        "provider_calls=3 token_refreshes=0 rate_limited=0 server_errors=0 slowest_call=0.0s"
    )


def test_durations_read_like_a_stopwatch() -> None:
    assert duration(timedelta(seconds=0.4)) == "0s"
    assert duration(timedelta(seconds=59)) == "59s"
    assert duration(timedelta(minutes=3, seconds=2)) == "3m02s"
    assert duration(timedelta(minutes=28, seconds=14)) == "28m14s"
    assert duration(timedelta(hours=1, minutes=2, seconds=3)) == "1h02m03s"


class FailingCalendars(FakeCalendars):
    """Every listing fails with the same error."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def changes(
        self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
    ) -> ProviderChangeSet:
        raise self.error

    def list_events(
        self, calendar: CalendarEndpoint, not_ended_before: datetime
    ) -> tuple[CalendarEvent, ...]:
        raise self.error


class DenyingDeletes:
    """Google refuses every deletion for this account."""

    def __init__(self, calendars: FakeCalendars) -> None:
        self.calendars = calendars

    def delete_projection(
        self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
    ) -> None:
        raise ProviderFailure(ProviderFailureKind.AUTHORIZATION, "denied")
