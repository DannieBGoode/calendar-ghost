# Installation Status for Monitors and Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Uptime Kuma, homelab dashboards, and AI agents read Calendar Ghost's health through
Integration Tokens, `GET /api/v1/status`, and an MCP server at `/mcp`, with one health verdict that
the Overview shares.

**Architecture:** A pure application function decides the Installation Status from rule summaries,
the operations overview, open incidents, and a new scheduler heartbeat. A SQLite adapter stores
hashed Integration Tokens. The FastAPI interface serves the status and token routes; a new
`interfaces/mcp` package serves the same status through the official MCP SDK, mounted as one
Starlette route. The Overview renders the server's verdict.

**Tech Stack:** Python 3.12, FastAPI 0.142, Starlette 1.7, SQLite, `mcp` 2.3 (`MCPServer`),
React 19, TanStack Query, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-03-integration-status-design.md`

## Global Constraints

- Integration Token format: `cgs_` followed by exactly 43 URL-safe base64 characters
  (`secrets.token_urlsafe(32)`).
- Only a SHA-256 hash of a token is stored; `token_hash` is unique and indexed.
- Token names: trimmed, 1 to 80 characters, no control characters.
- `last_used_at` is written at most once every 5 minutes per token.
- The only scope is `status:read`.
- Only `/api/v1/status` and `/mcp` accept an Integration Token. Every other API route keeps
  `require_admin`.
- A present `Authorization` header that is not a valid token is refused even with a valid cookie.
- `/mcp` never accepts the session cookie.
- `/api/v1/status` answers 200 with `Cache-Control: no-store` for every authorized request.
- Stalled: enabled rules exist and either no pass is running and none completed within 15 minutes
  (counting from scheduler construction before the first pass), or the running pass started more
  than 3 hours ago, or there is no scheduler.
- Overdue: an enabled rule that has succeeded before, has no running work, has no other problem,
  and whose last success is more than 24 hours old, while the scheduler is not stalled.
- Provider waiting (`rate_limit`, `temporary`) older than 24 hours counts as review.
- `needs_attention` is true only for `stalled`, `stopped`, and `review`.
- The status payload never contains calendar IDs, account IDs, emails, event titles, Activity, or
  token data.
- MCP SDK dependency: `mcp>=2.3,<3`. Import `MCPServer` from `mcp.server.mcpserver`; `FastMCP` no
  longer exists.
- No em dashes (U+2014) in code, comments, copy, docs, or commit messages. Use the domain terms in
  `CONTEXT.md`.
- Backend gate: `ruff format --check .`, `ruff check .`, `mypy`, `lint-imports`,
  `pytest --cov --cov-fail-under=80`. Frontend gate: `typecheck`, `lint`, `test`, `build`, and
  commit the regenerated `src/calendar_sync/interfaces/api/static/`.

## Deviations from the spec

- The token port method is `authenticate(token)`, not `authorize(token, scope)`; the caller checks
  the scope so a token without it can answer 403.
- No in-memory token adapter: tests use SQLite in `tmp_path`, as administrator sessions do.
- Each problem also carries `since` (when its incident opened, or the last success for an overdue
  rule) so the Overview can keep its "First seen" wording.
- The MCP SDK server is created once per application lifespan, because a session manager runs only
  once and tests start the same app more than once.

## Review Focus

1. **A bearer header beside a valid session cookie.** A misconfigured monitor in a browser profile
   must still get 401, so the broken credential is visible. Pinned in Task 4.
2. **A token on any other API route.** A leaked status token must never read rules, Activity, or
   accounts. Task 4 sends a valid token to every other API route and expects 401.
3. **`GET /mcp` from an MCP client.** In stateless mode the SDK would hold an SSE stream open
   forever; the gate answers 405 so no connection hangs. Pinned in Task 5.
4. **A rule whose removal is running.** The administrator just removed it; it must not turn the
   Overview red. Pinned in Task 2.
5. **A Host header that is not localhost (`ghost.lan:8000`).** The SDK's default allowlist would
   answer 421; the plan turns it off. Pinned in Task 5.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/calendar_sync/application/ports.py` | Add `SchedulerProgress`, `SchedulerHeartbeat`, Integration Token types and port |
| `src/calendar_sync/application/activity.py` | Add `AccountStanding` and `OperationsOverview.accounts` |
| `src/calendar_sync/application/status.py` (new) | The Installation Status verdict: pure `assess_installation` and the `GetInstallationStatus` use case |
| `src/calendar_sync/application/integration_tokens.py` (new) | Token format and name rules |
| `src/calendar_sync/application/errors.py` | `InvalidIntegrationTokenName` |
| `src/calendar_sync/infrastructure/scheduling.py` | Record pass start and completion |
| `src/calendar_sync/infrastructure/integration_tokens.py` (new) | `SqliteIntegrationTokens` |
| `src/calendar_sync/infrastructure/security.py` | Make the token hash function public |
| `src/calendar_sync/infrastructure/persistence/0018_integration_tokens.sql` (new) | The table |
| `src/calendar_sync/infrastructure/persistence/sqlite.py` | Register migration 18 |
| `src/calendar_sync/infrastructure/persistence/activity_queries.py` | Fill `OperationsOverview.accounts` |
| `src/calendar_sync/bootstrap/container.py` | Compose tokens and the status use case |
| `src/calendar_sync/interfaces/access.py` (new) | `status_access`, shared by the API and MCP |
| `src/calendar_sync/interfaces/api/status_payload.py` (new) | Status to response schema translation, shared by the API and MCP |
| `src/calendar_sync/interfaces/api/schemas.py` | Status, problem, and token schemas; dashboard fields |
| `src/calendar_sync/interfaces/api/dependencies.py` | `require_status_reader` |
| `src/calendar_sync/interfaces/api/routes/integrations.py` (new) | Token management and `GET /api/v1/status` |
| `src/calendar_sync/interfaces/api/routes/activity.py` | Dashboard reads the verdict |
| `src/calendar_sync/interfaces/api/app.py` | Register the router, mount MCP, run its session manager |
| `src/calendar_sync/interfaces/mcp/__init__.py`, `server.py` (new) | MCP server, tools, and gate |
| `pyproject.toml` | `mcp` dependency and import-linter contracts |
| `web/src/lib/api.ts` | Dashboard, problem, and token types; token calls |
| `web/src/lib/overview-health.ts` | Render server status and problems |
| `web/src/features/overview.tsx` | Drop client-side verdict inputs |
| `web/src/lib/integrations.ts` (new) | Integration examples and token usage text |
| `web/src/features/settings.tsx` | Integrations section |
| Docs | ADR 0023, `CONTEXT.md`, `docs/self-hosting.md`, `AGENTS.md`, `CHANGELOG.md` |

---

### Task 1: Scheduler heartbeat

**Files:**
- Modify: `src/calendar_sync/application/ports.py` (after `Clock`, around line 465)
- Modify: `src/calendar_sync/infrastructure/scheduling.py:30-70`
- Test: `tests/adapters/test_scheduling.py`

**Interfaces:**
- Produces:
  - `SchedulerProgress(running_since: datetime, pass_started_at: datetime | None, last_completed_at: datetime | None)`
  - `class SchedulerHeartbeat(Protocol): def progress(self) -> SchedulerProgress`
  - `SyncScheduler.progress() -> SchedulerProgress`

- [ ] **Step 1: Write the failing tests**

Append to `tests/adapters/test_scheduling.py`:

```python
class SteppingClock:
    """A clock that moves forward by one minute each time it is read."""

    def __init__(self, start: datetime) -> None:
        self.moment = start

    def now(self) -> datetime:
        current = self.moment
        self.moment = current + timedelta(minutes=1)
        return current


def test_the_scheduler_reports_when_it_started_and_its_last_completed_pass() -> None:
    clock = SteppingClock(datetime(2026, 10, 3, 9, 0, tzinfo=UTC))
    scheduler = SyncScheduler(
        cast(ExecuteSyncRule, RecordingExecuteRule([])),
        InMemoryUnitOfWorkFactory(),
        cast(RunHealth, Mock()),
        clock=clock,
    )

    before = scheduler.progress()
    asyncio.run(scheduler.run_once())
    after = scheduler.progress()

    assert before.running_since == datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
    assert before.pass_started_at is None
    assert before.last_completed_at is None
    assert after.pass_started_at is None
    assert after.last_completed_at is not None
    assert after.last_completed_at > after.running_since


def test_a_pass_that_raises_is_not_counted_as_completed() -> None:
    class BrokenUnitOfWork:
        def __call__(self) -> UnitOfWork:
            raise sqlite3.OperationalError("database is locked")

    scheduler = SyncScheduler(
        cast(ExecuteSyncRule, RecordingExecuteRule([])),
        cast(UnitOfWorkFactory, BrokenUnitOfWork()),
        cast(RunHealth, Mock()),
        clock=SteppingClock(datetime(2026, 10, 3, 9, 0, tzinfo=UTC)),
    )

    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(scheduler.run_once())

    progress = scheduler.progress()
    assert progress.pass_started_at is None
    assert progress.last_completed_at is None
```

Add `timedelta` to the `datetime` import and `from unittest.mock import Mock` at the top of the
file if they are not already imported.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_scheduling.py -k "reports_when_it_started or raises_is_not_counted" -v`
Expected: FAIL with `AttributeError: 'SyncScheduler' object has no attribute 'progress'`

- [ ] **Step 3: Add the port**

In `src/calendar_sync/application/ports.py`, after `class Clock(Protocol)`:

```python
@dataclass(frozen=True, slots=True)
class SchedulerProgress:
    """What the scheduler did last, so Installation Status can see a scheduler that stopped."""

    running_since: datetime
    """When the scheduler was created; the baseline until its first pass completes."""
    pass_started_at: datetime | None
    """When the pass running now started; None between passes."""
    last_completed_at: datetime | None
    """When the last pass that raised nothing completed."""


class SchedulerHeartbeat(Protocol):
    def progress(self) -> SchedulerProgress: ...
```

- [ ] **Step 4: Record progress in `SyncScheduler`**

In `src/calendar_sync/infrastructure/scheduling.py`, import `SchedulerProgress` from
`calendar_sync.application.ports`. At the end of `__init__` add:

```python
        # Read from request threads while the event loop writes; each is one attribute store.
        self._running_since = self._clock.now()
        self._pass_started_at: datetime | None = None
        self._last_completed_at: datetime | None = None
```

Rename the current body of `run_once` to a new private method `_run_pass` (same code, same
signature `async def _run_pass(self) -> None`), and make `run_once`:

```python
    async def run_once(self) -> None:
        self._pass_started_at = self._clock.now()
        try:
            await self._run_pass()
        finally:
            self._pass_started_at = None
        self._last_completed_at = self._clock.now()

    def progress(self) -> SchedulerProgress:
        return SchedulerProgress(
            self._running_since, self._pass_started_at, self._last_completed_at
        )
```

- [ ] **Step 5: Run the scheduling tests**

Run: `.venv/bin/pytest tests/adapters/test_scheduling.py -v`
Expected: PASS, including every test that existed before. If an existing test counts clock reads,
update its expected count by the two new reads and say so in the commit message.

- [ ] **Step 6: Commit**

```bash
git add src/calendar_sync/application/ports.py src/calendar_sync/infrastructure/scheduling.py tests/adapters/test_scheduling.py
git commit -m "feat: report scheduler progress for Installation Status"
```

---

### Task 2: The Installation Status verdict

**Files:**
- Modify: `src/calendar_sync/application/activity.py` (`OperationsOverview`, around line 178)
- Modify: `src/calendar_sync/infrastructure/persistence/activity_queries.py:267-290`
- Create: `src/calendar_sync/application/status.py`
- Test: `tests/application/test_status.py`, `tests/adapters/test_activity_queries.py`

**Interfaces:**
- Consumes: `SchedulerProgress`, `SchedulerHeartbeat` (Task 1); `SyncRuleSummary` and
  `ListSyncRules` from `application/rules.py`; `OperationsQueries`, `IncidentSummary`,
  `OperationsOverview` from `application/activity.py`.
- Produces (all in `calendar_sync.application.status`):
  - `class InstallationHealth(StrEnum)`: `STALLED="stalled"`, `STOPPED="stopped"`,
    `REVIEW="review"`, `WAITING="waiting"`, `PAUSED="paused"`, `SETUP="setup"`,
    `HEALTHY="healthy"`
  - `class ProblemKind(StrEnum)`: `STALLED`, `STOPPED`, `REVIEW`, `OVERDUE`, `BLOCKED`, `WAITING`
    with lowercase values
  - `Problem(kind: ProblemKind, rule_id: str | None, summary: str, since: datetime | None)`
  - `RuleStatus(summary: SyncRuleSummary, name: str, problem: Problem | None)`
  - `InstallationStatus(health, problems: tuple[Problem, ...], rules: tuple[RuleStatus, ...], open_incidents: tuple[IncidentSummary, ...], overview: OperationsOverview, scheduler: SchedulerProgress | None, checked_at: datetime)`
    with properties `needs_attention: bool`, `summary: str`, `providers: Mapping[str, str]`
  - `assess_installation(rules, overview, incidents, scheduler, now) -> InstallationStatus`
  - `GetInstallationStatus(rules: ListSyncRules, operations: OperationsQueries, clock: Clock, scheduler: SchedulerHeartbeat | None)` with `execute() -> InstallationStatus`
  - `rule_name(summary: SyncRuleSummary) -> str`
  - `AccountStanding(id: str, state: str, provider: str)` in `application/activity.py`

- [ ] **Step 1: Add account standings to the operations overview (test first)**

In `tests/adapters/test_activity_queries.py`, add:

```python
def test_the_overview_lists_each_account_state_and_provider(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO connected_accounts (
                id, provider, display_name, email, encrypted_credentials,
                state, created_at, updated_at
            ) VALUES (?, 'google', ?, ?, x'00', ?, '2026-09-01', '2026-09-01')
            """,
            [
                ("acct-a", "A", "a@example.test", "connected"),
                ("acct-b", "B", "b@example.test", "disconnected"),
            ],
        )

    overview = SqliteOperationsQueries(database).overview()

    assert overview.accounts == (
        AccountStanding("acct-a", "connected", "google"),
        AccountStanding("acct-b", "disconnected", "google"),
    )
    assert (overview.connected_accounts, overview.disconnected_accounts) == (1, 1)
```

Import `AccountStanding` from `calendar_sync.application.activity`, and `sqlite3`,
`initialize_database`, `SqliteOperationsQueries` if the file does not already import them.

Run: `.venv/bin/pytest tests/adapters/test_activity_queries.py -k account_state -v`
Expected: FAIL with `ImportError: cannot import name 'AccountStanding'`

- [ ] **Step 2: Implement account standings**

In `src/calendar_sync/application/activity.py`, before `OperationsOverview`:

```python
@dataclass(frozen=True, slots=True)
class AccountStanding:
    """A Connected Account's state and Provider Kind; never its email or name."""

    id: str
    state: str
    provider: str
```

Add a last field to `OperationsOverview`:

```python
    accounts: tuple[AccountStanding, ...] = ()
    """Every Connected Account, ordered by id."""
```

In `SqliteOperationsQueries.overview`, replace the account-count query with:

```python
            accounts = tuple(
                AccountStanding(str(row["id"]), str(row["state"]), str(row["provider"]))
                for row in connection.execute(
                    "SELECT id, state, provider FROM connected_accounts ORDER BY id"
                )
            )
```

and build the counts from it:

```python
        return OperationsOverview(
            connected_accounts=sum(account.state == "connected" for account in accounts),
            disconnected_accounts=sum(account.state == "disconnected" for account in accounts),
            open_incidents=incidents,
            last_synced_at=last_synced_at,
            open_blocks=tuple(OpenBlock(entry_id, rule_id) for entry_id, rule_id in blocks),
            accounts=accounts,
        )
```

Run: `.venv/bin/pytest tests/adapters/test_activity_queries.py -v`
Expected: PASS

- [ ] **Step 3: Write the failing verdict tests**

Create `tests/application/test_status.py`:

```python
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.application.activity import (
    AccountStanding,
    IncidentSummary,
    OpenBlock,
    OperationsOverview,
)
from calendar_sync.application.locking import RuleWork, RuleWorkKind
from calendar_sync.application.ports import RuleRunOutcome, RunKind, SchedulerProgress
from calendar_sync.application.rules import SyncRuleSummary
from calendar_sync.application.status import (
    InstallationHealth,
    InstallationStatus,
    ProblemKind,
    assess_installation,
    rule_name,
)
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from tests.helpers import endpoint

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
CONNECTED = (
    AccountStanding("personal-account", "connected", "google"),
    AccountStanding("work-account", "connected", "google"),
)
TICKING = SchedulerProgress(NOW - timedelta(days=1), None, NOW - timedelta(minutes=2))


def _rule(rule_id: str = "rule-1", state: SyncRuleState = SyncRuleState.ENABLED) -> SyncRule:
    return SyncRule(
        id=SyncRuleId(rule_id),
        source=endpoint("personal-account", f"{rule_id}-source"),
        destination=endpoint("work-account", f"{rule_id}-destination"),
        state=state,
    )


def _summary(
    rule: SyncRule,
    *,
    succeeded_at: datetime | None = NOW - timedelta(minutes=2),
    running: RuleWork | None = None,
) -> SyncRuleSummary:
    last_sync = (
        RuleRunOutcome(
            rule.id, RunKind.SYNC, succeeded_at, succeeded=True, last_succeeded_at=succeeded_at
        )
        if succeeded_at
        else None
    )
    names = {rule.source: "Personal", rule.destination: "Work"}
    return SyncRuleSummary(rule, last_sync, None, running, names)


def _overview(
    *,
    accounts: tuple[AccountStanding, ...] = CONNECTED,
    open_incidents: int = 0,
    blocks: tuple[OpenBlock, ...] = (),
    last_synced_at: str | None = "2026-10-03T11:58:00+00:00",
) -> OperationsOverview:
    return OperationsOverview(
        connected_accounts=sum(a.state == "connected" for a in accounts),
        disconnected_accounts=sum(a.state == "disconnected" for a in accounts),
        open_incidents=open_incidents,
        last_synced_at=last_synced_at,
        open_blocks=blocks,
        accounts=accounts,
    )


def _incident(
    rule_id: str | None, category: str, *, opened: datetime = NOW - timedelta(hours=1)
) -> IncidentSummary:
    return IncidentSummary(
        id=f"incident-{rule_id}-{category}",
        rule_id=rule_id,
        category=category,
        state="open",
        summary="Calendar provider authorization expired",
        opened_at=opened.isoformat(),
        updated_at=opened.isoformat(),
    )


def _assess(
    summaries: list[SyncRuleSummary],
    overview: OperationsOverview | None = None,
    incidents: tuple[IncidentSummary, ...] = (),
    scheduler: SchedulerProgress | None = TICKING,
) -> InstallationStatus:
    return assess_installation(
        summaries,
        overview or _overview(open_incidents=len(incidents)),
        incidents,
        scheduler,
        NOW,
    )


def test_a_running_installation_is_healthy() -> None:
    status = assess_installation([_summary(_rule())], _overview(), (), TICKING, NOW)
    assert status.health is InstallationHealth.HEALTHY
    assert status.needs_attention is False
    assert status.problems == ()
    assert status.summary == "1 rule running."


def test_rule_names_use_last_known_calendar_names() -> None:
    summary = _summary(_rule())
    assert rule_name(summary) == "Personal → Work"
    assert rule_name(replace(summary, names={})) == "Unnamed calendar → Unnamed calendar"


@pytest.mark.parametrize(
    ("progress", "health"),
    [
        (SchedulerProgress(NOW - timedelta(minutes=14), None, None), InstallationHealth.HEALTHY),
        (SchedulerProgress(NOW - timedelta(minutes=16), None, None), InstallationHealth.STALLED),
        (
            SchedulerProgress(NOW - timedelta(days=1), None, NOW - timedelta(minutes=14)),
            InstallationHealth.HEALTHY,
        ),
        (
            SchedulerProgress(NOW - timedelta(days=1), None, NOW - timedelta(minutes=16)),
            InstallationHealth.STALLED,
        ),
        (
            SchedulerProgress(
                NOW - timedelta(days=1), NOW - timedelta(hours=2, minutes=59), NOW - timedelta(hours=3)
            ),
            InstallationHealth.HEALTHY,
        ),
        (
            SchedulerProgress(
                NOW - timedelta(days=1), NOW - timedelta(hours=3, minutes=1), NOW - timedelta(hours=4)
            ),
            InstallationHealth.STALLED,
        ),
        (None, InstallationHealth.STALLED),
    ],
)
def test_a_scheduler_that_stopped_running_passes_is_stalled(
    progress: SchedulerProgress | None, health: InstallationHealth
) -> None:
    status = assess_installation([_summary(_rule())], _overview(), (), progress, NOW)
    assert status.health is health
    assert status.needs_attention is (health is InstallationHealth.STALLED)


def test_a_stalled_scheduler_without_enabled_rules_is_not_a_problem() -> None:
    status = assess_installation(
        [_summary(_rule(state=SyncRuleState.PAUSED))], _overview(), (), None, NOW
    )
    assert status.health is InstallationHealth.PAUSED


def test_a_degraded_rule_is_stopped_and_names_its_incident() -> None:
    incident = _incident("rule-1", "authentication")
    status = assess_installation(
        [_summary(_rule(state=SyncRuleState.DEGRADED))],
        _overview(open_incidents=1),
        (incident,),
        TICKING,
        NOW,
    )
    assert status.health is InstallationHealth.STOPPED
    assert status.problems[0].kind is ProblemKind.STOPPED
    assert status.problems[0].summary == "Calendar provider authorization expired"
    assert status.problems[0].since == NOW - timedelta(hours=1)
    assert status.rules[0].problem == status.problems[0]
    assert status.summary == "Personal → Work: Calendar provider authorization expired."


@pytest.mark.parametrize("side", ["personal-account", "work-account"])
def test_an_enabled_rule_with_a_disconnected_account_is_stopped(side: str) -> None:
    accounts = tuple(
        replace(account, state="disconnected") if account.id == side else account
        for account in CONNECTED
    )
    status = assess_installation([_summary(_rule())], _overview(accounts=accounts), (), TICKING, NOW)
    assert status.health is InstallationHealth.STOPPED
    assert status.problems[0].summary == "A calendar account needs reauthorization"


def test_a_rule_whose_removal_is_running_is_not_stopped() -> None:
    removing = _rule(state=SyncRuleState.REMOVING)
    work = RuleWork(RuleWorkKind.REMOVAL, NOW - timedelta(seconds=30))
    status = assess_installation(
        [_summary(_rule("rule-2")), _summary(removing, running=work)], _overview(), (), TICKING, NOW
    )
    assert status.health is InstallationHealth.HEALTHY
    assert [rule.summary.rule.id.value for rule in status.rules] == ["rule-2"]


def test_an_interrupted_removal_is_stopped() -> None:
    status = assess_installation(
        [_summary(_rule(state=SyncRuleState.REMOVING))], _overview(), (), TICKING, NOW
    )
    assert status.health is InstallationHealth.STOPPED
    assert status.problems[0].summary == "Stopped syncing"


def test_provider_waiting_turns_into_review_after_a_day() -> None:
    fresh = _incident("rule-1", "rate_limit", opened=NOW - timedelta(hours=23))
    lasting = _incident("rule-1", "rate_limit", opened=NOW - timedelta(hours=25))
    assert _assess([_summary(_rule())], incidents=(fresh,)).health is InstallationHealth.WAITING
    assert _assess([_summary(_rule())], incidents=(lasting,)).health is InstallationHealth.REVIEW


def test_waiting_does_not_need_attention() -> None:
    status = _assess([_summary(_rule())], incidents=(_incident("rule-1", "temporary"),))
    assert status.health is InstallationHealth.WAITING
    assert status.needs_attention is False


def test_open_blocks_need_a_look_and_name_their_rule() -> None:
    blocks = (OpenBlock(42, "rule-1"), OpenBlock(41, "rule-1"))
    status = _assess([_summary(_rule())], overview=_overview(blocks=blocks))
    assert status.health is InstallationHealth.REVIEW
    assert status.problems[0].kind is ProblemKind.BLOCKED
    assert status.problems[0].rule_id == "rule-1"
    assert status.problems[0].summary == "2 events couldn't be synced"


def test_a_blocked_incident_is_covered_by_the_open_blocks() -> None:
    blocked = _incident("rule-1", "conflict")
    status = _assess(
        [_summary(_rule())],
        overview=_overview(open_incidents=1, blocks=(OpenBlock(42, "rule-1"),)),
        incidents=(blocked,),
    )
    assert [problem.kind for problem in status.problems] == [ProblemKind.BLOCKED]


@pytest.mark.parametrize(("hours", "overdue"), [(23, False), (25, True)])
def test_a_rule_not_synced_for_a_day_is_overdue(hours: int, overdue: bool) -> None:
    status = _assess([_summary(_rule(), succeeded_at=NOW - timedelta(hours=hours))])
    assert (status.health is InstallationHealth.REVIEW) is overdue
    if overdue:
        assert status.problems[0].kind is ProblemKind.OVERDUE
        assert status.problems[0].since == NOW - timedelta(hours=hours)


def test_running_and_never_synced_rules_are_never_overdue() -> None:
    work = RuleWork(RuleWorkKind.SYNC, NOW - timedelta(minutes=1))
    running = _summary(_rule(), succeeded_at=NOW - timedelta(days=3), running=work)
    never = _summary(_rule("rule-2"), succeeded_at=None)
    assert _assess([running, never]).health is InstallationHealth.HEALTHY


def test_problems_are_ordered_most_urgent_first() -> None:
    status = _assess(
        [
            _summary(_rule("rule-a", SyncRuleState.DEGRADED)),
            _summary(_rule("rule-b")),
            _summary(_rule("rule-c")),
            _summary(_rule("rule-d"), succeeded_at=NOW - timedelta(days=2)),
        ],
        overview=_overview(open_incidents=2, blocks=(OpenBlock(9, "rule-x"),)),
        incidents=(_incident("rule-c", "rate_limit"), _incident("rule-b", "permanent")),
    )
    assert [(problem.kind, problem.rule_id) for problem in status.problems] == [
        (ProblemKind.STOPPED, "rule-a"),
        (ProblemKind.REVIEW, "rule-b"),
        (ProblemKind.OVERDUE, "rule-d"),
        (ProblemKind.BLOCKED, "rule-x"),
        (ProblemKind.WAITING, "rule-c"),
    ]
    assert status.health is InstallationHealth.STOPPED


def test_an_open_incident_never_reads_as_healthy() -> None:
    status = _assess([_summary(_rule())], incidents=(_incident(None, "permanent"),))
    assert status.health is InstallationHealth.REVIEW
    assert status.problems[0].rule_id is None


@pytest.mark.parametrize(
    ("summaries", "overview", "health"),
    [
        ([], _overview(accounts=()), InstallationHealth.SETUP),
        ([], _overview(), InstallationHealth.SETUP),
        (
            [_summary(_rule(state=SyncRuleState.PAUSED))],
            _overview(),
            InstallationHealth.PAUSED,
        ),
        (
            [_summary(_rule(state=SyncRuleState.PREVIEWED), succeeded_at=None)],
            _overview(last_synced_at=None),
            InstallationHealth.SETUP,
        ),
        (
            [_summary(_rule(state=SyncRuleState.PAUSED))],
            _overview(accounts=tuple(replace(a, state="disconnected") for a in CONNECTED)),
            InstallationHealth.SETUP,
        ),
    ],
)
def test_installations_without_running_rules(
    summaries: list[SyncRuleSummary], overview: OperationsOverview, health: InstallationHealth
) -> None:
    status = assess_installation(summaries, overview, (), TICKING, NOW)
    assert status.health is health
    assert status.needs_attention is False
```

Run: `.venv/bin/pytest tests/application/test_status.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'calendar_sync.application.status'`

- [ ] **Step 4: Implement `application/status.py`**

```python
"""Installation Status: one health verdict for the Overview, the status API, and MCP."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from calendar_sync.application.activity import (
    IncidentSummary,
    OperationsOverview,
    OperationsQueries,
)
from calendar_sync.application.errors import ProviderFailureKind
from calendar_sync.application.locking import RuleWorkKind
from calendar_sync.application.ports import Clock, SchedulerHeartbeat, SchedulerProgress
from calendar_sync.application.rules import ListSyncRules, SyncRuleSummary
from calendar_sync.domain.model import SyncRuleState

STALL_AFTER = timedelta(minutes=15)
"""Three scheduler intervals without a completed pass."""
PASS_LIMIT = timedelta(hours=3)
"""Far beyond the 40-minute full pass seen on a Raspberry Pi."""
OVERDUE_AFTER = timedelta(hours=24)
WAITING_LIMIT = timedelta(hours=24)

# Provider conditions that retry by themselves; nothing to do unless they last.
WAITING_CATEGORIES = frozenset({ProviderFailureKind.RATE_LIMIT.value, ProviderFailureKind.TEMPORARY.value})
# Blocked-event incidents; the open blocks already describe them.
BLOCKED_CATEGORY = "conflict"
UNNAMED_CALENDAR = "Unnamed calendar"


class InstallationHealth(StrEnum):
    STALLED = "stalled"
    STOPPED = "stopped"
    REVIEW = "review"
    WAITING = "waiting"
    PAUSED = "paused"
    SETUP = "setup"
    HEALTHY = "healthy"


NEEDS_ATTENTION = frozenset(
    {InstallationHealth.STALLED, InstallationHealth.STOPPED, InstallationHealth.REVIEW}
)


class ProblemKind(StrEnum):
    STALLED = "stalled"
    STOPPED = "stopped"
    REVIEW = "review"
    OVERDUE = "overdue"
    BLOCKED = "blocked"
    WAITING = "waiting"


_HEALTH_OF = {
    ProblemKind.STALLED: InstallationHealth.STALLED,
    ProblemKind.STOPPED: InstallationHealth.STOPPED,
    ProblemKind.REVIEW: InstallationHealth.REVIEW,
    ProblemKind.OVERDUE: InstallationHealth.REVIEW,
    ProblemKind.BLOCKED: InstallationHealth.REVIEW,
    ProblemKind.WAITING: InstallationHealth.WAITING,
}


@dataclass(frozen=True, slots=True)
class Problem:
    kind: ProblemKind
    rule_id: str | None
    summary: str
    """Operational wording only; never event content."""
    since: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuleStatus:
    summary: SyncRuleSummary
    name: str
    problem: Problem | None


@dataclass(frozen=True, slots=True)
class InstallationStatus:
    health: InstallationHealth
    problems: tuple[Problem, ...]
    rules: tuple[RuleStatus, ...]
    open_incidents: tuple[IncidentSummary, ...]
    overview: OperationsOverview
    scheduler: SchedulerProgress | None
    checked_at: datetime
    providers: Mapping[str, str] = field(default_factory=dict)
    """Each Connected Account's Provider Kind, by account id."""

    @property
    def needs_attention(self) -> bool:
        return self.health in NEEDS_ATTENTION

    @property
    def summary(self) -> str:
        if self.problems:
            first = self.problems[0]
            named = next(
                (rule.name for rule in self.rules if rule.summary.rule.id.value == first.rule_id),
                None,
            )
            return f"{named}: {first.summary}." if named else f"{first.summary}."
        running = sum(rule.summary.rule.state is SyncRuleState.ENABLED for rule in self.rules)
        if self.health is InstallationHealth.HEALTHY:
            return f"{running} {'rule' if running == 1 else 'rules'} running."
        if self.health is InstallationHealth.PAUSED:
            return "Synchronization is paused."
        return "Setup is not finished."


def rule_name(summary: SyncRuleSummary) -> str:
    source = summary.names.get(summary.rule.source, UNNAMED_CALENDAR)
    destination = summary.names.get(summary.rule.destination, UNNAMED_CALENDAR)
    return f"{source} → {destination}"


def assess_installation(
    rules: Sequence[SyncRuleSummary],
    overview: OperationsOverview,
    incidents: Sequence[IncidentSummary],
    scheduler: SchedulerProgress | None,
    now: datetime,
) -> InstallationStatus:
    """The verdict, most urgent problem first, from what the installation recorded."""
    visible = [summary for summary in rules if not _removal_running(summary)]
    enabled = [s for s in visible if s.rule.state is SyncRuleState.ENABLED]
    disconnected = {a.id for a in overview.accounts if a.state == "disconnected"}
    open_incidents = tuple(incident for incident in incidents if incident.state == "open")
    stalled = bool(enabled) and _stalled(scheduler, now)

    problems: list[Problem] = []
    if stalled:
        problems.append(Problem(ProblemKind.STALLED, None, "Scheduled synchronization stopped running"))
    problems.extend(_stopped(visible, open_incidents, disconnected))
    named: set[str | None] = {problem.rule_id for problem in problems if problem.rule_id}
    reviews, waits = _incident_problems(open_incidents, named, now)
    problems.extend(reviews)
    named |= {problem.rule_id for problem in reviews if problem.rule_id}
    if not stalled:
        problems.extend(_overdue(enabled, named, now))
    if overview.open_blocks:
        problems.append(_blocked(overview))
    problems.extend(problem for problem in waits if problem.rule_id not in named)
    if not problems and open_incidents:
        count = len(open_incidents)
        problems.append(
            Problem(
                ProblemKind.REVIEW,
                None,
                f"{count} {'problem' if count == 1 else 'problems'} kept happening",
            )
        )

    first_by_rule: dict[str, Problem] = {}
    for problem in problems:
        if problem.rule_id is not None:
            first_by_rule.setdefault(problem.rule_id, problem)
    return InstallationStatus(
        health=_health(problems, visible, enabled, overview, stalled),
        problems=tuple(problems),
        rules=tuple(
            RuleStatus(s, rule_name(s), first_by_rule.get(s.rule.id.value)) for s in visible
        ),
        open_incidents=open_incidents,
        overview=overview,
        scheduler=scheduler,
        checked_at=now,
        providers={account.id: account.provider for account in overview.accounts},
    )


def _removal_running(summary: SyncRuleSummary) -> bool:
    return (
        summary.rule.state is SyncRuleState.REMOVING
        and summary.running is not None
        and summary.running.kind is RuleWorkKind.REMOVAL
    )


def _stalled(scheduler: SchedulerProgress | None, now: datetime) -> bool:
    if scheduler is None:
        return True
    if scheduler.pass_started_at is not None:
        return now - scheduler.pass_started_at > PASS_LIMIT
    baseline = scheduler.last_completed_at or scheduler.running_since
    return now - baseline > STALL_AFTER


def _stopped(
    visible: Sequence[SyncRuleSummary],
    incidents: Sequence[IncidentSummary],
    disconnected: set[str],
) -> list[Problem]:
    problems = []
    for summary in visible:
        rule = summary.rule
        lost_account = rule.state is SyncRuleState.ENABLED and bool(
            {rule.source.connected_account_id.value, rule.destination.connected_account_id.value}
            & disconnected
        )
        if rule.state not in {SyncRuleState.DEGRADED, SyncRuleState.REMOVING} and not lost_account:
            continue
        incident = next(
            (
                item
                for item in incidents
                if item.rule_id == rule.id.value and item.category != BLOCKED_CATEGORY
            ),
            None,
        )
        if incident is not None:
            problems.append(
                Problem(
                    ProblemKind.STOPPED,
                    rule.id.value,
                    incident.summary,
                    datetime.fromisoformat(incident.opened_at),
                )
            )
        elif lost_account:
            problems.append(
                Problem(ProblemKind.STOPPED, rule.id.value, "A calendar account needs reauthorization")
            )
        else:
            problems.append(Problem(ProblemKind.STOPPED, rule.id.value, "Stopped syncing"))
    return problems


def _incident_problems(
    incidents: Sequence[IncidentSummary], named: set[str | None], now: datetime
) -> tuple[list[Problem], list[Problem]]:
    """Open incidents on rules not already named: those to review, then those still waiting."""
    reviews: list[Problem] = []
    waits: list[Problem] = []
    seen: set[str | None] = set(named)
    for incident in incidents:
        if incident.category == BLOCKED_CATEGORY or (
            incident.rule_id is not None and incident.rule_id in seen
        ):
            continue
        opened = datetime.fromisoformat(incident.opened_at)
        waiting = incident.category in WAITING_CATEGORIES and now - opened <= WAITING_LIMIT
        kind = ProblemKind.WAITING if waiting else ProblemKind.REVIEW
        (waits if waiting else reviews).append(
            Problem(kind, incident.rule_id, incident.summary, opened)
        )
        if incident.rule_id is not None:
            seen.add(incident.rule_id)
    return reviews, waits


def _overdue(
    enabled: Sequence[SyncRuleSummary], named: set[str | None], now: datetime
) -> list[Problem]:
    problems = []
    for summary in enabled:
        succeeded = summary.last_sync.last_succeeded_at if summary.last_sync else None
        if (
            succeeded is None
            or summary.running is not None
            or summary.rule.id.value in named
            or now - succeeded <= OVERDUE_AFTER
        ):
            continue
        problems.append(
            Problem(ProblemKind.OVERDUE, summary.rule.id.value, "Not synced in over a day", succeeded)
        )
    return problems


def _blocked(overview: OperationsOverview) -> Problem:
    count = len(overview.open_blocks)
    rules = {block.rule_id for block in overview.open_blocks}
    return Problem(
        ProblemKind.BLOCKED,
        rules.pop() if len(rules) == 1 else None,
        f"{count} {'event' if count == 1 else 'events'} couldn't be synced",
    )


def _health(
    problems: Sequence[Problem],
    visible: Sequence[SyncRuleSummary],
    enabled: Sequence[SyncRuleSummary],
    overview: OperationsOverview,
    stalled: bool,
) -> InstallationHealth:
    if stalled:
        return InstallationHealth.STALLED
    stopped = any(problem.kind is ProblemKind.STOPPED for problem in problems)
    if not overview.accounts:
        return InstallationHealth.SETUP
    if overview.connected_accounts == 0 and not stopped and overview.open_incidents == 0:
        return InstallationHealth.SETUP
    if problems:
        return _HEALTH_OF[problems[0].kind]
    if not visible:
        return InstallationHealth.SETUP
    if not enabled:
        return InstallationHealth.PAUSED if overview.last_synced_at else InstallationHealth.SETUP
    return InstallationHealth.HEALTHY


@dataclass(slots=True)
class GetInstallationStatus:
    rules: ListSyncRules
    operations: OperationsQueries
    clock: Clock
    scheduler: SchedulerHeartbeat | None

    def execute(self) -> InstallationStatus:
        return assess_installation(
            self.rules.execute(),
            self.operations.overview(),
            self.operations.incidents(),
            self.scheduler.progress() if self.scheduler is not None else None,
            self.clock.now(),
        )
```

Notes for the implementer:
- `_health` orders the two account setup checks after `stalled` and before problems, exactly as
  `overviewHealth` does today, so the Overview keeps its setup screens.
- If Ruff reports a function as too complex (C901, PLR0912), split it further. Do not add a
  `noqa` marker; AGENTS.md treats existing markers as debt.
- `ProviderFailureKind.RATE_LIMIT.value` and `.TEMPORARY.value` must equal `"rate_limit"` and
  `"temporary"`. Check `application/errors.py`; the tests use the literal strings.

- [ ] **Step 5: Run the verdict tests**

Run: `.venv/bin/pytest tests/application/test_status.py tests/application/test_activity.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/calendar_sync/application/activity.py src/calendar_sync/application/status.py src/calendar_sync/infrastructure/persistence/activity_queries.py tests/application/test_status.py tests/adapters/test_activity_queries.py
git commit -m "feat: decide Installation Status on the server"
```

---

### Task 3: Integration Tokens

**Files:**
- Create: `src/calendar_sync/application/integration_tokens.py`
- Modify: `src/calendar_sync/application/ports.py` (after `AdministratorAccess`)
- Modify: `src/calendar_sync/application/errors.py`
- Modify: `src/calendar_sync/infrastructure/security.py` (rename `_token_hash` to `token_hash`)
- Create: `src/calendar_sync/infrastructure/persistence/0018_integration_tokens.sql`
- Modify: `src/calendar_sync/infrastructure/persistence/sqlite.py:65-82`
- Create: `src/calendar_sync/infrastructure/integration_tokens.py`
- Test: `tests/application/test_integration_tokens.py`, `tests/adapters/test_integration_tokens.py`

**Interfaces:**
- Produces:
  - `IntegrationTokenScope(StrEnum)`: `STATUS_READ = "status:read"` (in `ports.py`)
  - `IntegrationTokenSummary(id: str, name: str, scope: IntegrationTokenScope, created_at: datetime, last_used_at: datetime | None, revoked_at: datetime | None)`
  - `IssuedIntegrationToken(summary: IntegrationTokenSummary, token: str)`
  - `IntegrationTokens(Protocol)`: `issue(name: str) -> IssuedIntegrationToken`,
    `list() -> Sequence[IntegrationTokenSummary]`, `revoke(token_id: str) -> bool`,
    `authenticate(token: str) -> IntegrationTokenSummary | None`
  - `calendar_sync.application.integration_tokens`: `TOKEN_PREFIX`, `is_well_formed(token: str) -> bool`, `token_name(raw: str) -> str`
  - `InvalidIntegrationTokenName(ValueError)` in `application/errors.py`
  - `SqliteIntegrationTokens(database_path: Path, clock: Clock, ids: IdGenerator)`
  - `token_hash(token: str) -> str` in `infrastructure/security.py`

Note: the spec named the port method `authorize(token, scope)`. This plan uses
`authenticate(token)` and lets the caller compare the scope, so a valid token without the scope can
answer 403 instead of 401.

- [ ] **Step 1: Write the failing rule tests**

Create `tests/application/test_integration_tokens.py`:

```python
import pytest

from calendar_sync.application.errors import InvalidIntegrationTokenName
from calendar_sync.application.integration_tokens import is_well_formed, token_name

VALID = "cgs_" + "A" * 43


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        (VALID, True),
        ("cgs_" + "a-_9" * 10 + "abc", True),
        ("cgs_" + "A" * 42, False),
        ("cgs_" + "A" * 44, False),
        ("cgx_" + "A" * 43, False),
        ("cgs_" + "A" * 42 + "=", False),
        ("cgs_" + "A" * 42 + "\n", False),
        ("", False),
        ("x" * 10_000, False),
    ],
)
def test_only_the_exact_token_format_is_well_formed(token: str, expected: bool) -> None:
    assert is_well_formed(token) is expected


def test_names_are_trimmed() -> None:
    assert token_name("  Uptime Kuma  ") == "Uptime Kuma"


@pytest.mark.parametrize("name", ["", "   ", "x" * 81, "Kuma\nadmin", "Kuma\x1b[31m"])
def test_names_must_be_short_printable_text(name: str) -> None:
    with pytest.raises(InvalidIntegrationTokenName):
        token_name(name)
```

Run: `.venv/bin/pytest tests/application/test_integration_tokens.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 2: Implement the rules and the port**

`src/calendar_sync/application/errors.py`, add:

```python
class InvalidIntegrationTokenName(ValueError):
    """An Integration Token name must be 1 to 80 printable characters."""
```

Create `src/calendar_sync/application/integration_tokens.py`:

```python
"""What an Integration Token and its name may look like; checked before any lookup."""

from __future__ import annotations

import re
import unicodedata

from calendar_sync.application.errors import InvalidIntegrationTokenName

TOKEN_PREFIX = "cgs_"
# The prefix and 32 random bytes in unpadded URL-safe base64.
_TOKEN = re.compile(r"cgs_[A-Za-z0-9_-]{43}")
NAME_LIMIT = 80


def is_well_formed(token: str) -> bool:
    return _TOKEN.fullmatch(token) is not None


def token_name(raw: str) -> str:
    name = raw.strip()
    if not 1 <= len(name) <= NAME_LIMIT or any(
        unicodedata.category(character).startswith("C") for character in name
    ):
        raise InvalidIntegrationTokenName("name must be 1 to 80 printable characters")
    return name
```

In `src/calendar_sync/application/ports.py`, after `class AdministratorAccess`, add:

```python
class IntegrationTokenScope(StrEnum):
    STATUS_READ = "status:read"


@dataclass(frozen=True, slots=True)
class IntegrationTokenSummary:
    """An Integration Token as the administrator sees it; never the token or its hash."""

    id: str
    name: str
    scope: IntegrationTokenScope
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssuedIntegrationToken:
    summary: IntegrationTokenSummary
    token: str
    """Shown once, when issued; only its hash is kept."""


class IntegrationTokens(Protocol):
    """Named credentials the administrator issues so monitors and agents can read status."""

    def issue(self, name: str) -> IssuedIntegrationToken: ...

    def list(self) -> Sequence[IntegrationTokenSummary]:
        """Every token, newest first, revoked ones last."""
        ...

    def revoke(self, token_id: str) -> bool:
        """Whether a token that was not yet revoked is revoked now."""
        ...

    def authenticate(self, token: str) -> IntegrationTokenSummary | None:
        """The token's summary when it is well formed, known, and not revoked."""
        ...
```

Run: `.venv/bin/pytest tests/application/test_integration_tokens.py -v`
Expected: PASS

- [ ] **Step 3: Write the failing adapter tests**

Create `tests/adapters/test_integration_tokens.py`:

```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from calendar_sync.application.errors import InvalidIntegrationTokenName
from calendar_sync.application.ports import IntegrationTokenScope, IntegrationTokenSummary
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.security import token_hash

ISSUED = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


@dataclass
class MovableClock:
    moment: datetime

    def now(self) -> datetime:
        return self.moment


def _tokens(tmp_path: Path) -> tuple[SqliteIntegrationTokens, MovableClock, Path]:
    database = tmp_path / "test.db"
    initialize_database(database)
    clock = MovableClock(ISSUED)
    return SqliteIntegrationTokens(database, clock, UuidIdGenerator()), clock, database


def test_an_issued_token_authenticates_and_only_its_hash_is_stored(tmp_path: Path) -> None:
    tokens, _, database = _tokens(tmp_path)

    issued = tokens.issue("  Uptime Kuma ")

    assert issued.token.startswith("cgs_")
    assert len(issued.token) == 47
    assert issued.summary.name == "Uptime Kuma"
    assert issued.summary.scope is IntegrationTokenScope.STATUS_READ
    # The first use records itself, so last_used_at is the moment of that use.
    assert tokens.authenticate(issued.token) == IntegrationTokenSummary(
        issued.summary.id, "Uptime Kuma", IntegrationTokenScope.STATUS_READ, ISSUED, ISSUED, None
    )
    with sqlite3.connect(database) as connection:
        stored = connection.execute("SELECT * FROM integration_tokens").fetchall()
    assert issued.token not in repr(stored)
    assert token_hash(issued.token) in repr(stored)


def test_unknown_malformed_and_revoked_tokens_are_refused(tmp_path: Path) -> None:
    tokens, _, _ = _tokens(tmp_path)
    issued = tokens.issue("Claude Code")

    assert tokens.authenticate("cgs_" + "A" * 43) is None
    assert tokens.authenticate(issued.token + "x") is None
    assert tokens.authenticate(issued.token[:-1]) is None
    assert tokens.revoke(issued.summary.id) is True
    assert tokens.revoke(issued.summary.id) is False
    assert tokens.revoke("missing") is False
    assert tokens.authenticate(issued.token) is None


def test_use_is_recorded_at_most_every_five_minutes(tmp_path: Path) -> None:
    tokens, clock, _ = _tokens(tmp_path)
    issued = tokens.issue("Homepage")

    clock.moment = ISSUED + timedelta(minutes=1)
    tokens.authenticate(issued.token)
    clock.moment = ISSUED + timedelta(minutes=4)
    assert tokens.authenticate(issued.token).last_used_at == ISSUED + timedelta(minutes=1)  # type: ignore[union-attr]
    clock.moment = ISSUED + timedelta(minutes=6)
    assert tokens.authenticate(issued.token).last_used_at == ISSUED + timedelta(minutes=6)  # type: ignore[union-attr]


def test_tokens_are_listed_newest_first_with_revoked_ones_last(tmp_path: Path) -> None:
    tokens, clock, _ = _tokens(tmp_path)
    first = tokens.issue("First")
    clock.moment = ISSUED + timedelta(minutes=1)
    second = tokens.issue("Second")
    clock.moment = ISSUED + timedelta(minutes=2)
    third = tokens.issue("Third")
    tokens.revoke(third.summary.id)

    assert [token.name for token in tokens.list()] == ["Second", "First", "Third"]
    assert tokens.list()[2].revoked_at == ISSUED + timedelta(minutes=2)
    assert first.summary.last_used_at is None
    assert second.summary.last_used_at is None


def test_invalid_names_are_refused_before_anything_is_stored(tmp_path: Path) -> None:
    tokens, _, _ = _tokens(tmp_path)
    with pytest.raises(InvalidIntegrationTokenName):
        tokens.issue("Kuma\nadmin")
    assert tokens.list() == []


def test_the_migration_applies_to_an_existing_database(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE integration_tokens")
        connection.execute("DELETE FROM schema_migrations WHERE version = 18")

    initialize_database(database)

    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
        indexes = connection.execute("PRAGMA index_list('integration_tokens')").fetchall()
    assert 18 in versions
    assert any(index[2] == 1 for index in indexes)
```

Run: `.venv/bin/pytest tests/adapters/test_integration_tokens.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'calendar_sync.infrastructure.integration_tokens'`

- [ ] **Step 4: Implement the migration and adapter**

`src/calendar_sync/infrastructure/persistence/0018_integration_tokens.sql`:

```sql
-- Integration Tokens let monitors and agents read Installation Status (ADR 0023).
-- Only a SHA-256 hash of each token is kept; UNIQUE indexes it for lookup.
CREATE TABLE integration_tokens (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
```

In `sqlite.py`, append `(18, "0018_integration_tokens.sql"),` to `_FORWARD_MIGRATIONS`.

In `security.py`, rename `_token_hash` to `token_hash` and update its three callers in the same
file.

Create `src/calendar_sync/infrastructure/integration_tokens.py`:

```python
from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from calendar_sync.application.integration_tokens import TOKEN_PREFIX, is_well_formed, token_name
from calendar_sync.application.ports import (
    Clock,
    IdGenerator,
    IntegrationTokenScope,
    IntegrationTokenSummary,
    IssuedIntegrationToken,
)
from calendar_sync.infrastructure.security import token_hash

USAGE_GRANULARITY = timedelta(minutes=5)
"""A monitor polling every 20 seconds must not write to SQLite on every request."""

_COLUMNS = "id, name, scope, created_at, last_used_at, revoked_at"


class SqliteIntegrationTokens:
    def __init__(self, database_path: Path, clock: Clock, ids: IdGenerator) -> None:
        self._database_path = database_path
        self._clock = clock
        self._ids = ids

    def issue(self, name: str) -> IssuedIntegrationToken:
        cleaned = token_name(name)
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        summary = IntegrationTokenSummary(
            self._ids.new(), cleaned, IntegrationTokenScope.STATUS_READ, self._clock.now(), None, None
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO integration_tokens (id, name, token_hash, scope, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    summary.id,
                    summary.name,
                    token_hash(token),
                    summary.scope.value,
                    summary.created_at.isoformat(),
                ),
            )
        return IssuedIntegrationToken(summary, token)

    def list(self) -> Sequence[IntegrationTokenSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {_COLUMNS} FROM integration_tokens
                ORDER BY revoked_at IS NOT NULL, created_at DESC
                """
            ).fetchall()
        return [_summary(row) for row in rows]

    def revoke(self, token_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE integration_tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (self._clock.now().isoformat(), token_id),
            )
        return cursor.rowcount == 1

    def authenticate(self, token: str) -> IntegrationTokenSummary | None:
        if not is_well_formed(token):
            return None
        now = self._clock.now()
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT {_COLUMNS} FROM integration_tokens
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (token_hash(token),),
            ).fetchone()
            if row is None:
                return None
            summary = _summary(row)
            if summary.last_used_at is None or now - summary.last_used_at >= USAGE_GRANULARITY:
                connection.execute(
                    "UPDATE integration_tokens SET last_used_at = ? WHERE id = ?",
                    (now.isoformat(), summary.id),
                )
                summary = IntegrationTokenSummary(
                    summary.id, summary.name, summary.scope, summary.created_at, now, None
                )
        return summary

    def _connect(self) -> closing[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return _committing(connection)


class _committing(closing[sqlite3.Connection]):
    """Commit on success, roll back on error, and always close: one short transaction."""

    def __exit__(self, *exc_info: object) -> None:
        connection = self.thing
        try:
            if exc_info[0] is None:
                connection.commit()
            else:
                connection.rollback()
        finally:
            connection.close()


def _summary(row: sqlite3.Row) -> IntegrationTokenSummary:
    return IntegrationTokenSummary(
        id=str(row["id"]),
        name=str(row["name"]),
        scope=IntegrationTokenScope(str(row["scope"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        last_used_at=_time(row["last_used_at"]),
        revoked_at=_time(row["revoked_at"]),
    )


def _time(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None
```

If mypy rejects subclassing `closing`, replace `_connect` with a `@contextmanager` generator that
yields the connection and commits, rolls back, and closes in the same way. `SqliteAdminAuth`
uses `with sqlite3.connect(...)`, which commits but never closes; do not copy that.

- [ ] **Step 5: Run the token tests**

Run: `.venv/bin/pytest tests/application/test_integration_tokens.py tests/adapters/test_integration_tokens.py tests/adapters/test_admin_sessions.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/calendar_sync/application/integration_tokens.py src/calendar_sync/application/ports.py src/calendar_sync/application/errors.py src/calendar_sync/infrastructure/security.py src/calendar_sync/infrastructure/integration_tokens.py src/calendar_sync/infrastructure/persistence/0018_integration_tokens.sql src/calendar_sync/infrastructure/persistence/sqlite.py tests/application/test_integration_tokens.py tests/adapters/test_integration_tokens.py
git commit -m "feat: store hashed Integration Tokens"
```

---

### Task 4: Status and token routes

**Files:**
- Modify: `src/calendar_sync/bootstrap/container.py`
- Create: `src/calendar_sync/interfaces/access.py`
- Create: `src/calendar_sync/interfaces/api/status_payload.py`
- Modify: `src/calendar_sync/interfaces/api/schemas.py`
- Modify: `src/calendar_sync/interfaces/api/dependencies.py`
- Create: `src/calendar_sync/interfaces/api/routes/integrations.py`
- Modify: `src/calendar_sync/interfaces/api/routes/activity.py:53-72`
- Modify: `src/calendar_sync/interfaces/api/app.py` (router list and `ApiServices`)
- Test: `tests/adapters/test_status_api.py` (new), `tests/adapters/test_api_authorization.py`,
  `tests/adapters/test_api.py:85-112`

**Interfaces:**
- Consumes: `GetInstallationStatus`, `InstallationStatus`, `ProblemKind` (Task 2);
  `IntegrationTokens`, `IntegrationTokenScope` (Task 3).
- Produces:
  - `Container.integration_tokens: IntegrationTokens`, `Container.get_installation_status: GetInstallationStatus`
  - `calendar_sync.interfaces.access`: `class StatusAccess(Enum)` with `GRANTED`,
    `UNAUTHENTICATED`, `FORBIDDEN`; `status_access(tokens, administrator, authorization: str | None, session: str | None) -> StatusAccess`
  - `calendar_sync.interfaces.api.status_payload.status_response(status: InstallationStatus) -> StatusResponse`
  - `require_status_reader` FastAPI dependency
  - `ProblemResponse(kind: str, rule_id: str | None, summary: str, since: str | None)`
  - `DashboardResponse` gains `status: str`, `needs_attention: bool`, `problems: list[ProblemResponse]` and loses `health`

- [ ] **Step 1: Write the failing API tests**

Create `tests/adapters/test_status_api.py`:

```python
from __future__ import annotations

import logging
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.ports import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Adapters, Container, build_adapters, compose
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.interfaces.api.app import create_app
from tests.helpers import endpoint

PASSWORD = {"password": "correct horse battery staple"}
SECRETS = {
    "account": "acct-secret-7f3a",
    "email": "secret.person@example.test",
    "calendar": "c_secret9b1e@group.calendar.example.test",
    "title": "Secret dentist visit",
}


def _installation(tmp_path: Path) -> tuple[Container, Adapters]:
    settings = Settings(tmp_path / "test.db")
    adapters = build_adapters(settings)
    return replace(compose(settings, adapters), scheduler=None), adapters


def _signed_in(client: TestClient) -> None:
    client.post("/api/v1/setup/admin", json=PASSWORD)


def _issue(client: TestClient, name: str = "Uptime Kuma") -> str:
    response = client.post("/api/v1/integration-tokens", json={"name": name})
    assert response.status_code == 201
    token: str = response.json()["token"]
    return token


def test_tokens_are_managed_only_with_an_administrator_session(tmp_path: Path) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        assert client.get("/api/v1/integration-tokens").status_code == 401
        _signed_in(client)
        token = _issue(client)
        listed = client.get("/api/v1/integration-tokens").json()

        assert listed[0]["name"] == "Uptime Kuma"
        assert "token" not in listed[0]
        assert client.post("/api/v1/integration-tokens", json={"name": "a\nb"}).status_code == 422

        client.cookies.clear()
        bearer = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/integration-tokens", headers=bearer).status_code == 401
        assert client.post(
            "/api/v1/integration-tokens", json={"name": "x"}, headers=bearer
        ).status_code == 401


def test_status_accepts_a_token_or_a_session(tmp_path: Path) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        token = _issue(client)
        by_session = client.get("/api/v1/status")
        client.cookies.clear()
        by_token = client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"})

    assert by_session.status_code == by_token.status_code == 200
    assert by_token.headers["cache-control"] == "no-store"
    body = by_token.json()
    assert body["status"] == "setup"
    assert body["needs_attention"] is False
    assert body["problems"] == []
    assert set(body) >= {"summary", "version", "checked_at", "scheduler", "counts", "rules"}


@pytest.mark.parametrize(
    "header",
    [None, "Bearer cgs_" + "A" * 43, "Bearer not-a-token", "Basic abc", "Bearer "],
)
def test_status_refuses_missing_and_invalid_credentials_alike(
    tmp_path: Path, header: str | None
) -> None:
    container, _ = _installation(tmp_path)
    headers = {"Authorization": header} if header is not None else {}
    with TestClient(create_app(container)) as client:
        response = client.get("/api/v1/status", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "valid credentials required"}


def test_an_invalid_bearer_header_is_refused_beside_a_valid_session(tmp_path: Path) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        response = client.get(
            "/api/v1/status", headers={"Authorization": "Bearer cgs_" + "B" * 43}
        )
    assert response.status_code == 401


def test_a_revoked_token_and_a_token_in_the_query_string_are_refused(tmp_path: Path) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        token = _issue(client)
        token_id = client.get("/api/v1/integration-tokens").json()[0]["id"]
        assert client.delete(f"/api/v1/integration-tokens/{token_id}").status_code == 204
        assert client.delete(f"/api/v1/integration-tokens/{token_id}").status_code == 404
        live = _issue(client, "Homepage")
        client.cookies.clear()

        revoked = client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"})
        in_query = client.get(f"/api/v1/status?token={live}")
        in_access_token = client.get(f"/api/v1/status?access_token={live}")
        in_header = client.get("/api/v1/status", headers={"Authorization": f"Bearer {live}"})

    assert (revoked.status_code, in_query.status_code, in_access_token.status_code) == (401, 401, 401)
    assert in_header.status_code == 200


def test_status_never_contains_identifiers_emails_or_event_content(tmp_path: Path) -> None:
    container, adapters = _installation(tmp_path)
    database = tmp_path / "test.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO connected_accounts (
                id, provider, display_name, email, encrypted_credentials,
                state, created_at, updated_at
            ) VALUES (?, 'google', 'Secret Person', ?, x'00', 'connected', '2026-09-01', '2026-09-01')
            """,
            (SECRETS["account"], SECRETS["email"]),
        )
    seeded = SyncRule(
        id=SyncRuleId("rule-1"),
        source=CalendarEndpoint(ConnectedAccountId(SECRETS["account"]), CalendarId(SECRETS["calendar"])),
        destination=endpoint("work-account", "work-calendar"),
        state=SyncRuleState.DEGRADED,
    )
    with adapters.unit_of_work() as uow:
        uow.rules.add(seeded)
        uow.audit.append(
            AuditEntry(
                occurred_at=datetime(2026, 10, 3, 8, 0, tzinfo=UTC),
                rule_id=seeded.id,
                action=AuditAction.CREATE,
                outcome=AuditOutcome.COMPLETED,
                source_event_id="source-event-1",
                event=RecordedEvent(title=SECRETS["title"]),
            )
        )
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO incidents (
                id, deduplication_key, rule_id, category, state, summary, opened_at, updated_at,
                account_id
            ) VALUES ('incident-1', 'provider:rule-1', 'rule-1', 'authentication', 'open',
                'Calendar provider authorization expired', '2026-10-03T08:00:00+00:00',
                '2026-10-03T08:00:00+00:00', ?)
            """,
            (SECRETS["account"],),
        )
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        token = _issue(client)
        client.cookies.clear()
        response = client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"})

    assert response.json()["status"] == "stopped"
    for value in [*SECRETS.values(), token]:
        assert value not in response.text


def test_the_token_never_reaches_the_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        token = _issue(client)
        client.cookies.clear()
        with caplog.at_level(logging.DEBUG):
            client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"})
            client.get("/api/v1/status", headers={"Authorization": f"Bearer {token[:-1]}x"})
    assert token not in caplog.text
    assert token[:-1] not in caplog.text


def test_the_dashboard_carries_the_server_verdict(tmp_path: Path) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        body: dict[str, Any] = client.get("/api/v1/dashboard").json()
    assert body["status"] == "setup"
    assert body["needs_attention"] is False
    assert body["problems"] == []
    assert "health" not in body
```

If `AuditAction.CREATE` needs fields this entry lacks, copy the `AuditEntry` shape from
`test_activity_and_incidents_require_admin_and_return_operational_data` in `tests/adapters/test_api.py`
and keep `event=RecordedEvent(title=SECRETS["title"])`.

Change `tests/adapters/test_api.py` line 100 onwards: the dashboard assertion replaces
`"health": "healthy"` with `"status": "setup", "needs_attention": False, "problems": []`.

In `tests/adapters/test_api_authorization.py`:

```python
from calendar_sync.interfaces.api.dependencies import require_admin, require_status_reader

# Readable with an administrator session or an Integration Token (ADR 0023).
STATUS_READER_ROUTES = {("GET", "/api/v1/status")}


def _requires(dependant: Dependant, guard: object) -> bool:
    return any(sub.call is guard or _requires(sub, guard) for sub in dependant.dependencies)
```

Replace `_requires_admin(route.dependant)` with `_requires(route.dependant, require_admin)`, and
change the final assertions to:

```python
    readers = {
        (method, route.path)
        for route in api_routes
        if _requires(route.dependant, require_status_reader)
        for method in route.methods or ()
    }
    assert len(api_routes) > len(PUBLIC_API_ROUTES)
    assert unguarded == PUBLIC_API_ROUTES | STATUS_READER_ROUTES
    assert readers == STATUS_READER_ROUTES
```

Add a request-level test to the same file:

```python
def test_an_integration_token_is_refused_by_every_other_api_route(tmp_path: Path) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))
    with TestClient(app) as client:
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})
        token = client.post("/api/v1/integration-tokens", json={"name": "Probe"}).json()["token"]
        client.cookies.clear()
        refused = []
        for route in app.routes:
            if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
                continue
            for method in route.methods or ():
                if (method, route.path) in PUBLIC_API_ROUTES | STATUS_READER_ROUTES:
                    continue
                path = re.sub(r"\{[^}]+\}", "x", route.path)
                response = client.request(
                    method, path, headers={"Authorization": f"Bearer {token}"}, json={}
                )
                refused.append((method, route.path, response.status_code))
    assert refused
    assert {status for _, _, status in refused} == {401}, refused
```

Add `import re` and `from fastapi.testclient import TestClient` to that file.

Run: `.venv/bin/pytest tests/adapters/test_status_api.py tests/adapters/test_api_authorization.py -v`
Expected: FAIL (routes and fields do not exist yet).

- [ ] **Step 2: Compose the new services**

In `bootstrap/container.py`:
- Import `GetInstallationStatus` from `calendar_sync.application.status`, `IntegrationTokens` from
  ports, and `SqliteIntegrationTokens` from `calendar_sync.infrastructure.integration_tokens`.
- Add to `Container`, after `get_dashboard`: `get_installation_status: GetInstallationStatus` and
  `integration_tokens: IntegrationTokens`.
- Add to `Adapters`, after `database_storage`: `integration_tokens: IntegrationTokens`.
- In `build_adapters`, pass `integration_tokens=SqliteIntegrationTokens(settings.database_path, clock, ids)`.
- In `compose`, build `list_sync_rules = ListSyncRules(unit_of_work, locks)` once, use it for the
  existing field, and add:

```python
        get_installation_status=GetInstallationStatus(
            list_sync_rules, adapters.operations, clock, scheduler
        ),
        integration_tokens=adapters.integration_tokens,
```

`scheduler` is `None` when the installation has no master key or Google configuration. With
enabled rules that is `stalled`, which is correct: nothing can synchronize.

- [ ] **Step 3: Implement shared access and the payload**

Create `src/calendar_sync/interfaces/access.py`:

```python
"""Who may read Installation Status: the one decision the status API and MCP share."""

from __future__ import annotations

from enum import Enum

from calendar_sync.application.ports import (
    AdministratorAccess,
    IntegrationTokens,
    IntegrationTokenScope,
)


class StatusAccess(Enum):
    GRANTED = "granted"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"


def status_access(
    tokens: IntegrationTokens,
    administrator: AdministratorAccess,
    authorization: str | None,
    session: str | None,
) -> StatusAccess:
    """A present Authorization header decides alone, so a broken token is never hidden."""
    if authorization is not None:
        scheme, _, credential = authorization.partition(" ")
        summary = tokens.authenticate(credential.strip()) if scheme.lower() == "bearer" else None
        if summary is None:
            return StatusAccess.UNAUTHENTICATED
        if summary.scope is not IntegrationTokenScope.STATUS_READ:
            return StatusAccess.FORBIDDEN
        return StatusAccess.GRANTED
    if session is not None and administrator.session_is_valid(session):
        return StatusAccess.GRANTED
    return StatusAccess.UNAUTHENTICATED
```

Add to `schemas.py`:

```python
class ProblemResponse(BaseModel):
    kind: str
    rule_id: str | None
    summary: str
    since: str | None


class SchedulerResponse(BaseModel):
    running: bool
    last_pass_completed_at: str | None
    current_pass_started_at: str | None


class StatusCountsResponse(BaseModel):
    rules: int
    running: int
    stopped: int
    paused: int
    overdue: int
    open_incidents: int
    blocked_events: int
    disconnected_accounts: int


class StatusCalendarResponse(BaseModel):
    calendar: str
    provider: str | None


class StatusRuleResponse(BaseModel):
    id: str
    name: str
    state: str
    source: StatusCalendarResponse
    destination: StatusCalendarResponse
    projection: str
    last_succeeded_at: str | None
    running: str | None
    problem: ProblemResponse | None


class StatusIncidentResponse(BaseModel):
    rule_id: str | None
    category: str
    summary: str
    opened_at: str


class StatusResponse(BaseModel):
    status: str
    needs_attention: bool
    summary: str
    version: str
    checked_at: str
    last_synced_at: str | None
    scheduler: SchedulerResponse
    counts: StatusCountsResponse
    problems: list[ProblemResponse]
    rules: list[StatusRuleResponse]
    incidents: list[StatusIncidentResponse]


class IntegrationTokenResponse(BaseModel):
    id: str
    name: str
    scope: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


class IssuedIntegrationTokenResponse(IntegrationTokenResponse):
    token: str


class IssueIntegrationTokenRequest(BaseModel):
    name: str = Field(max_length=200)
```

In `DashboardResponse`, replace `health: str` with:

```python
    status: str
    needs_attention: bool
    problems: list[ProblemResponse]
```

and move `class ProblemResponse` above `DashboardResponse`.

Create `src/calendar_sync/interfaces/api/status_payload.py`:

```python
"""Installation Status as the status API and MCP return it: no IDs of accounts or calendars."""

from __future__ import annotations

from calendar_sync import __version__
from calendar_sync.application.status import (
    InstallationStatus,
    Problem,
    ProblemKind,
    RuleStatus,
)
from calendar_sync.domain.model import CalendarEndpoint, SyncRuleState
from calendar_sync.interfaces.api.schemas import (
    ProblemResponse,
    SchedulerResponse,
    StatusCalendarResponse,
    StatusCountsResponse,
    StatusIncidentResponse,
    StatusResponse,
    StatusRuleResponse,
)


def problem_response(problem: Problem) -> ProblemResponse:
    return ProblemResponse(
        kind=problem.kind.value,
        rule_id=problem.rule_id,
        summary=problem.summary,
        since=problem.since.isoformat() if problem.since else None,
    )


def status_response(status: InstallationStatus) -> StatusResponse:
    overview = status.overview
    scheduler = status.scheduler
    states = [rule.summary.rule.state for rule in status.rules]
    return StatusResponse(
        status=status.health.value,
        needs_attention=status.needs_attention,
        summary=status.summary,
        version=__version__,
        checked_at=status.checked_at.isoformat(),
        last_synced_at=overview.last_synced_at,
        scheduler=SchedulerResponse(
            running=scheduler is not None,
            last_pass_completed_at=(
                scheduler.last_completed_at.isoformat()
                if scheduler and scheduler.last_completed_at
                else None
            ),
            current_pass_started_at=(
                scheduler.pass_started_at.isoformat()
                if scheduler and scheduler.pass_started_at
                else None
            ),
        ),
        counts=StatusCountsResponse(
            rules=len(status.rules),
            running=states.count(SyncRuleState.ENABLED),
            stopped=sum(p.kind is ProblemKind.STOPPED for p in status.problems),
            paused=states.count(SyncRuleState.PAUSED),
            overdue=sum(p.kind is ProblemKind.OVERDUE for p in status.problems),
            open_incidents=overview.open_incidents,
            blocked_events=len(overview.open_blocks),
            disconnected_accounts=overview.disconnected_accounts,
        ),
        problems=[problem_response(problem) for problem in status.problems],
        rules=[_rule(status, rule) for rule in status.rules],
        incidents=[
            StatusIncidentResponse(
                rule_id=incident.rule_id,
                category=incident.category,
                summary=incident.summary,
                opened_at=incident.opened_at,
            )
            for incident in status.open_incidents
        ],
    )


def _rule(status: InstallationStatus, rule: RuleStatus) -> StatusRuleResponse:
    summary = rule.summary
    last = summary.last_sync.last_succeeded_at if summary.last_sync else None
    return StatusRuleResponse(
        id=summary.rule.id.value,
        name=rule.name,
        state=summary.rule.state.value,
        source=_calendar(status, rule, summary.rule.source),
        destination=_calendar(status, rule, summary.rule.destination),
        projection=summary.rule.transformation.content.value,
        last_succeeded_at=last.isoformat() if last else None,
        running=summary.running.kind.value if summary.running else None,
        problem=problem_response(rule.problem) if rule.problem else None,
    )


def _calendar(
    status: InstallationStatus, rule: RuleStatus, endpoint: CalendarEndpoint
) -> StatusCalendarResponse:
    return StatusCalendarResponse(
        calendar=rule.summary.names.get(endpoint, "Unnamed calendar"),
        provider=status.providers.get(endpoint.connected_account_id.value),
    )
```

Check `SyncRuleState.PREVIEWED.value` and similar values: `state` returns the stored value
(`"dry_run_validated"`, `"disabled"`), as `/api/v1/rules` already does.

- [ ] **Step 4: Implement the dependency and routes**

In `dependencies.py`, add:

```python
from fastapi import Header

from calendar_sync.application.ports import IntegrationTokens
from calendar_sync.interfaces.access import StatusAccess, status_access


class StatusReaderServices(AdministratorServices, Protocol):
    @property
    def integration_tokens(self) -> IntegrationTokens: ...


UNAUTHENTICATED = HTTPException(
    status.HTTP_401_UNAUTHORIZED,
    "valid credentials required",
    headers={"WWW-Authenticate": "Bearer"},
)


def require_status_reader(
    services: Annotated[StatusReaderServices, Depends(app_services)],
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    access = status_access(
        services.integration_tokens, services.administrator, authorization, session
    )
    if access is StatusAccess.FORBIDDEN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "token lacks the required scope")
    if access is not StatusAccess.GRANTED:
        raise UNAUTHENTICATED
```

Create `src/calendar_sync/interfaces/api/routes/integrations.py`:

```python
from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Response, status

from calendar_sync.application.errors import InvalidIntegrationTokenName
from calendar_sync.application.ports import IntegrationTokens, IntegrationTokenSummary
from calendar_sync.application.status import GetInstallationStatus
from calendar_sync.interfaces.api.dependencies import (
    app_services,
    require_admin,
    require_status_reader,
)
from calendar_sync.interfaces.api.schemas import (
    IntegrationTokenResponse,
    IssuedIntegrationTokenResponse,
    IssueIntegrationTokenRequest,
    StatusResponse,
)
from calendar_sync.interfaces.api.status_payload import status_response


class IntegrationServices(Protocol):
    @property
    def integration_tokens(self) -> IntegrationTokens: ...
    @property
    def get_installation_status(self) -> GetInstallationStatus: ...


Services = Annotated[IntegrationServices, Depends(app_services)]
ADMIN = [Depends(require_admin)]
router = APIRouter()


@router.get(
    "/api/v1/status",
    response_model=StatusResponse,
    dependencies=[Depends(require_status_reader)],
)
def installation_status(services: Services, response: Response) -> StatusResponse:
    response.headers["Cache-Control"] = "no-store"
    return status_response(services.get_installation_status.execute())


@router.get(
    "/api/v1/integration-tokens",
    response_model=list[IntegrationTokenResponse],
    dependencies=ADMIN,
)
def list_integration_tokens(services: Services) -> list[IntegrationTokenResponse]:
    return [_token(summary) for summary in services.integration_tokens.list()]


@router.post(
    "/api/v1/integration-tokens",
    response_model=IssuedIntegrationTokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN,
)
def issue_integration_token(
    payload: IssueIntegrationTokenRequest, services: Services
) -> IssuedIntegrationTokenResponse:
    try:
        issued = services.integration_tokens.issue(payload.name)
    except InvalidIntegrationTokenName as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return IssuedIntegrationTokenResponse(
        **_token(issued.summary).model_dump(), token=issued.token
    )


@router.delete(
    "/api/v1/integration-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=ADMIN,
)
def revoke_integration_token(token_id: str, services: Services) -> None:
    if not services.integration_tokens.revoke(token_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "integration token not found")


def _token(summary: IntegrationTokenSummary) -> IntegrationTokenResponse:
    return IntegrationTokenResponse(
        id=summary.id,
        name=summary.name,
        scope=summary.scope.value,
        created_at=summary.created_at.isoformat(),
        last_used_at=summary.last_used_at.isoformat() if summary.last_used_at else None,
        revoked_at=summary.revoked_at.isoformat() if summary.revoked_at else None,
    )
```

In `routes/activity.py`, add `get_installation_status` to `ActivityServices` and change the
dashboard route body:

```python
    summary = services.get_dashboard.execute()
    verdict = services.get_installation_status.execute()
    return DashboardResponse(
        status=verdict.health.value,
        needs_attention=verdict.needs_attention,
        problems=[problem_response(problem) for problem in verdict.problems],
        connected_accounts=summary.connected_accounts,
        # ... every other existing field unchanged
    )
```

Import `problem_response` from `calendar_sync.interfaces.api.status_payload`.

In `app.py`, import `integrations`, add `integrations.IntegrationServices` to `ApiServices`, and
add `integrations` to the tuple of modules whose routes are extended.

- [ ] **Step 5: Run the API tests**

Run: `.venv/bin/pytest tests/adapters/test_status_api.py tests/adapters/test_api_authorization.py tests/adapters/test_api.py -v`
Expected: PASS. If a route answers 422 or 405 instead of 401 in the request-level authorization
test, it does not run `require_admin` before validation; fix the route, never the test.

- [ ] **Step 6: Commit**

```bash
git add src/calendar_sync/bootstrap/container.py src/calendar_sync/interfaces tests/adapters/test_status_api.py tests/adapters/test_api_authorization.py tests/adapters/test_api.py
git commit -m "feat: serve Installation Status to Integration Tokens"
```

---

### Task 5: MCP server at `/mcp`

**Files:**
- Modify: `pyproject.toml` (dependencies; import-linter contracts)
- Create: `src/calendar_sync/interfaces/mcp/__init__.py`, `src/calendar_sync/interfaces/mcp/server.py`
- Modify: `src/calendar_sync/interfaces/api/app.py` (`create_app`, `lifespan`)
- Test: `tests/adapters/test_mcp.py`

**Interfaces:**
- Consumes: `status_access` (Task 4), `status_response` (Task 4), `GetInstallationStatus`,
  `GetSyncRuleDetails`, `rule_name`.
- Produces: `calendar_sync.interfaces.mcp.server.McpEndpoint` with `app` (the gated route
  endpoint) and `running()` (an async context manager for the app lifespan);
  `build_mcp(services: McpServices) -> McpEndpoint`; `McpNotFound`.

- [ ] **Step 1: Add the dependency and contracts**

In `pyproject.toml` `dependencies`, add `"mcp>=2.3,<3",`. Add `"mcp"` to the `forbidden_modules`
of the contract "Domain and application stay free of frameworks, providers, and storage", and add:

```toml
[[tool.importlinter.contracts]]
name = "The MCP SDK stays in the MCP interface"
type = "protected"
protected_modules = ["mcp"]
allowed_importers = ["calendar_sync.interfaces.mcp"]
```

Run: `.venv/bin/pip install -e '.[dev]' && .venv/bin/lint-imports`
Expected: PASS (nothing imports `mcp` yet).

- [ ] **Step 2: Write the failing MCP tests**

Create `tests/adapters/test_mcp.py`:

```python
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.interfaces.api.app import create_app
from tests.helpers import rule

PASSWORD = {"password": "correct horse battery staple"}
PROTOCOL = "2025-06-18"
JSON_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": PROTOCOL,
}


@pytest.fixture
def mcp(tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    """A signed-in client on a LAN host name, with one rule and one Integration Token."""
    database = tmp_path / "test.db"
    settings = Settings(database)
    adapters = build_adapters(settings)
    container = replace(compose(settings, adapters), scheduler=None)
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO connected_accounts (
                id, provider, display_name, email, encrypted_credentials,
                state, created_at, updated_at
            ) VALUES (?, 'google', ?, ?, x'00', 'connected', '2026-09-01', '2026-09-01')
            """,
            [(account, account, f"{account}@example.test") for account in ("personal-account", "work-account")],
        )
    with adapters.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    with TestClient(create_app(container), base_url="http://ghost.lan:8000") as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        token: str = client.post("/api/v1/integration-tokens", json={"name": "Agent"}).json()["token"]
        yield client, token


def _rpc(client: TestClient, token: str | None, method: str, params: dict[str, Any] | None = None) -> Any:
    headers = dict(JSON_HEADERS)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", headers=headers, json=body)


def test_tools_are_listed_and_read_only(mcp: Any) -> None:
    client, token = mcp
    client.cookies.clear()
    response = _rpc(client, token, "tools/list")
    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    assert set(tools) == {"get_status", "get_rule"}
    assert all(tool["annotations"]["readOnlyHint"] is True for tool in tools.values())


def test_initialize_names_the_server_and_explains_the_statuses(mcp: Any) -> None:
    client, token = mcp
    result = _rpc(
        client,
        token,
        "initialize",
        {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    ).json()["result"]
    assert result["serverInfo"]["name"] == "calendar-ghost"
    assert "needs_attention" in result["instructions"]
    assert "read-only" in result["instructions"]


def test_get_status_matches_the_status_api(mcp: Any) -> None:
    client, token = mcp
    called = _rpc(client, token, "tools/call", {"name": "get_status", "arguments": {}}).json()
    api = client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"}).json()
    structured = called["result"]["structuredContent"]
    assert structured["status"] == api["status"]
    assert structured["rules"] == api["rules"]


@pytest.mark.parametrize("reference", ["rule-1", "Unnamed calendar → Unnamed calendar"])
def test_get_rule_finds_a_rule_by_id_or_name(mcp: Any, reference: str) -> None:
    client, token = mcp
    called = _rpc(
        client, token, "tools/call", {"name": "get_rule", "arguments": {"rule": reference}}
    ).json()
    structured = called["result"]["structuredContent"]
    assert structured["rule"]["id"] == "rule-1"
    assert "last_sync" in structured


def test_get_rule_reports_an_unknown_rule_without_listing_names(mcp: Any) -> None:
    client, token = mcp
    called = _rpc(
        client, token, "tools/call", {"name": "get_rule", "arguments": {"rule": "Nope"}}
    ).json()
    assert called["result"]["isError"] is True
    text = called["result"]["content"][0]["text"]
    assert "get_status" in text
    assert "Unnamed calendar" not in text


def test_mcp_refuses_missing_revoked_and_cookie_only_credentials(mcp: Any) -> None:
    client, token = mcp
    assert _rpc(client, None, "tools/list").status_code == 401
    assert _rpc(client, "cgs_" + "A" * 43, "tools/list").status_code == 401
    unauthorized = _rpc(client, None, "tools/list")
    assert unauthorized.headers["www-authenticate"] == "Bearer"
    token_id = client.get("/api/v1/integration-tokens").json()[0]["id"]
    client.delete(f"/api/v1/integration-tokens/{token_id}")
    assert _rpc(client, token, "tools/list").status_code == 401


@pytest.mark.parametrize("method", ["GET", "DELETE", "PUT"])
def test_only_post_is_served_so_no_stream_stays_open(mcp: Any, method: str) -> None:
    client, token = mcp
    response = client.request(method, "/mcp", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


def test_paths_below_mcp_are_not_found_and_the_web_ui_is_unaffected(mcp: Any) -> None:
    client, token = mcp
    below = client.post("/mcp/", headers={"Authorization": f"Bearer {token}"}, json={})
    assert below.status_code == 404
    assert client.post("/mcp/extra", json={}).status_code == 404
    assert client.get("/rules").status_code in {200, 404}
    assert "mcp" not in client.get("/api/openapi.json").text
```

The `get_status` test sends a token through the `Host: ghost.lan:8000` base URL, which pins Review
Focus item 5. The last assertion accepts 404 for `/rules` because the static Web UI is absent in
some development checkouts.

Run: `.venv/bin/pytest tests/adapters/test_mcp.py -v`
Expected: FAIL (`/mcp` serves the Web UI fallback or 405).

- [ ] **Step 3: Implement the MCP package**

`src/calendar_sync/interfaces/mcp/__init__.py`:

```python
"""The Model Context Protocol interface: Installation Status for AI agents (ADR 0023)."""
```

`src/calendar_sync/interfaces/mcp/server.py`:

```python
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from calendar_sync import __version__
from calendar_sync.application.errors import RuleNotFound
from calendar_sync.application.ports import AdministratorAccess, IntegrationTokens, RuleRunOutcome
from calendar_sync.application.rules import GetSyncRuleDetails
from calendar_sync.application.status import GetInstallationStatus
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.interfaces.access import StatusAccess, status_access
from calendar_sync.interfaces.api.status_payload import status_response

INSTRUCTIONS = """\
Calendar Ghost synchronizes calendars one way, from a source calendar to a destination calendar,
following Directional Sync Rules. This server is read-only: it reports health and never changes
rules or calendars.

Call get_status first. Its `status` is one of:
- stalled: scheduled synchronization stopped running. The administrator restarts the service.
- stopped: a rule writes nothing until the administrator acts, usually by reauthorizing a
  calendar account in Settings.
- review: something needs a look: an incident, blocked events in Activity, or a rule not synced
  in over a day.
- waiting: the calendar provider is limiting or failing requests; rules retry by themselves.
- paused, setup, healthy: nothing needs attention.
`needs_attention` is true only for stalled, stopped, and review. `problems` lists each problem,
most urgent first. Call get_rule with a rule id or its "Source → Destination" name for its last
run. Events already synced stay where they are while a rule is stopped.
"""
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)


class McpServices(Protocol):
    @property
    def administrator(self) -> AdministratorAccess: ...
    @property
    def integration_tokens(self) -> IntegrationTokens: ...
    @property
    def get_installation_status(self) -> GetInstallationStatus: ...
    @property
    def get_sync_rule_details(self) -> GetSyncRuleDetails: ...


class McpEndpoint:
    """The `/mcp` route. Each application lifespan runs a fresh SDK server, because a session
    manager runs only once and tests start the same app more than once."""

    def __init__(self, services: McpServices) -> None:
        self.app = McpGate(self, services)
        self._services = services
        self.inner: ASGIApp | None = None

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        inner, session_manager = _sdk_app(self._services)
        async with session_manager.run():
            self.inner = inner
            try:
                yield
            finally:
                self.inner = None


def build_mcp(services: McpServices) -> McpEndpoint:
    return McpEndpoint(services)


def _sdk_app(services: McpServices) -> tuple[ASGIApp, StreamableHTTPSessionManager]:
    server = MCPServer(name="calendar-ghost", instructions=INSTRUCTIONS, version=__version__)

    @server.tool(annotations=READ_ONLY)
    def get_status() -> dict[str, Any]:
        """Installation Status: the verdict, each problem, and every rule's state."""
        return status_response(services.get_installation_status.execute()).model_dump(mode="json")

    @server.tool(annotations=READ_ONLY)
    def get_rule(rule: str) -> dict[str, Any]:
        """One rule by id or "Source → Destination" name, with its last runs and problem."""
        status = status_response(services.get_installation_status.execute())
        matches = [item for item in status.rules if rule in {item.id, item.name}]
        if len(matches) != 1:
            reason = "matches more than one rule" if matches else "matches no rule"
            raise ToolError(f"'{rule}' {reason}. Call get_status to see each rule's id.")
        found = matches[0]
        try:
            details = services.get_sync_rule_details.execute(SyncRuleId(found.id))
        except RuleNotFound as error:
            raise ToolError("That rule was removed. Call get_status again.") from error
        return {
            "rule": found.model_dump(mode="json"),
            "last_sync": _outcome(details.last_sync),
            "last_reconciliation": _outcome(details.last_reconciliation),
        }

    # Stateless JSON: no per-client session to keep in the single process. The Host allowlist is
    # off because every request carries a bearer token a rebinding page cannot supply (ADR 0023).
    sdk = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    endpoint: ASGIApp = sdk.routes[0].endpoint  # type: ignore[attr-defined]
    return endpoint, server.session_manager


def _outcome(outcome: RuleRunOutcome | None) -> dict[str, Any] | None:
    if outcome is None:
        return None
    return {
        "completed_at": outcome.completed_at.isoformat(),
        "succeeded": outcome.succeeded,
        "full_run": outcome.full_run,
        "created": outcome.created,
        "updated": outcome.updated,
        "deleted": outcome.deleted,
        "conflicts": outcome.conflicts,
        "drift": outcome.drift,
        "failure_kind": outcome.failure_kind,
    }


class McpGate:
    """Refuses before the SDK sees a request: bearer tokens only, and POST only."""

    def __init__(self, endpoint: McpEndpoint, services: McpServices) -> None:
        self._endpoint = endpoint
        self._services = services

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope["headers"]}
        access = await run_in_threadpool(
            status_access,
            self._services.integration_tokens,
            self._services.administrator,
            headers.get("authorization"),
            None,
        )
        if access is StatusAccess.UNAUTHENTICATED:
            await _json(send, 401, {"detail": "valid credentials required"}, [(b"www-authenticate", b"Bearer")])
            return
        if access is StatusAccess.FORBIDDEN:
            await _json(send, 403, {"detail": "token lacks the required scope"})
            return
        # Stateless mode has no stream to resume, and a GET would hold one open.
        if scope["method"] != "POST":
            await _json(send, 405, {"detail": "method not allowed"}, [(b"allow", b"POST")])
            return
        inner = self._endpoint.inner
        if inner is None:
            await _json(send, 503, {"detail": "the MCP server is starting or stopping"})
            return
        await inner(scope, receive, send)


class McpNotFound:
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await _json(send, 404, {"detail": "not found"})


async def _json(
    send: Send, status: int, body: dict[str, str], headers: list[tuple[bytes, bytes]] | None = None
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), *(headers or [])],
        }
    )
    await send({"type": "http.response.body", "body": json.dumps(body).encode()})
```

`GetSyncRuleDetails.execute` raises `RuleNotFound` for a missing rule (`application/rules.py:227`).
Verified against `mcp` 2.3.0 while planning: a `ToolError` returns HTTP 200 with
`result.isError: true` and the text `Error executing tool get_rule: <message>`, and a fresh
`MCPServer` per lifespan lets one app start twice.

- [ ] **Step 4: Mount it in `create_app`**

In `app.py`:

```python
from calendar_sync.interfaces.mcp.server import McpNotFound, McpServices, build_mcp
```

Add `McpServices` to the `ApiServices` bases. In `create_app`, build the endpoint before
`lifespan` is defined and run it inside the lifespan:

```python
    resolved = container or service_container()
    services: ApiServices = resolved
    mcp = build_mcp(services)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        scheduler_task: asyncio.Task[None] | None = None
        if resolved.scheduler is not None:
            scheduler_task = asyncio.create_task(resolved.scheduler.run_forever())
        try:
            async with mcp.running():
                yield
        finally:
            ...  # unchanged scheduler cancellation
```

After the API routes are extended and before the `/api` fallback routes, register:

```python
    # One exact route, ahead of the API fallback and the Web UI catch-all (ADR 0023).
    app.router.routes.append(Route("/mcp", mcp.app, include_in_schema=False))
    app.router.routes.append(Route("/mcp/{path:path}", McpNotFound(), include_in_schema=False))
```

Remove the later duplicate `services: ApiServices = resolved` line.

- [ ] **Step 5: Run the MCP and API tests**

Run: `.venv/bin/pytest tests/adapters/test_mcp.py tests/adapters/test_status_api.py tests/adapters/test_api_authorization.py -v && .venv/bin/lint-imports && .venv/bin/mypy`
Expected: PASS. If `TestClient` hangs, a non-POST request reached the SDK; check the gate order.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/calendar_sync/interfaces/mcp src/calendar_sync/interfaces/api/app.py tests/adapters/test_mcp.py
git commit -m "feat: serve Installation Status to AI agents over MCP"
```

---

### Task 6: The Overview renders the server verdict

**Files:**
- Modify: `web/src/lib/api.ts:33-46`
- Modify: `web/src/lib/overview-health.ts`
- Modify: `web/src/features/overview.tsx:86-140`
- Test: `web/src/lib/overview-health.test.ts`

**Interfaces:**
- Consumes: `/api/v1/dashboard` fields `status`, `needs_attention`, `problems` (Task 4).
- Produces:
  - `export type InstallationHealth = "stalled" | "stopped" | "review" | "waiting" | "paused" | "setup" | "healthy"`
  - `export type ServerProblem = { kind: "stalled" | "stopped" | "review" | "overdue" | "blocked" | "waiting"; rule_id: string | null; summary: string; since: string | null }`
  - `overviewHealth(dashboard: Dashboard, now?: number, ruleName?: (ruleId: string) => string | null): OverviewHealth`

- [ ] **Step 1: Update the types**

In `api.ts`, replace `health: "healthy" | "attention"` in `Dashboard` with:

```ts
  /** The server's verdict; the Overview never derives its own (ADR 0023). */
  status: InstallationHealth
  needs_attention: boolean
  /** Every current problem, most urgent first. */
  problems: ServerProblem[]
```

and add above `Dashboard`:

```ts
export type InstallationHealth = "stalled" | "stopped" | "review" | "waiting" | "paused" | "setup" | "healthy"
export type ServerProblem = {
  kind: "stalled" | "stopped" | "review" | "overdue" | "blocked" | "waiting"
  rule_id: string | null
  summary: string
  since: string | null
}
```

- [ ] **Step 2: Rewrite the tests to drive the Overview from server problems**

In `overview-health.test.ts`:
- `healthy` gains `status: "healthy", needs_attention: false, problems: []` and loses `health`.
- Add a helper:

```ts
const names: Record<string, string> = {
  "rule-7": "Family → Work",
  "rule-8": "Work → Family",
  "rule-9": "Work → Family",
}
const ruleName = (ruleId: string) => names[ruleId] ?? null
const problem = (
  kind: ServerProblem["kind"],
  rule_id: string | null,
  summary: string,
  since: string | null = "2026-09-28T11:00:00Z",
): ServerProblem => ({ kind, rule_id, summary, since })
```

- Convert each test that passed a `RuleProblem[]` third argument into a dashboard with
  `problems` and a matching `status`, and pass `ruleName` as the third argument. For example,
  "names the running rule an incident is about" becomes:

```ts
  it("names the running rule an incident is about", () => {
    const health = overviewHealth(
      {
        ...healthy,
        status: "review",
        open_incidents: 2,
        problems: [
          problem("review", "rule-7", "Rule Removal stopped"),
          problem("review", "rule-8", "Rule Removal stopped", "2026-09-28T10:00:00Z"),
        ],
      },
      now,
      ruleName,
    )
    expect(health.tone).toBe("review")
    expect(health.headline).toBe("A rule needs a look")
    expect(health.title).toBe("Family → Work")
    expect(health.detail).toBe("Rule Removal stopped. First seen 1 hour ago. 1 other problem also needs a look.")
    expect(health.action).toEqual({ label: "Review this rule", view: "rules", ruleId: "rule-7" })
  })
```

  Convert "only informs while Google limits requests", "leads with the most urgent problem",
  "puts a stopped rule ahead of problems", "says rules stopped when an account needs
  reauthorization", and "flags stopped rules even without naming one" the same way. Keep every
  expected headline, title, detail, and action string except where noted below.
- In "puts a stopped rule ahead of problems on running ones", the stopped problem has no incident,
  so it is `problem("stopped", "rule-7", "Stopped syncing", null)` and the expected detail becomes
  `"Stopped syncing. It writes nothing until it is fixed. Events already synced stay where they are."`.
- "flags stopped rules even without naming one" uses `problem("stopped", "rule-gone", "Stopped syncing", null)`
  with `ruleName` returning null for it; the title stays `""` and the action stays
  `{ label: "Review rules", view: "rules" }`.
- Delete the whole `describe("withoutRunningRemovals", ...)` block: the server excludes running
  removals (Task 2 pins it).
- Add:

```ts
  it("says synchronization stopped running when the scheduler stalls", () => {
    const health = overviewHealth(
      { ...healthy, status: "stalled", needs_attention: true, problems: [problem("stalled", null, "Scheduled synchronization stopped running", null)] },
      now,
      ruleName,
    )
    expect(health.tone).toBe("stopped")
    expect(health.headline).toBe("Synchronization stopped running")
    expect(health.detail).toBe(
      "Calendar Ghost has not checked your calendars recently. Restart the service to resume. Events already synced stay where they are.",
    )
    expect(health.action).toBeNull()
  })

  it("asks for a look at a rule that has not synced in over a day", () => {
    const health = overviewHealth(
      { ...healthy, status: "review", problems: [problem("overdue", "rule-7", "Not synced in over a day", "2026-09-27T10:00:00Z")] },
      now,
      ruleName,
    )
    expect(health.tone).toBe("review")
    expect(health.title).toBe("Family → Work")
    expect(health.detail).toBe("Not synced in over a day. Last sync 1 day ago.")
  })

  it("takes its tone from the server", () => {
    for (const status of ["stopped", "review", "waiting", "paused", "setup", "healthy"] as const) {
      expect(overviewHealth({ ...healthy, status }, now, ruleName).tone).toBe(status)
    }
    expect(overviewHealth({ ...healthy, status: "stalled" }, now, ruleName).tone).toBe("stopped")
  })
```

Confirm `relativeTime("2026-09-27T10:00:00Z", now)` returns "1 day ago" in
`web/src/lib/relative-time.ts`; adjust the expected string to what it returns.

Run: `npm --prefix web run test -- overview-health`
Expected: FAIL

- [ ] **Step 3: Implement**

In `overview-health.ts`:
- Remove `withoutRunningRemovals`.
- Change `RuleProblem` to keep its shape; it is now built from server problems:

```ts
const TONE_OF: Record<InstallationHealth, OverviewTone> = {
  stalled: "stopped",
  stopped: "stopped",
  review: "review",
  waiting: "waiting",
  paused: "paused",
  setup: "setup",
  healthy: "healthy",
}

// Incident summaries are written with or without a closing period.
function sentence(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`
}

/** The server's per-rule problems in the Overview's words. */
export function ruleProblemsOf(
  problems: ServerProblem[],
  ruleName: (ruleId: string) => string | null,
  now: number,
): RuleProblem[] {
  return problems.flatMap((problem): RuleProblem[] => {
    if (problem.rule_id === null || problem.kind === "blocked" || problem.kind === "stalled") return []
    const name = ruleName(problem.rule_id) ?? ""
    const since = problem.since
      ? problem.kind === "overdue"
        ? ` Last sync ${relativeTime(problem.since, now)}.`
        : ` First seen ${relativeTime(problem.since, now)}.`
      : ""
    const kind = problem.kind === "overdue" ? "review" : problem.kind
    return [{ ruleId: problem.rule_id, name, detail: `${sentence(problem.summary)}${since}`, kind }]
  })
}
```

- In `problemsOf(dashboard, ruleProblems)`:
  - Add first, before the stopped section:

```ts
  if (dashboard.problems.some((problem) => problem.kind === "stalled")) {
    problems.push({
      tone: "stopped",
      headline: "Synchronization stopped running",
      title: "",
      detail:
        "Calendar Ghost has not checked your calendars recently. Restart the service to resume. Events already synced stay where they are.",
      action: null,
      summary: "Synchronization stopped running",
    })
  }
```

  - Count stopped rules from the problems, not `dashboard.stopped_rules`:
    `const stoppedCount = of("stopped").length` and use it in `stoppedHeadline` and in both
    stopped conditions. The "named" branch becomes `stoppedCount === 1 && stopped[0].name ? stopped[0] : null`.
- `overviewHealth(dashboard, now = Date.now(), ruleName = () => null)` builds
  `ruleProblemsOf(dashboard.problems, ruleName, now)` and passes it to `problemsOf`. Every return
  value sets `tone: TONE_OF[dashboard.status]` instead of its computed tone, so the server decides.
- Keep `OverviewTone`, the setup branches, `overviewRules`, and every existing copy string.

In `overview.tsx`:
- Delete `ruleProblems`, `WAITING_CATEGORIES`, `sentence`, the `incidents` query, and the
  `withoutRunningRemovals` import.
- Build health with:

```ts
  const ruleNames = new Map(rules.data.map((rule) => [rule.id, ruleName(endpoints(rule))]))
  const health = overviewHealth(dashboard.data, now, (ruleId) => ruleNames.get(ruleId) ?? null)
```

- Keep `useRemovingRuleIds` for `overviewRules` ordering.

- [ ] **Step 4: Run the frontend gate for this change**

Run: `npm --prefix web run typecheck && npm --prefix web run lint && npm --prefix web run test`
Expected: PASS. Fix every other test fixture that builds a `Dashboard` (search
`grep -rn "blocked_rule_id" web/src`) by replacing `health` with `status`, `needs_attention`,
and `problems`.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat: the Overview renders the server's Installation Status"
```

---

### Task 7: Settings → Integrations

**Files:**
- Modify: `web/src/lib/api.ts`
- Create: `web/src/lib/integrations.ts`, `web/src/lib/integrations.test.ts`
- Modify: `web/src/features/settings.tsx` (new `IntegrationsSection` before `<StorageSection />` at line 696)

**Interfaces:**
- Consumes: `GET/POST /api/v1/integration-tokens`, `DELETE /api/v1/integration-tokens/{id}` (Task 4).
- Produces: `integrationExamples(origin: string): IntegrationExample[]`, `isPlainHttp(origin: string): boolean`, `tokenUsage(token: IntegrationToken, now: number): string`.

- [ ] **Step 1: Write the failing helper tests**

`web/src/lib/integrations.test.ts`:

```ts
import { describe, expect, it } from "vitest"

import type { IntegrationToken } from "@/lib/api"
import { integrationExamples, isPlainHttp, tokenUsage } from "@/lib/integrations"

const now = Date.parse("2026-10-03T12:00:00Z")
const token: IntegrationToken = {
  id: "t1",
  name: "Uptime Kuma",
  scope: "status:read",
  created_at: "2026-10-01T09:00:00Z",
  last_used_at: "2026-10-03T11:57:00Z",
  revoked_at: null,
}

describe("integrationExamples", () => {
  it("fills each example with this installation's address and reads the token from the environment", () => {
    const examples = integrationExamples("https://ghost.example.lan")
    expect(examples.map((example) => example.title)).toEqual(["Uptime Kuma", "Homepage", "Claude Code", "Codex"])
    const text = examples.map((example) => example.code).join("\n")
    expect(text).toContain("https://ghost.example.lan/api/v1/status")
    expect(text).toContain("https://ghost.example.lan/mcp")
    expect(text).toContain("$.needs_attention")
    expect(text).toContain("${CALENDAR_GHOST_TOKEN}")
    expect(text).toContain('bearer_token_env_var = "CALENDAR_GHOST_TOKEN"')
    expect(text).not.toContain("cgs_")
  })
})

describe("isPlainHttp", () => {
  it("warns only for plain HTTP", () => {
    expect(isPlainHttp("http://ghost.lan:8000")).toBe(true)
    expect(isPlainHttp("https://ghost.example.lan")).toBe(false)
  })
})

describe("tokenUsage", () => {
  it("says when a token was last used, never used, or revoked", () => {
    expect(tokenUsage(token, now)).toBe("Last used 3 minutes ago")
    expect(tokenUsage({ ...token, last_used_at: null }, now)).toBe("Never used")
    expect(tokenUsage({ ...token, revoked_at: "2026-10-02T12:00:00Z" }, now)).toBe("Revoked 1 day ago")
  })
})
```

Run: `npm --prefix web run test -- integrations`
Expected: FAIL

- [ ] **Step 2: Implement the API calls and helpers**

In `api.ts` add:

```ts
export type IntegrationToken = {
  id: string
  name: string
  scope: "status:read"
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}
export type IssuedIntegrationToken = IntegrationToken & { token: string }
```

and in `api`:

```ts
  integrationTokens: () => request<IntegrationToken[]>("/api/v1/integration-tokens"),
  issueIntegrationToken: (name: string) =>
    request<IssuedIntegrationToken>("/api/v1/integration-tokens", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  revokeIntegrationToken: (id: string) =>
    request<void>(`/api/v1/integration-tokens/${encodeURIComponent(id)}`, { method: "DELETE" }),
```

`web/src/lib/integrations.ts`:

```ts
import type { IntegrationToken } from "@/lib/api"
import { relativeTime } from "@/lib/relative-time"

export type IntegrationExample = { title: string; description: string; code: string }

export function isPlainHttp(origin: string): boolean {
  return origin.startsWith("http://")
}

export function integrationExamples(origin: string): IntegrationExample[] {
  const status = `${origin}/api/v1/status`
  const mcp = `${origin}/mcp`
  return [
    {
      title: "Uptime Kuma",
      description: "Add an HTTP(s) - Json Query monitor. Alert when the result is not false.",
      code: `URL: ${status}\nHeaders: {"Authorization": "Bearer <token>"}\nJson Query: $.needs_attention\nExpected Value: false`,
    },
    {
      title: "Homepage",
      description: "Add a customapi widget to the Calendar Ghost service.",
      code: `widget:\n  type: customapi\n  url: ${status}\n  headers:\n    Authorization: Bearer {{HOMEPAGE_VAR_CALENDAR_GHOST_TOKEN}}\n  mappings:\n    - field: status\n      label: Status\n    - field: summary\n      label: Summary`,
    },
    {
      title: "Claude Code",
      description: "Keep the token in an environment variable, then add the server.",
      code: `claude mcp add --transport http calendar-ghost ${mcp} \\\n  --header "Authorization: Bearer \${CALENDAR_GHOST_TOKEN}"`,
    },
    {
      title: "Codex",
      description: "Add this to ~/.codex/config.toml and set CALENDAR_GHOST_TOKEN.",
      code: `[mcp_servers.calendar-ghost]\nurl = "${mcp}"\nbearer_token_env_var = "CALENDAR_GHOST_TOKEN"`,
    },
  ]
}

export function tokenUsage(token: IntegrationToken, now: number): string {
  if (token.revoked_at) return `Revoked ${relativeTime(token.revoked_at, now)}`
  if (!token.last_used_at) return "Never used"
  return `Last used ${relativeTime(token.last_used_at, now)}`
}
```

The Uptime Kuma example uses `<token>` because Kuma stores headers in its own database; it has no
environment variables. Check Homepage's documented variable syntax
(`{{HOMEPAGE_VAR_NAME}}`) against its docs before committing, and adjust the test if it differs.

Run: `npm --prefix web run test -- integrations`
Expected: PASS

- [ ] **Step 3: Add the Settings section**

In `settings.tsx`, add `<IntegrationsSection />` directly above `<StorageSection />`, and add the
component below `StorageSection`, following its structure (`settings-section`,
`section-heading`, `settings-list`, `setting-row`, `DestructiveConfirmation`, `inline-error`,
`role="status"`):

```tsx
function IntegrationsSection() {
  const queryClient = useQueryClient()
  const now = useNow()
  const tokens = useQuery({ queryKey: ["integration-tokens"], queryFn: api.integrationTokens })
  const [name, setName] = useState("")
  const [issued, setIssued] = useState<IssuedIntegrationToken | null>(null)
  const [revoking, setRevoking] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const origin = window.location.origin
  const issue = useMutation({
    mutationFn: () => api.issueIntegrationToken(name),
    onSuccess: async (token) => {
      setIssued(token)
      setName("")
      setCopied(false)
      await queryClient.invalidateQueries({ queryKey: ["integration-tokens"] })
    },
  })
  const revoke = useMutation({
    mutationFn: api.revokeIntegrationToken,
    onSuccess: async () => {
      setRevoking(null)
      await queryClient.invalidateQueries({ queryKey: ["integration-tokens"] })
    },
  })

  return (
    <section className="settings-section" aria-labelledby="integrations-title">
      <div className="section-heading">
        <div>
          <h2 id="integrations-title">Integrations</h2>
          <p>Tokens that let monitors, dashboards, and AI agents read whether synchronization is healthy. They cannot change anything.</p>
        </div>
      </div>
      {isPlainHttp(origin) && (
        <div className="inline-error" role="alert">
          This page uses plain HTTP, so a token sent to it can be read on your network. Serve Calendar Ghost over HTTPS before you issue one.
        </div>
      )}
      <form
        className="setting-row"
        onSubmit={(event) => {
          event.preventDefault()
          issue.mutate()
        }}
      >
        <div>
          <Label htmlFor="integration-name">Name</Label>
          <Input id="integration-name" value={name} maxLength={80} placeholder="Uptime Kuma" onChange={(event) => setName(event.target.value)} />
        </div>
        <Button type="submit" disabled={!name.trim() || issue.isPending}>
          {issue.isPending ? "Issuing…" : "Issue token"}
        </Button>
      </form>
      {issued && (
        <div className="setting-row" role="status">
          <div>
            <h3>Copy the token for {issued.name} now</h3>
            <p>It is shown only once. Store it in your password manager or the tool that uses it.</p>
            <code>{issued.token}</code>
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void navigator.clipboard.writeText(issued.token).then(() => setCopied(true))
            }}
          >
            {copied ? "Copied" : "Copy token"}
          </Button>
        </div>
      )}
      {tokens.isPending && <Skeleton className="h-16 w-full" />}
      {tokens.error && (
        <div className="inline-error" role="alert">
          Integration tokens could not load.
        </div>
      )}
      {tokens.data && tokens.data.length > 0 && (
        <div className="settings-list">
          {tokens.data.map((token) => (
            <div key={token.id}>
              <div className="setting-row">
                <div>
                  <h3>{token.name}</h3>
                  <p>{tokenUsage(token, now)}</p>
                </div>
                {!token.revoked_at && (
                  <Button type="button" variant="outline" aria-expanded={revoking === token.id} onClick={() => setRevoking(token.id)}>
                    Revoke
                  </Button>
                )}
              </div>
              {revoking === token.id && (
                <DestructiveConfirmation
                  id={`revoke-${token.id}`}
                  title={`Revoke ${token.name}?`}
                  body="Anything that uses this token loses access right away. This cannot be undone."
                  cancelLabel="Keep token"
                  confirmLabel="Revoke token"
                  pendingLabel="Revoking…"
                  pending={revoke.isPending}
                  onConfirm={() => revoke.mutate(token.id)}
                  onCancel={() => setRevoking(null)}
                />
              )}
            </div>
          ))}
        </div>
      )}
      <details className="inline-help setting-help">
        <summary>
          <span>Examples for monitors and agents</span>
          <ChevronDown className="inline-help-chevron" aria-hidden="true" />
        </summary>
        <div className="inline-help-body">
          {integrationExamples(origin).map((example) => (
            <div key={example.title}>
              <h3>{example.title}</h3>
              <p>{example.description}</p>
              <pre>
                <code>{example.code}</code>
              </pre>
            </div>
          ))}
        </div>
      </details>
      {(issue.error ?? revoke.error) && (
        <div className="inline-error" role="alert">
          {(issue.error ?? revoke.error)?.message}
        </div>
      )}
    </section>
  )
}
```

Import `Input`, `Label`, `useNow`,
`IssuedIntegrationToken`, and the helpers if `settings.tsx` does not import them yet. Use the
design tokens and classes that exist; add CSS only if `pre` blocks overflow the card, with
`overflow-x: auto` on `.inline-help-body pre`.

- [ ] **Step 4: Run the frontend gate and build**

Run: `npm --prefix web run typecheck && npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`
Expected: PASS, and `src/calendar_sync/interfaces/api/static/` changes.

- [ ] **Step 5: Check it in the browser**

Run the service (`.venv/bin/uvicorn calendar_sync.interfaces.api.app:create_app --factory`) and
open `http://localhost:8000/settings`. Issue a token, copy it, revoke it, and open the examples.
Then run `curl -s -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/status` with a
fresh token and confirm the JSON. Save a screenshot to `.context/integrations.png`.

- [ ] **Step 6: Commit**

```bash
git add web/src src/calendar_sync/interfaces/api/static
git commit -m "feat: issue and revoke Integration Tokens in Settings"
```

---

### Task 8: Documentation and the full gate

**Files:**
- Create: `docs/adr/0023-integration-tokens-installation-status-and-mcp.md`
- Modify: `CONTEXT.md` (Health and Access sections), `docs/self-hosting.md`, `AGENTS.md:116-118`,
  `CHANGELOG.md` (`[Unreleased]`), `tests/test_ubiquitous_language.py` only if a new avoided term
  is added

- [ ] **Step 1: Write ADR 0023**

Follow the structure of ADR 0022 (Context, Decision, Alternatives considered, Consequences).
Record:
- Context: monitors and agents could read only `/health`; the verdict lived in the browser; a
  stalled scheduler was invisible.
- Decision: Integration Tokens (format, hash, no expiry, one scope, header only, a present header
  decides alone); `GET /api/v1/status` as a separate contract; the server owns the verdict and the
  Overview renders it; the scheduler heartbeat and its 15-minute and 3-hour limits; overdue at 24
  hours; provider waiting escalates after 24 hours; MCP at `/mcp`, stateless JSON, POST only,
  bearer only; the SDK's DNS-rebinding allowlist is off because every request is authenticated;
  `/health` stays liveness only.
- Alternatives: tokens on the existing dashboard API; a status badge; a stdio MCP command; a
  separate summary scope; an in-memory heartbeat versus a persisted one.
- Consequences: a new dependency (`mcp`, `httpx2`, `pyjwt`, and their dependencies); new scopes
  need their own review; a reverse proxy that logs headers will record tokens.

- [ ] **Step 2: Update `CONTEXT.md`**

Under Health, add:

```markdown
**Installation Status**:
The server's one verdict on the installation's health (stalled, stopped, review, waiting, paused,
setup, or healthy) with every current problem, most urgent first. The Overview, the status API, and
MCP all show it. It names rules by their calendars and never carries event content, calendar IDs,
or account emails.
_Avoid_: Health check, status page
```

Under Access, add:

```markdown
**Integration Token**:
A named credential the Installation Administrator issues so a monitor or AI agent can read
Installation Status, and nothing else. Only its hash is stored; it is shown once and can be revoked.
_Avoid_: API key, personal access token
```

Append to **Public Health Status**: "Installation Status is its authenticated counterpart."

Run: `.venv/bin/pytest tests/test_ubiquitous_language.py -v`
Expected: PASS

- [ ] **Step 3: Update `docs/self-hosting.md`**

Add a section after "5. Use a LAN host or HTTPS" called "6. Connect monitors and agents"
(renumber the later sections): HTTPS first and why; issuing a token in Settings → Integrations;
Uptime Kuma (HTTP(s) - Json Query, `$.needs_attention`, expected `false`); Homepage customapi;
Claude Code and Codex snippets with `CALENDAR_GHOST_TOKEN`; a table of statuses and what to do;
that a reverse proxy logging request headers would record tokens.

- [ ] **Step 4: Update `AGENTS.md` and `CHANGELOG.md`**

In `AGENTS.md`, replace the security bullet text at lines 116-118 with:

```markdown
- Keep administrator-only API routes behind the session dependency. Only setup, login, the
  state-protected OAuth callback, static application files, and `/health` are intentionally public;
  `/health` is the only unauthenticated operational status route. `/api/v1/status` and `/mcp` are
  the only routes that accept an Integration Token, and `/mcp` accepts nothing else (ADR 0023).
```

In `CHANGELOG.md` under `[Unreleased]`, add an `### Added` entry:

```markdown
- Monitors, homelab dashboards, and AI agents can read Installation Status with an Integration
  Token: `GET /api/v1/status` for tools like Uptime Kuma and Homepage, and an MCP server at `/mcp`
  for Claude Code, Codex, and other agents. Settings → Integrations issues and revokes tokens.
- Installation Status notices a scheduler that stopped running passes and a rule that has not
  synced in over a day.
```

and a `### Changed` entry: "The Overview shows the server's health verdict, so it always agrees
with the status API."

- [ ] **Step 5: Run every quality gate**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
npm --prefix web run typecheck
npm --prefix web run lint
npm --prefix web run test
npm --prefix web run build
grep -rn $'\xe2\x80\x94' src web/src docs/adr/0023* CONTEXT.md AGENTS.md CHANGELOG.md docs/self-hosting.md
```

Expected: every command passes, and the last `grep` prints nothing. Also run
`docker compose build` to confirm the image installs the new dependency.

- [ ] **Step 6: Commit**

```bash
git add docs CONTEXT.md AGENTS.md CHANGELOG.md src/calendar_sync/interfaces/api/static
git commit -m "docs: record Integration Tokens, Installation Status, and MCP (ADR 0023)"
```
