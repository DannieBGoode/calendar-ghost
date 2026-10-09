"""SQLite keeps Source Observations and Source Change values sealed (ADR 0017)."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from calendar_sync.application.ports import AuditAction, AuditEntry, AuditOutcome, UnitOfWorkFactory
from calendar_sync.domain.changes import SourceChange, SourceObservation
from calendar_sync.domain.model import (
    AllDayRange,
    EventId,
    EventRef,
    InvitationResponse,
    Recurrence,
    SyncReason,
    TimedInterval,
)
from calendar_sync.infrastructure.persistence.source_changes import open_change_values
from calendar_sync.infrastructure.persistence.sqlite import (
    initialize_database,
)
from calendar_sync.infrastructure.security import CredentialCipher, HistoryCipher
from tests.fake_calendar import FakeCalendars, sync_use_case
from tests.helpers import NOW, endpoint, event, rule
from tests.users import sqlite_units

HISTORY = HistoryCipher(CredentialCipher.generate_key())


def _factory(tmp_path: Path, history: HistoryCipher | None = HISTORY) -> UnitOfWorkFactory:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = sqlite_units(database, history=history)
    with factory() as uow:
        uow.rules.add(rule())
        uow.commit()
    return factory


def _observation(**changes: object) -> SourceObservation:
    source = replace(
        event(),
        guests=("ana@example.com", "ben@example.com"),
        conferencing=("tel:+34-900-000-000,,1234#",),
        recurrence=Recurrence(("RRULE:FREQ=WEEKLY",)),
    )
    observation = SourceObservation.of(source)
    assert observation is not None
    return replace(observation, **changes)  # type: ignore[arg-type]


def _database_bytes(tmp_path: Path) -> bytes:
    return (tmp_path / "calendar-sync.db").read_bytes()


def test_an_observation_round_trips_and_is_sealed_at_rest(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    observation = _observation()

    with factory() as uow:
        uow.observations.save(rule().id, event().reference, observation, NOW)
        uow.commit()
    with factory() as uow:
        restored = uow.observations.get(rule().id, event().reference)

    assert restored == observation
    stored = _database_bytes(tmp_path)
    assert b"Sensitive description" not in stored
    assert b"ben@example.com" not in stored
    assert b"1234#" not in stored


def test_a_response_round_trips_and_one_sealed_before_it_was_tracked_reads_as_unknown(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    maybe = _observation(response=InvitationResponse.TENTATIVE)
    with factory() as uow:
        uow.observations.save(rule().id, event().reference, maybe, NOW)
        uow.commit()
    with factory() as uow:
        assert uow.observations.get(rule().id, event().reference) == maybe
    context = "observation|" + "|".join(
        (rule().id.value, "personal-account", "personal-calendar", "source-event")
    )
    details: dict[str, object] = {
        "time": {
            "all_day": False,
            "starts": NOW.isoformat(),
            "ends": (NOW + timedelta(hours=1)).isoformat(),
        },
        "description": "",
        "location": "",
        "recurrence": [],
        "guests": None,
        "conferencing": None,
    }
    with sqlite3.connect(tmp_path / "calendar-sync.db") as connection:
        connection.execute(
            "UPDATE source_observations SET sealed = ?",
            (HISTORY.seal(json.dumps(details), context),),
        )

    with factory() as uow:
        earlier = uow.observations.get(rule().id, event().reference)

    assert earlier is not None
    assert earlier.response is None


def test_an_all_day_observation_round_trips(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    observation = _observation(time=AllDayRange(date(2026, 8, 30), date(2026, 8, 31)))

    with factory() as uow:
        uow.observations.save(rule().id, event().reference, observation, NOW)
        uow.commit()
    with factory() as uow:
        assert uow.observations.get(rule().id, event().reference) == observation


def test_an_observation_sealed_under_another_key_reads_as_unobserved(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as uow:
        uow.observations.save(rule().id, event().reference, _observation(), NOW)
        uow.commit()
    other = sqlite_units(
        tmp_path / "calendar-sync.db", history=HistoryCipher(CredentialCipher.generate_key())
    )

    with other() as uow:
        assert uow.observations.get(rule().id, event().reference) is None


def test_without_a_master_key_nothing_is_observed(tmp_path: Path) -> None:
    factory = _factory(tmp_path, history=None)

    with factory() as uow:
        uow.observations.save(rule().id, event().reference, _observation(), NOW)
        uow.commit()
    with factory() as uow:
        assert uow.observations.get(rule().id, event().reference) is None


def _entry(change: SourceChange | None) -> AuditEntry:
    return AuditEntry(
        occurred_at=NOW,
        rule_id=rule().id,
        action=AuditAction.UPDATE,
        outcome=AuditOutcome.COMPLETED,
        source_event_id=event().reference.event_id.value,
        reason=SyncReason.SOURCE_CHANGED,
        run_id="run-1",
        change=change,
    )


def _change() -> SourceChange:
    later = TimedInterval(NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    change = SourceChange.between(
        _observation(),
        _observation(
            revision="revision-2",
            title="Renamed",
            time=later,
            description="Dial in: 1234#",
            guests=("ana@example.com", "cleo@example.com"),
        ),
    )
    assert change is not None
    return change


def _audit_row(tmp_path: Path) -> sqlite3.Row:
    with sqlite3.connect(tmp_path / "calendar-sync.db") as connection:
        connection.row_factory = sqlite3.Row
        row: sqlite3.Row = connection.execute(
            "SELECT id, rule_id, source_event_id, change_fields, change_title_before, change_sealed"
            " FROM audit_entries"
        ).fetchone()
        return row


def test_a_change_keeps_its_fields_and_previous_title_plain_and_seals_the_rest(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)

    with factory() as uow:
        uow.audit.append(_entry(_change()))
        uow.commit()

    row = _audit_row(tmp_path)
    assert json.loads(row["change_fields"]) == ["title", "time", "description", "guests"]
    assert row["change_title_before"] == "Private appointment"
    assert b"1234#" not in _database_bytes(tmp_path)
    values = open_change_values(HISTORY, row)
    assert values is not None
    assert values["description"] == {"before": "Sensitive description", "after": "Dial in: 1234#"}
    assert values["guests"] == {"added": ["cleo@example.com"], "removed": ["ben@example.com"]}
    assert values["time"]["after"]["starts"] == (NOW + timedelta(hours=1)).isoformat()
    assert "title" not in values


def test_an_entry_without_a_change_records_none(tmp_path: Path) -> None:
    factory = _factory(tmp_path)

    with factory() as uow:
        uow.audit.append(_entry(None))
        uow.commit()

    row = _audit_row(tmp_path)
    assert row["change_fields"] is None
    assert row["change_sealed"] is None


def test_without_a_master_key_a_change_keeps_only_its_fields_and_title(tmp_path: Path) -> None:
    factory = _factory(tmp_path, history=None)

    with factory() as uow:
        uow.audit.append(_entry(_change()))
        uow.commit()

    row = _audit_row(tmp_path)
    assert row["change_title_before"] == "Private appointment"
    assert row["change_sealed"] is None


def test_change_values_older_than_the_cutoff_are_forgotten(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as uow:
        uow.audit.append(_entry(_change()))
        uow.commit()

    with factory() as uow:
        uow.audit.forget_change_values(NOW)
        uow.commit()
    assert _audit_row(tmp_path)["change_sealed"] is not None
    with factory() as uow:
        uow.audit.forget_change_values(NOW + timedelta(seconds=1))
        uow.commit()

    row = _audit_row(tmp_path)
    assert row["change_sealed"] is None
    assert json.loads(row["change_fields"]) == ["title", "time", "description", "guests"]
    assert open_change_values(HISTORY, row) is None


def test_stale_observations_are_forgotten_and_series_kept(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    ended = EventRef(rule().source, EventId("ended"))
    elsewhere = EventRef(endpoint("personal-account", "old-calendar"), EventId("elsewhere"))
    past = TimedInterval(NOW - timedelta(days=100), NOW - timedelta(days=100, hours=-1))
    with factory() as uow:
        uow.observations.save(rule().id, event().reference, _observation(recurrence=()), NOW)
        uow.observations.save(rule().id, ended, _observation(recurrence=(), time=past), NOW)
        uow.observations.save(
            rule().id, EventRef(rule().source, EventId("series")), _observation(time=past), NOW
        )
        uow.observations.save(rule().id, elsewhere, _observation(recurrence=()), NOW)
        uow.commit()

    with factory() as uow:
        uow.observations.forget_stale(rule().id, rule().source, NOW - timedelta(days=90))
        uow.commit()

    with factory() as uow:
        assert uow.observations.get(rule().id, event().reference) is not None
        assert uow.observations.get(rule().id, ended) is None
        assert (
            uow.observations.get(rule().id, EventRef(rule().source, EventId("series"))) is not None
        )
        assert uow.observations.get(rule().id, elsewhere) is None


def test_removing_a_rule_removes_its_observations(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as uow:
        uow.observations.save(rule().id, event().reference, _observation(), NOW)
        uow.commit()

    with factory() as uow:
        uow.rules.remove(rule().id)
        uow.commit()

    with sqlite3.connect(tmp_path / "calendar-sync.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_observations").fetchone()[0] == 0


def test_change_values_of_a_removed_rule_are_forgotten_too(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as uow:
        uow.audit.append(_entry(_change()))
        uow.rules.remove(rule().id)
        uow.commit()

    with factory() as uow:
        uow.audit.forget_change_values(NOW + timedelta(seconds=1))
        uow.commit()

    assert _audit_row(tmp_path)["change_sealed"] is None


def test_a_sync_run_records_a_busy_only_rename_in_sqlite_without_a_write(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    details = {"guests": ("ana@example.com",), "conferencing": ()}
    calendars = FakeCalendars()
    calendars.put(replace(event(), **details))  # type: ignore[arg-type]
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    writes = len(calendars.writes)
    renamed = replace(event(), revision="revision-2", title="Renamed", **details)  # type: ignore[arg-type]
    calendars.report(calendars.put(renamed))

    sync.execute(rule().id)

    assert calendars.writes[writes:] == []
    with sqlite3.connect(tmp_path / "calendar-sync.db") as connection:
        reason, fields, title_before = connection.execute(
            "SELECT reason, change_fields, change_title_before FROM audit_entries"
            " ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert (reason, json.loads(fields), title_before) == (
        "projection_current",
        ["title"],
        "Private appointment",
    )
    with factory() as uow:
        mapping = uow.mappings.for_source(rule().id, event().reference)
    assert mapping is not None
    assert mapping.source_revision == "revision-2"


def test_answering_a_maybe_event_rewrites_it_and_records_the_response(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    calendars = FakeCalendars()
    calendars.put(replace(event(), response=InvitationResponse.TENTATIVE))
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    with factory() as uow:
        mapping = uow.mappings.for_source(rule().id, event().reference)
    assert mapping is not None
    assert calendars.events[mapping.destination].title == "Busy (tentative)"

    accepted = replace(event(), revision="revision-2", response=InvitationResponse.ACCEPTED)
    calendars.report(calendars.put(accepted))
    sync.execute(rule().id)

    assert calendars.events[mapping.destination].title == "Busy"
    row = _latest_entry(tmp_path)
    assert (row["reason"], json.loads(row["change_fields"])) == ("source_changed", ["response"])
    assert open_change_values(HISTORY, row) == {
        "response": {"before": "tentative", "after": "accepted"}
    }

    declined = replace(event(), revision="revision-3", response=InvitationResponse.DECLINED)
    calendars.report(calendars.put(declined))
    sync.execute(rule().id)

    assert mapping.destination not in calendars.events
    assert _latest_entry(tmp_path)["reason"] == "declined_removed"


def _latest_entry(tmp_path: Path) -> sqlite3.Row:
    with sqlite3.connect(tmp_path / "calendar-sync.db") as connection:
        connection.row_factory = sqlite3.Row
        row: sqlite3.Row = connection.execute(
            "SELECT * FROM audit_entries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row
