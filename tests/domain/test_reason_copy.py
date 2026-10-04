from pathlib import Path

from calendar_sync.domain.model import SyncReason

# The Activity copy for every reason, in the Web UI module that holds the reason tables.
REASON_COPY = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "activity-reasons.ts"


def test_every_sync_reason_has_activity_copy() -> None:
    source = REASON_COPY.read_text()

    missing = [reason.value for reason in SyncReason if f"  {reason.value}: {{" not in source]

    assert missing == []
