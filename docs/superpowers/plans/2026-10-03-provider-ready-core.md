# Provider-Ready Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make adding a calendar provider mean adding an adapter package, not reshaping the core.
Google stays the only provider, and synchronization behavior does not change.

**Architecture:**
- **Provider Kind.** Every Connected Account records a `ProviderKind`. Migration 17 lifts the
  `provider = 'google'` CHECK constraint.
- **Routing.** `RoutingCalendarProvider` and `RoutingAccountCalendars` implement the existing ports
  and send each request to the adapter of the account it names. Use cases do not change.
- **Domain rules leave the adapter.** Which occurrences a rule projects, and which occurrences are
  exceptions, move into the domain.
- **Provider-neutral edges.** Calendars report `writable` instead of Google access roles. Call
  instrumentation moves out of the Google package. Incident summaries name the provider through its
  `ProviderKind`.
- **Contract suite.** A shared test suite pins what every adapter must honor. It runs against the
  test fake and the router now, and against each new adapter later.

**Tech Stack:** Python 3.12, SQLite, FastAPI and pydantic, pytest, import-linter, React with
TypeScript and vitest.

**Spec:** `docs/adr/0022-route-calendar-requests-by-provider.md`

**Not in this plan:**
- The Outlook adapter, which gets its own plan.
- CalDAV and non-OAuth connection methods.
- Provider Capabilities.
- Web UI copy that says "Google account".
- Splitting `GoogleOAuthService`.
- Occurrence roles in the contract suite.

## Global Constraints

- Follow `AGENTS.md`. Use the terms in `CONTEXT.md`. `tests/test_ubiquitous_language.py` must pass.
- Google synchronization behavior must not change. The only intended differences:
  - incident summaries (Task 6);
  - the `google_calls=` log key becomes `provider_calls=` (Task 4);
  - the new additive API fields (Tasks 2 and 3).
- Never change these Google routes:
  - `/api/v1/oauth/google/start`
  - `/api/v1/oauth/google/callback`
  - `/api/v1/google/configuration`
- HTTP payload changes are additive only. `access_role` stays in calendar responses.
- `lint-imports` must pass. Never add an `ignore_imports` entry.
- Migration 17 must keep every `connected_accounts` row and every `calendar_names` row. Rolling
  back past it means restoring a backup.
- After any `web/` change, run the frontend build and commit
  `src/calendar_sync/interfaces/api/static/` in the same commit.
- Coverage floor: 80%.
- Backend gates, all of which must pass before handing off:
  - `.venv/bin/ruff format --check .`
  - `.venv/bin/ruff check .`
  - `.venv/bin/mypy`
  - `.venv/bin/lint-imports`
  - `.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80`
- Frontend gates, when `web/` changes:
  - `npm --prefix web run typecheck`
  - `npm --prefix web run lint`
  - `npm --prefix web run test`
  - `npm --prefix web run build`
- Every commit message ends with
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Upgrading an installation that has accounts and recorded calendar names.** The table rebuild
   runs with foreign keys on. Dropping `connected_accounts` directly would cascade-delete
   `calendar_names`. Rows must survive, and rules must still show their calendar names. Covered in
   Task 2.
2. **The same email connected under two providers.** Reauthorizing one must not return or
   overwrite the other. Covered in Task 2.
3. **A rule naming an account that no longer exists.** The router must fail the way the Google
   adapter did: a `PERMANENT` `ProviderFailure` naming the account, not an unhandled
   `ConnectedAccountNotFound`. Covered in Task 5.
4. **An occurrence reported in another UTC offset than its series.** It is the same occurrence,
   not an exception, so no destination write happens. Covered in Task 1.
5. **A read-only calendar.** It must never be offered as a Destination Calendar once access roles
   are gone. Covered in Task 3: the API test pins `writable: false`, and the rule builder filters
   on it.

---

### Task 1: The domain decides which occurrences a rule projects

**Files:**
- Modify: `src/calendar_sync/domain/model.py` (`TransformationPolicy`, `CalendarEvent`)
- Modify: `src/calendar_sync/infrastructure/google/provider.py` (`has_live_occurrences`,
  `occurrence_exceptions`; delete `_projected` and `_is_exception`)
- Modify: `tests/fake_calendar.py` (`has_live_occurrences`, `occurrence_exceptions`)
- Create: `tests/domain/test_occurrence_projection.py`

**Interfaces:**
- Produces: `TransformationPolicy.projects(event: CalendarEvent) -> bool` and
  `CalendarEvent.is_exception_of(series: CalendarEvent) -> bool`.

- [ ] **Step 1: Write the failing tests**

`tests/domain/test_occurrence_projection.py`:

```python
"""Which occurrences a rule projects, and which differ from their series, decided once."""

from dataclasses import replace
from datetime import timedelta, timezone

from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    EventStatus,
    InvitationResponse,
    TimedInterval,
    TransformationPolicy,
)
from tests.helpers import occurrence, series


def test_a_policy_projects_a_live_occurrence_it_does_not_exclude() -> None:
    assert TransformationPolicy().projects(occurrence(series()))


def test_a_policy_never_projects_a_cancelled_occurrence() -> None:
    assert not TransformationPolicy().projects(occurrence(series(), status=EventStatus.CANCELLED))


def test_a_policy_does_not_project_an_occurrence_it_excludes() -> None:
    policy = TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE)

    assert not policy.projects(occurrence(series(all_day=True), all_day=True))


def test_an_unchanged_occurrence_is_not_an_exception() -> None:
    master = series()

    assert not occurrence(master).is_exception_of(master)


def test_an_occurrence_reported_in_another_utc_offset_is_not_an_exception() -> None:
    master = series()
    plain = occurrence(master)
    assert isinstance(plain.time, TimedInterval)
    madrid = timezone(timedelta(hours=2))
    shifted = replace(
        plain,
        time=TimedInterval(
            plain.time.starts_at.astimezone(madrid), plain.time.ends_at.astimezone(madrid)
        ),
    )

    assert not shifted.is_exception_of(master)


def test_a_cancelled_occurrence_is_an_exception() -> None:
    master = series()

    assert occurrence(master, status=EventStatus.CANCELLED).is_exception_of(master)


def test_a_moved_occurrence_is_an_exception() -> None:
    master = series()

    assert occurrence(master, moved_by=timedelta(hours=2)).is_exception_of(master)


def test_a_lengthened_occurrence_is_an_exception() -> None:
    master = series()
    plain = occurrence(master)
    assert isinstance(plain.time, TimedInterval)
    longer = replace(
        plain,
        time=TimedInterval(plain.time.starts_at, plain.time.ends_at + timedelta(minutes=30)),
    )

    assert longer.is_exception_of(master)


def test_a_retitled_occurrence_is_an_exception() -> None:
    master = series()

    assert occurrence(master, title="Moved to the café").is_exception_of(master)


def test_an_occurrence_answered_differently_is_an_exception() -> None:
    master = series()
    declined = replace(occurrence(master), response=InvitationResponse.DECLINED)

    assert declined.is_exception_of(master)


def test_an_occurrence_switched_to_all_day_is_an_exception() -> None:
    master = series()

    assert occurrence(master, all_day=True).is_exception_of(master)


def test_only_an_occurrence_of_this_series_can_be_its_exception() -> None:
    master = series()
    elsewhere = occurrence(series("other-series"), status=EventStatus.CANCELLED)

    assert not elsewhere.is_exception_of(master)
    assert not master.is_exception_of(master)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/domain/test_occurrence_projection.py -q`
Expected: FAIL with `AttributeError: 'TransformationPolicy' object has no attribute 'projects'`
and `'CalendarEvent' object has no attribute 'is_exception_of'`.

- [ ] **Step 3: Add the domain predicates**

In `src/calendar_sync/domain/model.py`, add to `TransformationPolicy`, after `exclusion`:

```python
    def projects(self, event: CalendarEvent) -> bool:
        """Whether this policy projects a live event; a cancelled one is never projected.

        Adapters ask this while listing a series' occurrences, so whether a series still has one
        to project is decided here once, for every provider (ADR 0022).
        """
        return event.status is EventStatus.CONFIRMED and self.exclusion(event) is None
```

Add to `CalendarEvent`, after `occurrence_reaches`:

```python
    def is_exception_of(self, series: CalendarEvent) -> bool:
        """Whether this occurrence of `series` is cancelled or differs from its regular one.

        Times are compared as instants, so an occurrence a provider reports in another UTC offset
        is still the regular one.
        """
        identity = self.occurrence
        if identity is None or identity.series_event_id != series.reference.event_id:
            return False
        if self.status is EventStatus.CANCELLED:
            return True
        if (self.title, self.description, self.location, self.response) != (
            series.title,
            series.description,
            series.location,
            series.response,
        ):
            return True
        time, regular, original = self.time, series.time, identity.original_start
        if isinstance(time, TimedInterval) and isinstance(regular, TimedInterval):
            return (
                occurrence_start(time.starts_at) != original
                or time.ends_at - time.starts_at != regular.ends_at - regular.starts_at
            )
        if isinstance(time, AllDayRange) and isinstance(regular, AllDayRange):
            return (
                time.starts_on != original
                or time.ends_before - time.starts_on != regular.ends_before - regular.starts_on
            )
        # The occurrence switched between timed and all-day.
        return True
```

- [ ] **Step 4: Run the domain tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_occurrence_projection.py -q`
Expected: PASS.

- [ ] **Step 5: Make the Google adapter and the fake use the predicates**

In `src/calendar_sync/infrastructure/google/provider.py`:

- In `has_live_occurrences`, replace
  `_projected(to_domain_event(item, series.calendar), policy)` with
  `policy.projects(to_domain_event(item, series.calendar))`.
- In `occurrence_exceptions`, replace `_is_exception(instance, master)` with
  `instance.is_exception_of(master)`.
- Delete the module functions `_projected` and `_is_exception`.
- Run `.venv/bin/ruff check --fix src/calendar_sync/infrastructure/google/provider.py` to drop the
  imports it reports unused.

In `tests/fake_calendar.py`, change the end of `has_live_occurrences` to:

```python
        return any(
            policy.projects(self._instance(master, start)) for start in self.live_starts(series)
        )
```

Then replace the body of `occurrence_exceptions` after the `master` check with:

```python
        return tuple(
            instance
            for instance in self.instances_of(series)
            if instance.is_exception_of(master) and instance.occurrence_reaches(not_ended_before)
        )
```

- [ ] **Step 6: Run the provider and synchronization tests**

Run: `.venv/bin/pytest tests/domain tests/application tests/adapters/test_google_provider.py -q`
Expected: PASS. The behavior is unchanged, because the predicates are the adapter's code moved
into the domain.

- [ ] **Step 7: Commit**

```bash
git add src/calendar_sync/domain/model.py src/calendar_sync/infrastructure/google/provider.py \
  tests/fake_calendar.py tests/domain/test_occurrence_projection.py
git commit -m "refactor: decide projected occurrences and exceptions in the domain

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Connected Accounts record their Provider Kind

**Files:**
- Create: `src/calendar_sync/application/providers.py`
- Modify: `src/calendar_sync/application/ports.py` (`ConnectedAccount`)
- Create: `src/calendar_sync/infrastructure/persistence/0017_provider_kinds.sql`
- Modify: `src/calendar_sync/infrastructure/persistence/sqlite.py` (`_FORWARD_MIGRATIONS`)
- Modify: `src/calendar_sync/infrastructure/persistence/accounts.py`
- Modify: `src/calendar_sync/infrastructure/google/oauth.py` (`complete`)
- Modify: `src/calendar_sync/interfaces/api/schemas.py` (`ConnectedAccountResponse`)
- Modify: `src/calendar_sync/interfaces/api/routes/accounts.py` (`_account_response`)
- Modify: `scripts/dev_preview.py` (`ACCOUNTS`), `tests/application/test_accounts.py` (`_account`)
- Modify: every account-store `save(...)` call in `tests/adapters/`
- Modify: `CONTEXT.md`
- Create: `tests/adapters/test_connected_account_providers.py`

**Interfaces:**
- Produces:
  - `ProviderKind(StrEnum)` with `GOOGLE = "google"` and the property `calendar_name -> str`
    (`"Google Calendar"`), in `calendar_sync.application.providers`.
  - `ConnectedAccount.provider: ProviderKind`, a required keyword field.
  - `SqliteConnectedAccountStore.save(display_name, email, credential_json, *, provider:
    ProviderKind, avatar_url: str | None = None) -> ConnectedAccount`.
  - `SqliteConnectedAccountStore.provider_of(account_id: ConnectedAccountId) -> ProviderKind |
    None`.
  - The `provider` field in every Connected Account API payload.

- [ ] **Step 1: Write the failing tests**

`tests/adapters/test_connected_account_providers.py`:

```python
"""Each Connected Account belongs to one provider, recorded when it connects (ADR 0022)."""

import sqlite3
from pathlib import Path

from calendar_sync.application.ports import DiscoveredCalendar
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.security import CredentialCipher
from tests.helpers import endpoint

ANOTHER_PROVIDERS_ACCOUNT = """
    INSERT INTO connected_accounts (
        id, provider, display_name, email, encrypted_credentials, state, created_at, updated_at
    ) VALUES (
        'elsewhere', 'another-provider', 'Elsewhere', 'person@example.test', x'00',
        'connected', '2026-10-01', '2026-10-01'
    )
"""


def _store(database: Path) -> SqliteConnectedAccountStore:
    initialize_database(database)
    return SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))


def test_a_connected_account_records_its_provider(tmp_path: Path) -> None:
    store = _store(tmp_path / "test.db")

    account = store.save("Personal", "person@example.test", "{}", provider=ProviderKind.GOOGLE)

    assert account.provider is ProviderKind.GOOGLE
    assert store.get(account.id) == account
    assert store.provider_of(account.id) is ProviderKind.GOOGLE


def test_an_account_that_does_not_exist_has_no_provider(tmp_path: Path) -> None:
    assert _store(tmp_path / "test.db").provider_of(ConnectedAccountId("missing")) is None


def test_reauthorization_finds_the_account_by_provider_and_email(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    store = _store(database)
    with sqlite3.connect(database) as connection:
        connection.execute(ANOTHER_PROVIDERS_ACCOUNT)

    google = store.save("Personal", "person@example.test", "{}", provider=ProviderKind.GOOGLE)
    again = store.save("Renamed", "person@example.test", "{}", provider=ProviderKind.GOOGLE)

    assert google.id.value != "elsewhere"
    assert (again.id, again.display_name) == (google.id, "Renamed")
    with sqlite3.connect(database) as connection:
        untouched = connection.execute(
            "SELECT display_name FROM connected_accounts WHERE id = 'elsewhere'"
        ).fetchone()
    assert untouched == ("Elsewhere",)


def test_migration_17_keeps_accounts_and_their_calendar_names(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    store = _store(database)
    account = store.save(
        "Personal",
        "person@example.test",
        '{"token":"one"}',
        provider=ProviderKind.GOOGLE,
        avatar_url="https://example.test/avatar.png",
    )
    family = endpoint(account.id.value, "family")
    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.calendar_names.remember(
            account.id, [DiscoveredCalendar("family", "Family", "owner", primary=False)]
        )
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 17")

    initialize_database(database)

    assert store.get(account.id) == account
    assert store.credential_json(account.id) == '{"token":"one"}'
    with SqliteUnitOfWorkFactory(database)() as uow:
        assert uow.calendar_names.names([family]) == {family: "Family"}


def test_any_provider_kind_can_be_stored(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    _store(database)

    with sqlite3.connect(database) as connection:
        connection.execute(ANOTHER_PROVIDERS_ACCOUNT)
        stored = connection.execute("SELECT provider FROM connected_accounts").fetchall()

    assert stored == [("another-provider",)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_connected_account_providers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'calendar_sync.application.providers'`.

- [ ] **Step 3: Add `ProviderKind`**

`src/calendar_sync/application/providers.py`:

```python
"""The calendar services Connected Accounts can belong to (ADR 0022)."""

from __future__ import annotations

from enum import StrEnum


class ProviderKind(StrEnum):
    """The calendar service a Connected Account belongs to; stored, so values never change."""

    GOOGLE = "google"

    @property
    def calendar_name(self) -> str:
        """How messages name the service, such as "Google Calendar"."""
        return _CALENDAR_NAMES[self]


_CALENDAR_NAMES = {ProviderKind.GOOGLE: "Google Calendar"}
```

In `src/calendar_sync/application/ports.py`, import `field` from `dataclasses` and
`ProviderKind` from `calendar_sync.application.providers`. Then add the field last in
`ConnectedAccount`:

```python
    provider: ProviderKind = field(kw_only=True)
    """The calendar service the account belongs to; it never changes (ADR 0022)."""
```

- [ ] **Step 4: Add migration 17**

`src/calendar_sync/infrastructure/persistence/0017_provider_kinds.sql`:

```sql
-- Connected Accounts may belong to any calendar provider (ADR 0022). Code validates the provider,
-- so adding one needs no schema change. SQLite cannot drop a CHECK constraint, so the table is
-- rebuilt. Foreign keys are on while migrations run, and dropping the old table would delete
-- every calendar name through ON DELETE CASCADE, so calendar names are set aside first and
-- restored afterwards.
CREATE TEMP TABLE calendar_names_kept AS SELECT * FROM calendar_names;
DROP TABLE calendar_names;

CREATE TABLE connected_accounts_rebuilt (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    display_name TEXT NOT NULL,
    email TEXT NOT NULL,
    encrypted_credentials BLOB NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    avatar_url TEXT,
    UNIQUE (provider, email)
);
INSERT INTO connected_accounts_rebuilt (
    id, provider, display_name, email, encrypted_credentials, state, created_at, updated_at,
    avatar_url
)
SELECT
    id, provider, display_name, email, encrypted_credentials, state, created_at, updated_at,
    avatar_url
FROM connected_accounts;
DROP TABLE connected_accounts;
ALTER TABLE connected_accounts_rebuilt RENAME TO connected_accounts;

CREATE TABLE calendar_names (
    connected_account_id TEXT NOT NULL REFERENCES connected_accounts(id) ON DELETE CASCADE,
    calendar_id TEXT NOT NULL,
    name TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (connected_account_id, calendar_id)
);
INSERT INTO calendar_names (connected_account_id, calendar_id, name, updated_at)
SELECT connected_account_id, calendar_id, name, updated_at FROM calendar_names_kept;
DROP TABLE calendar_names_kept;
```

In `src/calendar_sync/infrastructure/persistence/sqlite.py`, append
`(17, "0017_provider_kinds.sql"),` to `_FORWARD_MIGRATIONS`.

- [ ] **Step 5: Store and read the provider**

In `src/calendar_sync/infrastructure/persistence/accounts.py`, import `ProviderKind`. Then:

- Add `provider` to the column list of every `SELECT` that builds a `ConnectedAccount`. These are
  in `list`, `get`, `save`, and `disconnect`; for example
  `SELECT id, provider, display_name, email, state, avatar_url, updated_at`.
- Replace `save` with:

```python
    def save(
        self,
        display_name: str,
        email: str,
        credential_json: str,
        *,
        provider: ProviderKind,
        avatar_url: str | None = None,
    ) -> ConnectedAccount:
        """Connect an account, or reauthorize the one with this provider and email."""
        now = self._clock.now().isoformat()
        account_id = self._ids.new()
        encrypted = self._cipher.encrypt(credential_json)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO connected_accounts (
                    id, provider, display_name, email, avatar_url, encrypted_credentials,
                    state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'connected', ?, ?)
                ON CONFLICT(provider, email) DO UPDATE SET
                    display_name = excluded.display_name,
                    avatar_url = excluded.avatar_url,
                    encrypted_credentials = excluded.encrypted_credentials,
                    state = 'connected',
                    updated_at = excluded.updated_at
                """,
                (account_id, provider.value, display_name, email, avatar_url, encrypted, now, now),
            )
            row = connection.execute(
                """
                SELECT id, provider, display_name, email, state, avatar_url, updated_at
                FROM connected_accounts WHERE provider = ? AND email = ?
                """,
                (provider.value, email),
            ).fetchone()
        assert row is not None
        return _account_from_row(row)
```

- Add after `is_connected`:

```python
    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
        """The provider a Connected or Disconnected Account belongs to; None if it does not exist."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT provider FROM connected_accounts WHERE id = ?", (account_id.value,)
            ).fetchone()
        return ProviderKind(str(row["provider"])) if row is not None else None
```

- In `disconnect`, pass `provider=ProviderKind(str(row["provider"]))` to the `ConnectedAccount`
  it returns.
- In `_account_from_row`, pass `provider=ProviderKind(str(row["provider"]))`.

In `src/calendar_sync/infrastructure/google/oauth.py`, import `ProviderKind` and pass
`provider=ProviderKind.GOOGLE` in the `self._accounts.save(...)` call in `complete`.

- [ ] **Step 6: Expose the provider and update construction sites**

- `schemas.py`: add `provider: str` to `ConnectedAccountResponse`, after `email`.
- `routes/accounts.py`: in `_account_response`, pass `provider=account.provider.value`.
- `scripts/dev_preview.py`: add `provider=ProviderKind.GOOGLE` to each of the three
  `ConnectedAccount(...)` calls in `ACCOUNTS`.
- `tests/application/test_accounts.py`: in `_account`, pass `provider=ProviderKind.GOOGLE`.
- Account-store `save` calls in tests: add `provider=ProviderKind.GOOGLE` as a keyword argument to
  each, and import `ProviderKind` where needed. To list them, run
  `rg -n '(store|accounts)\.save\(' tests/adapters`. Run `.venv/bin/mypy` until it reports no
  `Missing named argument "provider"`.
- `tests/adapters/test_api.py`: add `"provider": "google",` to the expected account dict in the
  test that asserts `"rule_count": 4`.

- [ ] **Step 7: Update the glossary**

In `CONTEXT.md` under **Authorization**:

- Replace the **Connected Account** definition with: "A calendar-service identity authorized on
  this installation, such as a Google account authorized through one OAuth grant. It belongs to
  exactly one Provider Kind. A sync rule may use different connected accounts, even of different
  providers, for its source and destination calendars."
- Add after it:

```markdown
**Provider Kind**:
The calendar service a Connected Account belongs to, such as Google. It is recorded when the account is first connected and never changes. Every request about the account's calendars goes to that provider's adapter (ADR 0022).
_Avoid_: Account type, integration
```

- In **Disconnected Account**, change "A previously connected Google identity" to "A previously
  connected identity".
- Change "remain in Google Calendar and are no longer managed" to "remain in their destination
  calendars and are no longer managed".

- [ ] **Step 8: Run the tests**

Run: `.venv/bin/pytest tests/adapters tests/application tests/test_ubiquitous_language.py tests/test_dev_preview.py -q && .venv/bin/mypy`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add -A src/calendar_sync scripts tests CONTEXT.md
git commit -m "feat: record each Connected Account's Provider Kind

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Discovered calendars say whether rules can write to them

**Files:**
- Modify: `src/calendar_sync/application/ports.py` (`DiscoveredCalendar`)
- Modify: `src/calendar_sync/infrastructure/google/oauth.py` (`calendars`, `verify_access`, new
  `discovered_calendar`)
- Modify: `src/calendar_sync/interfaces/api/schemas.py` (`DiscoveredCalendarResponse`)
- Modify: `src/calendar_sync/interfaces/api/routes/accounts.py` (`discover_calendars`)
- Modify: `scripts/dev_preview.py`, `tests/adapters/test_api.py`,
  `tests/adapters/test_connected_account_providers.py` (the `DiscoveredCalendar(...)` calls)
- Modify: `web/src/lib/api.ts`, `web/src/features/rules.tsx`, `web/src/features/rule-details.tsx`
- Modify: `src/calendar_sync/interfaces/api/static/` (rebuilt)
- Test: `tests/adapters/test_google_oauth_storage.py`, `tests/adapters/test_api.py`

**Interfaces:**
- Consumes: `ProviderKind` and `save(..., provider=...)` from Task 2.
- Produces:
  - `DiscoveredCalendar(id: str, summary: str, writable: bool, primary: bool)`.
  - `discovered_calendar(item: Mapping[str, Any]) -> DiscoveredCalendar` in `google/oauth.py`.
  - `writable: bool` in calendar API payloads.

- [ ] **Step 1: Write the failing tests**

Append to `tests/adapters/test_google_oauth_storage.py`, and import `discovered_calendar` from
`calendar_sync.infrastructure.google.oauth` and `DiscoveredCalendar` from
`calendar_sync.application.ports`:

```python
@pytest.mark.parametrize(
    ("role", "writable"),
    [("owner", True), ("writer", True), ("reader", False), ("freeBusyReader", False), (None, False)],
)
def test_google_access_roles_decide_whether_a_calendar_is_writable(
    role: str | None, writable: bool
) -> None:
    item = {"id": "family", "summary": "Family", "accessRole": role}

    assert discovered_calendar(item) == DiscoveredCalendar(
        "family", "Family", writable=writable, primary=False
    )
```

Append to `tests/adapters/test_api.py`, and import `ProviderKind`:

```python
def test_discovered_calendars_say_whether_rules_can_write_to_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container, adapters = _installation(
        Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    )
    assert adapters.accounts is not None
    assert adapters.google_oauth is not None
    account = adapters.accounts.save(
        "Personal", "person@example.test", "{}", provider=ProviderKind.GOOGLE
    )
    listed = Mock(
        return_value=[
            DiscoveredCalendar("family", "Family", writable=True, primary=True),
            DiscoveredCalendar("holidays", "Holidays", writable=False, primary=False),
        ]
    )
    monkeypatch.setattr(adapters.google_oauth, "calendars", listed)

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        response = client.get(f"/api/v1/accounts/{account.id.value}/calendars")

    assert response.json() == [
        {
            "id": "family",
            "summary": "Family",
            "access_role": "writer",
            "writable": True,
            "primary": True,
        },
        {
            "id": "holidays",
            "summary": "Holidays",
            "access_role": "reader",
            "writable": False,
            "primary": False,
        },
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_google_oauth_storage.py tests/adapters/test_api.py -q -k "writable"`
Expected: FAIL with `ImportError: cannot import name 'discovered_calendar'`.

- [ ] **Step 3: Replace the access role with `writable`**

In `ports.py`:

```python
@dataclass(frozen=True, slots=True)
class DiscoveredCalendar:
    id: str
    summary: str
    writable: bool
    """Whether rules may write projections to it, as its provider grants this account."""
    primary: bool
```

In `google/oauth.py`, import `Mapping` from `collections.abc`. Add after `OAUTH_SCOPES`:

```python
WRITABLE_ACCESS_ROLES = frozenset({"owner", "writer"})
"""Google access roles that let a Connected Account write events to a calendar."""
```

Add at module level:

```python
def discovered_calendar(item: Mapping[str, Any]) -> DiscoveredCalendar:
    """One Google calendar list entry, without Google's access-role vocabulary."""
    return DiscoveredCalendar(
        id=str(item["id"]),
        summary=str(item.get("summary") or item["id"]),
        writable=item.get("accessRole") in WRITABLE_ACCESS_ROLES,
        primary=bool(item.get("primary")),
    )
```

- In `calendars`, return
  `tuple(discovered_calendar(item) for item in self._calendar_items(service) if isinstance(item.get("id"), str))`.
- In `verify_access`, count with `item.get("accessRole") in WRITABLE_ACCESS_ROLES`.

In `schemas.py`:

```python
class DiscoveredCalendarResponse(BaseModel):
    id: str
    summary: str
    access_role: str
    """Kept for API compatibility; `writable` replaces it (ADR 0022)."""
    writable: bool
    primary: bool
```

In `routes/accounts.py` `discover_calendars`, build each response with
`access_role="writer" if calendar.writable else "reader"` and `writable=calendar.writable`.

To update the other construction sites, run `rg -n 'DiscoveredCalendar\(' scripts tests`. In each
call, replace the access-role string with `writable=True` (every existing site uses `"owner"` or
`"writer"`), and pass `primary` by keyword.

- [ ] **Step 4: Run the backend tests**

Run: `.venv/bin/pytest tests/adapters tests/application tests/test_dev_preview.py -q && .venv/bin/mypy`
Expected: PASS.

- [ ] **Step 5: The Web UI reads `writable`**

- `web/src/lib/api.ts`: replace `access_role: string` in `DiscoveredCalendar` with
  `writable: boolean`.
- `web/src/features/rules.tsx`:
  - Delete `const WRITABLE_ROLES = ["writer", "owner"]`.
  - In `firstOtherCalendar`, use `.filter((calendar) => calendar.writable)`.
  - For `writableDestinations`, use `.filter((calendar) => calendar.writable)`.
- `web/src/features/rule-details.tsx`: change the options filter to
  `(item) => !writableOnly || item.writable`.

Run: `npm --prefix web run typecheck && npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`
Expected: PASS, and the build rewrites `src/calendar_sync/interfaces/api/static/`.

- [ ] **Step 6: Commit**

```bash
git add -A src/calendar_sync scripts tests web/src
git commit -m "refactor: discovered calendars report writability, not Google access roles

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Provider call instrumentation is shared by every adapter

**Files:**
- Create: `src/calendar_sync/infrastructure/provider_calls.py`
- Delete: `src/calendar_sync/infrastructure/google/instrumentation.py`
- Modify: `src/calendar_sync/infrastructure/google/provider.py` (`_call`),
  `src/calendar_sync/infrastructure/google/oauth.py` (import)
- Modify: `src/calendar_sync/bootstrap/container.py` (`call_stats`)
- Modify: `src/calendar_sync/application/run_log.py` (`call_summary`),
  `src/calendar_sync/application/sync_run.py` (progress line)
- Move: `tests/adapters/test_google_instrumentation.py` to `tests/adapters/test_provider_calls.py`
- Modify: `tests/adapters/test_google_credentials.py`, `tests/application/test_run_logging.py`
- Modify: `docs/troubleshooting.md`, `docs/architecture.md`

**Interfaces:**
- Consumes: `ProviderKind` from Task 2.
- Produces:
  - `ContextProviderCallStats` (implements `ProviderCallStats`).
  - `record_call(provider: ProviderKind, operation: str, status: int | None, seconds: float, *,
    rate_limited: bool) -> None`.
  - `record_token_refresh() -> None`.
  - All three in `calendar_sync.infrastructure.provider_calls`.

- [ ] **Step 1: Move the tests and point them at the new module**

```bash
git mv tests/adapters/test_google_instrumentation.py tests/adapters/test_provider_calls.py
sed -i '' \
  -e 's/calendar_sync\.infrastructure\.google\.instrumentation/calendar_sync.infrastructure.provider_calls/' \
  -e 's/GoogleCallStats/ContextProviderCallStats/g' \
  -e 's/record_call("/record_call(ProviderKind.GOOGLE, "/g' \
  -e 's/"google call op=/"provider call provider=google op=/g' \
  -e 's/"slow google call op=/"slow provider call provider=google op=/g' \
  tests/adapters/test_provider_calls.py tests/adapters/test_google_credentials.py
sed -i '' 's/google_calls=/provider_calls=/g' tests/application/test_run_logging.py
```

Add `from calendar_sync.application.providers import ProviderKind` to
`tests/adapters/test_provider_calls.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_provider_calls.py tests/application/test_run_logging.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'calendar_sync.infrastructure.provider_calls'`,
and run-log assertions expecting `provider_calls=`.

- [ ] **Step 3: Create the shared module**

Move `src/calendar_sync/infrastructure/google/instrumentation.py` to
`src/calendar_sync/infrastructure/provider_calls.py` with `git mv`, then make these changes:

- Replace the module docstring's first paragraph with: "Counts and times calendar provider calls
  for the run that makes them. Every adapter reports its calls here, so one tally covers a rule
  whose calendars belong to different providers." Keep the rest of the docstring.
- Rename the context variable to `ContextVar("provider_call_tally", default=None)`.
- Rename `GoogleCallStats` to `ContextProviderCallStats`, with the docstring "ProviderCallStats
  for every calendar adapter."
- Make `record_call` take the provider first, and log it:

```python
def record_call(
    provider: ProviderKind,
    operation: str,
    status: int | None,
    seconds: float,
    *,
    rate_limited: bool,
) -> None:
    """Add one finished provider call to the current run's tally, and log it.

    `status` is None when no HTTP answer arrived, such as when the provider could not be reached.
    """
    tally = _current.get()
    if tally is not None:
        tally.calls += 1
        tally.seconds += seconds
        tally.slowest_seconds = max(tally.slowest_seconds, seconds)
        if rate_limited:
            tally.rate_limited += 1
        if status is not None and status >= 500:
            tally.server_errors += 1
    shown = "none" if status is None else str(status)
    logger.debug(
        "provider call provider=%s op=%s status=%s took=%dms",
        provider.value,
        operation,
        shown,
        round(seconds * 1000),
    )
    if seconds >= SLOW_CALL_SECONDS:
        logger.warning(
            "slow provider call provider=%s op=%s status=%s took=%.1fs",
            provider.value,
            operation,
            shown,
            seconds,
        )
```

Import `ProviderKind` there. Then update the callers:

- `google/provider.py`: import `record_call` from `calendar_sync.infrastructure.provider_calls`,
  and in `_call` use `record_call(ProviderKind.GOOGLE, operation, status, ...)`.
- `google/oauth.py`: import `record_token_refresh` from the new module.
- `bootstrap/container.py`: import `ContextProviderCallStats` from
  `calendar_sync.infrastructure.provider_calls`, and set `call_stats=ContextProviderCallStats()`.
- `application/run_log.py`: in `call_summary`, use `f"provider_calls={calls.calls} ..."`.
- `application/sync_run.py`: in the progress line, use `provider_calls=%d`.

- [ ] **Step 4: Update the docs**

- Run `sed -i '' 's/google_calls/provider_calls/g' docs/troubleshooting.md`.
- In `docs/architecture.md` under **Logging**, replace "The Google adapter sends every request
  through one helper that times it, and `infrastructure/google/instrumentation.py` keeps each
  measured run's tally" with "Each adapter sends every request through one helper that times it,
  and `infrastructure/provider_calls.py` keeps each measured run's tally".

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/adapters tests/application -q && .venv/bin/mypy && .venv/bin/lint-imports`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A src/calendar_sync tests docs
git commit -m "refactor: share provider call instrumentation across adapters

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Route calendar requests by the account's provider

**Files:**
- Modify: `src/calendar_sync/application/errors.py` (`ProviderFailure.provider`)
- Modify: `src/calendar_sync/infrastructure/google/provider.py` (`_failure` and direct
  `ProviderFailure(...)` constructions)
- Create: `src/calendar_sync/infrastructure/providers/__init__.py` (empty) and
  `src/calendar_sync/infrastructure/providers/routing.py`
- Modify: `src/calendar_sync/bootstrap/container.py` (`Adapters`, `build_adapters`, `compose`)
- Modify: `src/calendar_sync/interfaces/api/routes/accounts.py` (`discover_calendars`,
  `verify_account_access`)
- Modify: `docs/architecture.md`
- Create: `tests/adapters/test_provider_routing.py`
- Modify: `tests/adapters/test_google_provider.py`, `tests/adapters/test_api.py`

**Interfaces:**
- Consumes: `ProviderKind` and `SqliteConnectedAccountStore.provider_of` from Task 2.
- Produces:
  - `ProviderFailure.provider: ProviderKind | None = None`.
  - `ProviderKinds` protocol: `provider_of(account_id) -> ProviderKind | None`.
  - `RoutingCalendarProvider(kinds: ProviderKinds, adapters: Mapping[ProviderKind,
    CalendarProvider])`.
  - `RoutingAccountCalendars(kinds: ProviderKinds, adapters: Mapping[ProviderKind,
    AccountCalendars])`.
  - `Adapters.account_calendars: AccountCalendars | None`.

- [ ] **Step 1: Write the failing tests**

`tests/adapters/test_provider_routing.py`:

```python
"""Each calendar request reaches the adapter of its account's provider (ADR 0022)."""

from dataclasses import dataclass, field
from typing import cast
from unittest.mock import Mock

import pytest

from calendar_sync.application.errors import (
    AuthorizationNotConfigured,
    ConnectedAccountNotFound,
    ProviderFailure,
    ProviderFailureKind,
)
from calendar_sync.application.ports import AccountCalendars, DiscoveredCalendar
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.providers.routing import (
    RoutingAccountCalendars,
    RoutingCalendarProvider,
)
from tests.fake_calendar import FakeCalendars
from tests.helpers import event

PERSONAL = ConnectedAccountId("personal-account")


@dataclass
class StoredKinds:
    kinds: dict[ConnectedAccountId, ProviderKind]
    lookups: list[ConnectedAccountId] = field(default_factory=list)

    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
        self.lookups.append(account_id)
        return self.kinds.get(account_id)


def test_a_request_reaches_the_adapter_of_its_accounts_provider() -> None:
    calendars = FakeCalendars()
    source = calendars.put(event())
    router = RoutingCalendarProvider(
        StoredKinds({PERSONAL: ProviderKind.GOOGLE}), {ProviderKind.GOOGLE: calendars}
    )

    assert router.get_event(source.reference) == source


def test_an_accounts_provider_is_looked_up_once() -> None:
    kinds = StoredKinds({PERSONAL: ProviderKind.GOOGLE})
    router = RoutingCalendarProvider(kinds, {ProviderKind.GOOGLE: FakeCalendars()})

    router.get_event(event().reference)
    router.get_event(event().reference)

    assert kinds.lookups == [PERSONAL]


def test_a_request_for_an_account_that_does_not_exist_fails_like_a_provider() -> None:
    calendars = FakeCalendars()
    kinds = StoredKinds({})
    router = RoutingCalendarProvider(kinds, {ProviderKind.GOOGLE: calendars})

    with pytest.raises(ProviderFailure) as raised:
        router.get_event(event().reference)

    assert raised.value.kind is ProviderFailureKind.PERMANENT
    assert raised.value.account_id == PERSONAL
    assert calendars.reads == []
    # An account that later connects is found: only answers are kept.
    kinds.kinds[PERSONAL] = ProviderKind.GOOGLE
    assert router.get_event(event().reference) is None


def test_a_provider_this_installation_has_not_configured_stops_the_rule() -> None:
    router = RoutingCalendarProvider(StoredKinds({PERSONAL: ProviderKind.GOOGLE}), {})

    with pytest.raises(ProviderFailure) as raised:
        router.get_event(event().reference)

    assert raised.value.kind is ProviderFailureKind.PERMANENT
    assert raised.value.provider is ProviderKind.GOOGLE
    assert str(raised.value) == "Google Calendar is not configured on this installation"


def test_account_calendars_reach_the_accounts_provider() -> None:
    family = DiscoveredCalendar("family", "Family", writable=True, primary=True)
    google = Mock()
    google.calendars.return_value = (family,)
    router = RoutingAccountCalendars(
        StoredKinds({PERSONAL: ProviderKind.GOOGLE}),
        {ProviderKind.GOOGLE: cast(AccountCalendars, google)},
    )

    assert router.calendars(PERSONAL) == (family,)
    google.calendars.assert_called_once_with(PERSONAL)


def test_account_calendars_of_an_account_that_does_not_exist_are_not_found() -> None:
    router = RoutingAccountCalendars(StoredKinds({}), {})

    with pytest.raises(ConnectedAccountNotFound):
        router.calendars(PERSONAL)


def test_account_calendars_of_an_unconfigured_provider_are_unavailable() -> None:
    router = RoutingAccountCalendars(StoredKinds({PERSONAL: ProviderKind.GOOGLE}), {})

    with pytest.raises(AuthorizationNotConfigured):
        router.verify_access(PERSONAL)
```

Append to `tests/adapters/test_google_provider.py`, and import `ProviderKind` and
`ProviderFailure` if they are not imported yet:

```python
def test_google_failures_name_google_and_the_account() -> None:
    events_api = MagicMock()
    events_api.get.return_value = request_raising(500)
    provider = provider_with_events_api(events_api)

    with pytest.raises(ProviderFailure) as raised:
        provider.get_event(event().reference)

    assert raised.value.provider is ProviderKind.GOOGLE
    assert raised.value.account_id == event().reference.calendar.connected_account_id
```

Append to `tests/adapters/test_api.py`, and import `RoutingAccountCalendars` and `compose`:

```python
def test_calendars_of_a_provider_this_installation_has_not_configured_are_unavailable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    settings = Settings(database, master_key=CredentialCipher.generate_key())
    _, adapters = _installation(settings)
    assert adapters.accounts is not None
    unconfigured = replace(
        adapters, account_calendars=RoutingAccountCalendars(adapters.accounts, {})
    )
    container = replace(compose(settings, unconfigured), scheduler=None)
    _connect_accounts(database, "account-1")

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        listed = client.get("/api/v1/accounts/account-1/calendars")
        verified = client.post("/api/v1/accounts/account-1/verify")

    assert (listed.status_code, verified.status_code) == (503, 503)
    assert listed.json()["detail"] == "Google Calendar is not configured on this installation"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_provider_routing.py tests/adapters/test_google_provider.py tests/adapters/test_api.py -q -k "routing or provider or reach or unconfigured or name_google"`
Expected: FAIL with `ModuleNotFoundError: No module named 'calendar_sync.infrastructure.providers'`.

- [ ] **Step 3: Failures name their provider**

In `application/errors.py`, import `ProviderKind` and add a field to `ProviderFailure`, after
`account_id`:

```python
    provider: ProviderKind | None = None
    """The provider that failed, when the adapter names it, so incidents can (ADR 0022)."""
```

In `google/provider.py`:

- In `_failure`, return
  `replace(_provider_failure(error, self._clock.now()), account_id=account, provider=ProviderKind.GOOGLE)`.
- Add `provider=ProviderKind.GOOGLE` to every direct `ProviderFailure(...)` construction in the
  adapter's methods. To list them, run
  `rg -n 'raise ProviderFailure\(' src/calendar_sync/infrastructure/google/provider.py`.

- [ ] **Step 4: Add the routers**

`src/calendar_sync/infrastructure/providers/routing.py`:

```python
"""Sends each calendar request to the adapter of the provider its Connected Account belongs to.

A rule's source and destination may belong to different providers, so every request is routed
by the account its endpoint names (ADR 0022). An account's provider never changes, so the answer
is kept after the first lookup; an account not found is looked up again next time.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from threading import Lock
from typing import Protocol

from calendar_sync.application.errors import (
    AuthorizationNotConfigured,
    ConnectedAccountNotFound,
    ProviderFailure,
    ProviderFailureKind,
)
from calendar_sync.application.ports import (
    AccountAccess,
    AccountCalendars,
    CalendarProvider,
    CreatedProjection,
    DiscoveredCalendar,
    ProviderChangeSet,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarEvent,
    ConnectedAccountId,
    EventProjection,
    EventRef,
    OccurrenceStart,
    SyncRuleId,
    TransformationPolicy,
)


class ProviderKinds(Protocol):
    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None: ...


class _KnownKinds:
    def __init__(self, kinds: ProviderKinds) -> None:
        self._kinds = kinds
        self._known: dict[ConnectedAccountId, ProviderKind] = {}
        # Runs for different rules route on different worker threads.
        self._guard = Lock()

    def of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
        with self._guard:
            known = self._known.get(account_id)
        if known is not None:
            return known
        found = self._kinds.provider_of(account_id)
        if found is not None:
            with self._guard:
                self._known[account_id] = found
        return found


def _not_configured(kind: ProviderKind) -> str:
    return f"{kind.calendar_name} is not configured on this installation"


class RoutingCalendarProvider:
    """Every calendar role, answered by the adapter of each request's Connected Account."""

    def __init__(
        self, kinds: ProviderKinds, adapters: Mapping[ProviderKind, CalendarProvider]
    ) -> None:
        self._kinds = _KnownKinds(kinds)
        self._adapters = dict(adapters)

    def _for(self, calendar: CalendarEndpoint) -> CalendarProvider:
        account = calendar.connected_account_id
        kind = self._kinds.of(account)
        if kind is None:
            # As the Google adapter reported an account it could not find: the rule stops.
            raise ProviderFailure(
                ProviderFailureKind.PERMANENT,
                f"connected account {account.value} does not exist",
                account_id=account,
            )
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise ProviderFailure(
                ProviderFailureKind.PERMANENT,
                _not_configured(kind),
                account_id=account,
                provider=kind,
            )
        return adapter

    def changes(
        self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
    ) -> ProviderChangeSet:
        return self._for(source).changes(source, cursor, not_ended_before)

    def get_event(self, reference: EventRef) -> CalendarEvent | None:
        return self._for(reference.calendar).get_event(reference)

    def find_projection(
        self, destination: CalendarEndpoint, operation_key: str
    ) -> CalendarEvent | None:
        return self._for(destination).find_projection(destination, operation_key)

    def list_events(
        self, calendar: CalendarEndpoint, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        return self._for(calendar).list_events(calendar, not_ended_before)

    def managed_events(
        self, destination: CalendarEndpoint, rule_id: SyncRuleId, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        return self._for(destination).managed_events(destination, rule_id, not_ended_before)

    def get_occurrence(
        self, series: EventRef, original_start: OccurrenceStart
    ) -> CalendarEvent | None:
        return self._for(series.calendar).get_occurrence(series, original_start)

    def list_occurrences(
        self, series: EventRef, original_starts: Collection[OccurrenceStart]
    ) -> Mapping[OccurrenceStart, CalendarEvent]:
        return self._for(series.calendar).list_occurrences(series, original_starts)

    def has_live_occurrences(self, series: EventRef, policy: TransformationPolicy) -> bool:
        return self._for(series.calendar).has_live_occurrences(series, policy)

    def occurrence_exceptions(
        self, series: EventRef, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        return self._for(series.calendar).occurrence_exceptions(series, not_ended_before)

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection:
        return self._for(destination).create_projection(
            destination, source, rule_id, projection, operation_key
        )

    def update_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        return self._for(destination.calendar).update_projection(
            destination, source, rule_id, projection, operation_key
        )

    def delete_projection(
        self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
    ) -> None:
        self._for(destination.calendar).delete_projection(
            destination, source, rule_id, operation_key
        )

    def write_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        return self._for(destination_series.calendar).write_occurrence(
            destination_series, original_start, source_series, rule_id, projection, operation_key
        )

    def cancel_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        self._for(destination_series.calendar).cancel_occurrence(
            destination_series, original_start, source_series, rule_id, operation_key
        )


class RoutingAccountCalendars:
    """Calendar discovery and access checks, answered by each account's provider."""

    def __init__(
        self, kinds: ProviderKinds, adapters: Mapping[ProviderKind, AccountCalendars]
    ) -> None:
        self._kinds = _KnownKinds(kinds)
        self._adapters = dict(adapters)

    def _for(self, account_id: ConnectedAccountId) -> AccountCalendars:
        kind = self._kinds.of(account_id)
        if kind is None:
            raise ConnectedAccountNotFound(f"connected account {account_id.value} does not exist")
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise AuthorizationNotConfigured(_not_configured(kind))
        return adapter

    def calendars(self, account_id: ConnectedAccountId) -> Sequence[DiscoveredCalendar]:
        return self._for(account_id).calendars(account_id)

    def verify_access(self, account_id: ConnectedAccountId) -> AccountAccess:
        return self._for(account_id).verify_access(account_id)
```

- [ ] **Step 5: Compose the routers**

In `bootstrap/container.py`:

- Import `AccountCalendars`, `ProviderKind`, `RoutingAccountCalendars`, and
  `RoutingCalendarProvider`.
- Add to `Adapters`, after `google_oauth`:

```python
    account_calendars: AccountCalendars | None = None
    """Lists each account's calendars through its provider's adapter."""
```

- In `build_adapters`, return:

```python
    return replace(
        adapters,
        accounts=accounts,
        google_oauth=google_oauth,
        account_calendars=RoutingAccountCalendars(accounts, {ProviderKind.GOOGLE: google_oauth}),
        calendar_provider=RoutingCalendarProvider(
            accounts,
            {ProviderKind.GOOGLE: GoogleCalendarProvider(google_oauth.service_for, clock)},
        ),
        call_stats=ContextProviderCallStats(),
        notifications=_notifier(settings),
    )
```

- In `compose`, set `account_calendars=adapters.account_calendars` and:

```python
        discover_calendars=(
            DiscoverCalendars(adapters.account_calendars, unit_of_work)
            if adapters.account_calendars
            else None
        ),
```

In `routes/accounts.py`, add this clause to the `try` blocks in both `discover_calendars` and
`verify_account_access`:

```python
    except AuthorizationNotConfigured as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
```

In `tests/adapters/test_api.py`, two tests verify access for `account-1` without creating it:
`test_connected_account_access_can_be_verified` and
`test_connected_account_access_failures_are_mapped_to_recovery_statuses`. In each, call
`_connect_accounts(tmp_path / "test.db", "account-1")` before opening the client. The router now
needs the account to exist, as the Google adapter already did once it read credentials.

- [ ] **Step 6: Document the routing**

In `docs/architecture.md` under **Calendar provider roles**, replace "The Google adapter
implements every role." with:

```markdown
Each provider's adapter implements every role it can honor. `RoutingCalendarProvider` and
`RoutingAccountCalendars` in `infrastructure/providers/routing.py` implement the same ports and
send each request to the adapter of the Provider Kind its Connected Account belongs to, so a rule's
calendars may belong to different providers (ADR 0022). The use cases receive the routers and
never name a provider.
```

In the authorization paragraph, change "`infrastructure/google/oauth.py` holds only the
state-protected OAuth flow" to "`infrastructure/google/oauth.py` holds the state-protected OAuth
flow, Google credentials, and Google calendar discovery".

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/pytest -q && .venv/bin/mypy && .venv/bin/lint-imports`
Expected: PASS. mypy proves both routers satisfy their ports through the typed `Adapters` fields.

- [ ] **Step 8: Commit**

```bash
git add -A src/calendar_sync tests docs
git commit -m "feat: route calendar requests by each account's provider

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Messages name the provider instead of assuming Google

**Files:**
- Modify: `src/calendar_sync/application/health.py` (`_FAILURE_SUMMARIES`,
  `RuleHealthPolicy.summary`)
- Modify: `src/calendar_sync/application/errors.py`, `src/calendar_sync/application/rules.py`,
  `src/calendar_sync/application/accounts.py`, `src/calendar_sync/application/removal.py`,
  `src/calendar_sync/infrastructure/persistence/accounts.py`
- Modify: `src/calendar_sync/interfaces/api/routes/accounts.py`, `routes/rules.py`,
  `routes/activity.py`
- Modify: `tests/application/test_health.py`, `tests/adapters/test_scheduling.py`,
  `tests/adapters/test_api.py`
- Modify: `docs/troubleshooting.md`

**Interfaces:**
- Consumes: `ProviderFailure.provider` (Task 5) and `ProviderKind.calendar_name` (Task 2).
- Produces:
  - `RuleHealthPolicy.summary(failure: ProviderFailure) -> str`, which replaces
    `summary(kind)`.
  - `ProviderFailure.provider_name -> str`.

- [ ] **Step 1: Write the failing tests**

In `tests/application/test_health.py`, import `ProviderKind` and add:

```python
@pytest.mark.parametrize(
    ("kind", "summary"),
    [
        (ProviderFailureKind.AUTHENTICATION, "Authorization for Google Calendar expired"),
        (ProviderFailureKind.AUTHORIZATION, "Access to Google Calendar was denied"),
        (ProviderFailureKind.RATE_LIMIT, "Google Calendar is limiting requests"),
        (ProviderFailureKind.TEMPORARY, "Google Calendar is temporarily unavailable"),
        (ProviderFailureKind.PERMANENT, "Google Calendar rejected synchronization"),
        (ProviderFailureKind.INFRASTRUCTURE, "Local synchronization infrastructure failed"),
    ],
)
def test_incident_summaries_name_the_provider_that_failed(
    kind: ProviderFailureKind, summary: str
) -> None:
    failure = ProviderFailure(kind, "synthetic", provider=ProviderKind.GOOGLE)

    assert RuleHealthPolicy.summary(failure) == summary


def test_a_failure_naming_no_provider_is_summarized_without_one() -> None:
    assert (
        RuleHealthPolicy.summary(_failure(ProviderFailureKind.RATE_LIMIT))
        == "The calendar provider is limiting requests"
    )
```

Update the existing assertions:

- `test_health.py`:
  - In `test_failures_requiring_intervention_degrade_and_open_an_incident_at_once`, use
    `RuleHealthPolicy.summary(failure)`.
  - In `test_a_blocked_removal_names_its_cause`, expect
    `"Rule Removal stopped: Access to the calendar provider was denied"`.
- `test_scheduling.py`:
  - Expect `"The calendar provider is temporarily unavailable"` where it expects
    `"Google Calendar is temporarily unavailable"`.
  - Expect `"Rule Removal stopped: Access to the calendar provider was denied"` where it expects
    the Google wording.
- `test_api.py`: in the rule-creation refusal, expect
  `"connect both accounts before creating a rule"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/application/test_health.py tests/adapters/test_scheduling.py -q`
Expected: FAIL. `summary` still takes a kind, and the summaries still name Google.

- [ ] **Step 3: Summaries name the failure's provider**

In `application/errors.py`, add to `ProviderFailure`:

```python
    @property
    def provider_name(self) -> str:
        """How messages name the failed provider: "Google Calendar", or a neutral phrase."""
        return self.provider.calendar_name if self.provider else "the calendar provider"
```

In `application/health.py`:

```python
_FAILURE_SUMMARIES = {
    ProviderFailureKind.AUTHENTICATION: "Authorization for {calendar} expired",
    ProviderFailureKind.AUTHORIZATION: "Access to {calendar} was denied",
    ProviderFailureKind.RATE_LIMIT: "{Calendar} is limiting requests",
    ProviderFailureKind.TEMPORARY: "{Calendar} is temporarily unavailable",
    ProviderFailureKind.PERMANENT: "{Calendar} rejected synchronization",
    ProviderFailureKind.INFRASTRUCTURE: "Local synchronization infrastructure failed",
}
```

```python
    @staticmethod
    def summary(failure: ProviderFailure) -> str:
        """What failed, naming the provider when the failure says which one (ADR 0022)."""
        calendar = failure.provider_name
        return _FAILURE_SUMMARIES[failure.kind].format(
            calendar=calendar, Calendar=calendar[0].upper() + calendar[1:]
        )
```

In `provider_incident` and `removal_blocked`, call `self.summary(failure)`.

- [ ] **Step 4: Make the remaining messages provider-neutral**

| File | From | To |
| --- | --- | --- |
| `application/errors.py` `RemovalRequiresProvider` docstring | `needs a configured Google adapter` | `needs a configured calendar provider` |
| `application/errors.py` `RemovalInterrupted.__str__` | `because Google "` | `because the calendar provider "` |
| `application/rules.py` | `connect both Google accounts before creating a rule` | `connect both accounts before creating a rule` |
| `application/accounts.py` | `disconnect this Google account before deleting it permanently` | `disconnect this account before deleting it permanently` |
| `application/removal.py` | `configure Google OAuth and the installation master key before ` | `configure a calendar provider and the installation master key before ` |
| `infrastructure/persistence/accounts.py` | `this Google account is disconnected; reauthorize it from Settings` | `this account is disconnected; reauthorize it from Settings` |
| `routes/accounts.py` (`discover_calendars`, `verify_account_access`) | `Google OAuth is not configured` | `no calendar provider is configured` |
| `routes/accounts.py` `MANAGE_ACCOUNTS` | `before managing Google accounts` | `before managing accounts` |
| `routes/rules.py` (three messages) | `configure Google OAuth and the installation master key before` | `configure a calendar provider and the installation master key before` |
| `routes/activity.py` | `configure Google OAuth and the installation master key before inspecting events` | `configure a calendar provider and the installation master key before inspecting events` |
| `routes/activity.py` | `f"Google could not return this event: {error.kind.value}"` | `f"Could not read this event from {error.provider_name}: {error.kind.value}"` |

Re-wrap any string that now exceeds the line limit; `ruff check` reports it. Leave unchanged
the messages of the Google-only routes (`start_google_oauth`,
`complete_google_oauth`) and the Google adapter's own details.

In `docs/troubleshooting.md`:

- Line 134: replace "Rule Removal stopped: Google authorization expired** or **… calendar access
  was denied" with "Rule Removal stopped: Authorization for Google Calendar expired** or **Access
  to Google Calendar was denied".
- Line 162: replace "**Google authorization expired** or **Google calendar access was denied**"
  with "**Authorization for Google Calendar expired** or **Access to Google Calendar was
  denied**".

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest -q && .venv/bin/mypy`
Expected: PASS. If a test still asserts an old message from the table above, update it to the
new message. Any other failure is a regression.

- [ ] **Step 6: Commit**

```bash
git add -A src/calendar_sync tests docs
git commit -m "refactor: name the failed provider instead of assuming Google

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The Calendar Provider contract

**Files:**
- Create: `tests/contracts/__init__.py` (empty) and `tests/contracts/calendar_provider.py`
- Create: `tests/adapters/test_calendar_provider_contract.py`
- Modify: `src/calendar_sync/infrastructure/google/provider.py` (`update_projection` refusal)
- Modify: `tests/adapters/test_google_provider.py`
- Modify: `docs/architecture.md`, `docs/development.md`

**Interfaces:**
- Consumes: `RoutingCalendarProvider` from Task 5.
- Produces:
  - `ProviderHarness(provider: CalendarProvider, seed: Callable[[CalendarEvent], object])`.
  - `CalendarProviderContract`, a test base class whose subclasses override the `harness` fixture.

- [ ] **Step 1: Write the contract suite**

`tests/contracts/calendar_provider.py`:

```python
"""What every Calendar Provider adapter must honor, asked only through the provider ports.

An adapter passes this suite before it is composed (ADR 0022). A subclass supplies a harness
that can place a Native Event in its backend, as the calendar's owner would.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

import pytest

from calendar_sync.application.errors import ProjectionOwnershipMismatch
from calendar_sync.application.ports import CalendarProvider
from calendar_sync.domain.model import (
    CalendarEvent,
    EventId,
    EventProjection,
    EventRef,
    EventStatus,
    ManagedOrigin,
    SyncRuleId,
    TimedInterval,
)
from tests.helpers import NOW, endpoint, event

SOURCE = endpoint("personal-account", "personal-calendar")
DESTINATION = endpoint("work-account", "work-calendar")
RULE_ID = SyncRuleId("rule-1")
OTHER_RULE_ID = SyncRuleId("rule-2")
WINDOW_START = NOW - timedelta(days=1)


@dataclass(frozen=True, slots=True)
class ProviderHarness:
    provider: CalendarProvider
    seed: Callable[[CalendarEvent], object]
    """Place a Native Event in the provider, as the calendar's owner would create it."""


def _projection(title: str = "Busy") -> EventProjection:
    return EventProjection(time=TimedInterval(NOW, NOW + timedelta(hours=1)), title=title)


def _create(
    harness: ProviderHarness, key: str, rule_id: SyncRuleId = RULE_ID, source_id: str = "source"
) -> CalendarEvent:
    source = event(source_id, calendar=SOURCE).reference
    created = harness.provider.create_projection(DESTINATION, source, rule_id, _projection(), key)
    return created.destination_event


class CalendarProviderContract:
    @pytest.fixture
    def harness(self) -> ProviderHarness:
        raise NotImplementedError

    def test_a_created_projection_reads_back_owned_by_its_rule_and_source(
        self, harness: ProviderHarness
    ) -> None:
        created = _create(harness, "key-1")

        found = harness.provider.get_event(created.reference)

        assert found is not None
        assert found.status is EventStatus.CONFIRMED
        assert found.title == "Busy"
        assert found.managed_origin == ManagedOrigin(
            RULE_ID, event("source", calendar=SOURCE).reference
        )

    def test_one_operation_key_creates_one_projection(self, harness: ProviderHarness) -> None:
        first = _create(harness, "key-1")
        second = _create(harness, "key-1")

        listed = harness.provider.managed_events(DESTINATION, RULE_ID, WINDOW_START)

        assert second.reference == first.reference
        assert [projection.reference for projection in listed] == [first.reference]

    def test_only_a_known_operation_key_finds_a_projection(
        self, harness: ProviderHarness
    ) -> None:
        created = _create(harness, "key-1")

        found = harness.provider.find_projection(DESTINATION, "key-1")

        assert found is not None
        assert found.reference == created.reference
        assert harness.provider.find_projection(DESTINATION, "key-never-used") is None

    def test_managed_events_list_only_this_rules_projections(
        self, harness: ProviderHarness
    ) -> None:
        harness.seed(event("native-event", calendar=DESTINATION))
        mine = _create(harness, "key-1")
        _create(harness, "key-2", OTHER_RULE_ID, "other-source")

        listed = harness.provider.managed_events(DESTINATION, RULE_ID, WINDOW_START)

        assert [projection.reference for projection in listed] == [mine.reference]

    def test_an_event_that_never_existed_reads_as_none(self, harness: ProviderHarness) -> None:
        missing = EventRef(DESTINATION, EventId("never-existed"))

        assert harness.provider.get_event(missing) is None

    def test_deleting_a_projection_twice_is_quiet(self, harness: ProviderHarness) -> None:
        created = _create(harness, "key-1")
        source = event("source", calendar=SOURCE).reference

        harness.provider.delete_projection(created.reference, source, RULE_ID, "key-delete")
        harness.provider.delete_projection(created.reference, source, RULE_ID, "key-delete")

        found = harness.provider.get_event(created.reference)
        assert found is None or found.status is EventStatus.CANCELLED

    def test_another_rules_projection_is_never_updated_or_deleted(
        self, harness: ProviderHarness
    ) -> None:
        theirs = _create(harness, "key-1", OTHER_RULE_ID)
        source = event("source", calendar=SOURCE).reference

        with pytest.raises(ProjectionOwnershipMismatch):
            harness.provider.update_projection(
                theirs.reference, source, RULE_ID, _projection("Changed"), "key-update"
            )
        with pytest.raises(ProjectionOwnershipMismatch):
            harness.provider.delete_projection(theirs.reference, source, RULE_ID, "key-delete")

        found = harness.provider.get_event(theirs.reference)
        assert found is not None
        assert found.title == "Busy"

    def test_a_full_listing_reports_native_events_without_a_managed_origin(
        self, harness: ProviderHarness
    ) -> None:
        native = event("native-event", calendar=SOURCE)
        harness.seed(native)

        listing = harness.provider.changes(SOURCE, None, WINDOW_START)

        reported = {item.reference: item for item in listing.events}
        assert listing.complete
        assert listing.next_cursor
        assert native.reference in reported
        assert reported[native.reference].managed_origin is None
```

`tests/adapters/test_calendar_provider_contract.py`:

```python
"""The test fake and the router honor the Calendar Provider contract (ADR 0022)."""

import pytest

from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.providers.routing import RoutingCalendarProvider
from tests.contracts.calendar_provider import CalendarProviderContract, ProviderHarness
from tests.fake_calendar import FakeCalendars


class AllGoogle:
    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
        return ProviderKind.GOOGLE


class TestFakeCalendars(CalendarProviderContract):
    @pytest.fixture
    def harness(self) -> ProviderHarness:
        calendars = FakeCalendars()
        return ProviderHarness(calendars, calendars.put)


class TestRoutingCalendarProvider(CalendarProviderContract):
    @pytest.fixture
    def harness(self) -> ProviderHarness:
        calendars = FakeCalendars()
        router = RoutingCalendarProvider(AllGoogle(), {ProviderKind.GOOGLE: calendars})
        return ProviderHarness(router, calendars.put)
```

- [ ] **Step 2: Run the contract**

Run: `.venv/bin/pytest tests/adapters/test_calendar_provider_contract.py -q`
Expected: PASS, 16 tests. Both the fake and the router already honor the contract. A failure here
means the fake or the router has drifted from the ports. Fix the fake or the router, not the
contract.

- [ ] **Step 3: Write the failing Google test for the drift the contract exposes**

The contract requires an update refused for ownership to raise `ProjectionOwnershipMismatch`.
Google's `update_projection` raises a plain `ProviderFailure`; its `delete_projection` already
raises the subclass. Append to `tests/adapters/test_google_provider.py`, and import
`EventProjection`, `TimedInterval`, `EventRef`, `EventId`, `NOW`, and `rule` if they are not
imported yet:

```python
def test_google_refuses_to_update_a_projection_this_rule_does_not_own() -> None:
    events_api = MagicMock()
    events_api.get.return_value = request_returning(google_event_payload("projection-1"))
    provider = provider_with_events_api(events_api)
    destination = EventRef(rule().destination, EventId("projection-1"))
    projection = EventProjection(time=TimedInterval(NOW, NOW + timedelta(hours=1)), title="Busy")

    with pytest.raises(ProjectionOwnershipMismatch):
        provider.update_projection(
            destination, event().reference, rule().id, projection, "key-update"
        )

    events_api.update.assert_not_called()
```

Run: `.venv/bin/pytest tests/adapters/test_google_provider.py -q -k "does_not_own"`
Expected: FAIL. `ProviderFailure` is raised, not `ProjectionOwnershipMismatch`.

- [ ] **Step 4: Raise the ownership refusal the contract requires**

In `google/provider.py` `update_projection`, replace the `raise ProviderFailure(...)` for
incompatible ownership with:

```python
            raise ProjectionOwnershipMismatch(
                "Google event does not carry compatible ownership metadata"
            )
```

`ProjectionOwnershipMismatch` subclasses `ProviderFailure` with the same `PERMANENT` kind, so Sync
Run handling does not change.

- [ ] **Step 5: Document the contract**

- In `docs/architecture.md`, after the routing paragraph added in Task 5, add: "Every adapter, and
  the test fake, passes the Calendar Provider contract in `tests/contracts/calendar_provider.py`
  before it is composed. The contract states, through the ports alone, the ownership,
  idempotency, and listing guarantees the use cases rely on."
- In `docs/development.md`, in its testing section, add: "A new calendar adapter adds a
  `CalendarProviderContract` subclass whose harness seeds Native Events in that adapter's backend,
  next to `tests/adapters/test_calendar_provider_contract.py`."

- [ ] **Step 6: Run every gate**

Run:

```sh
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/lint-imports \
  && .venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A src/calendar_sync tests docs
git commit -m "test: add the Calendar Provider contract and align Google's ownership refusal

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
