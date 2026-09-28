from pathlib import Path

from calendar_sync.domain.model import SyncReason

ACTIVITY = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "activity.ts"


def test_every_sync_reason_has_activity_copy() -> None:
    source = ACTIVITY.read_text()

    missing = [reason.value for reason in SyncReason if f"  {reason.value}: {{" not in source]

    assert missing == []
