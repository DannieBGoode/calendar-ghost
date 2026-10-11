"""Errors of Activity and storage."""

from __future__ import annotations

from calendar_sync.application.shared.errors import ApplicationError


class ActivityEventNotFound(ApplicationError):
    """The Activity entry does not exist or names no source event."""


class ActivityRuleRemoved(ApplicationError):
    """The Activity entry's rule was removed, so its calendars are no longer known."""


class EventInspectionUnavailable(ApplicationError):
    """Events cannot be read live without a configured calendar provider."""


class InvalidActivityAge(ApplicationError):
    """Activity can be cleared only from one of the offered ages."""


STORAGE_BUSY_MESSAGE = (
    "Old Activity was cleared, but its space could not be reclaimed while a rule is "
    "synchronizing. Try again when it finishes."
)


class StorageBusy(ApplicationError):
    """Rule work kept the database from being compacted.

    Raised by the storage use case when a rule's lock cannot be acquired before its deadline, and
    by the SQLite adapter when `VACUUM` itself reports the database is locked -- a database user
    rule locks do not cover, such as a lifecycle change, Activity read, or health write.
    """


class FileLoggingOff(ApplicationError):
    """The installation keeps no log files to read or purge."""
