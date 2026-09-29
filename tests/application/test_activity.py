import pytest

from calendar_sync.application.activity import ActivityCategory, activity_category
from calendar_sync.domain.model import SyncReason


@pytest.mark.parametrize(
    ("action", "reason", "category"),
    [
        ("create", "source_created", "changed"),
        ("update", "source_changed", "changed"),
        ("delete", "source_cancelled", "changed"),
        ("policy_changed", None, "changed"),
        ("rule_removed", None, "changed"),
        ("remove_projection", None, "changed"),
        ("detach_projection", None, "changed"),
        ("ignore", "projection_current", "unchanged"),
        ("ignore", "occurrence_current", "unchanged"),
        ("ignore", "occurrence_already_cancelled", "unchanged"),
        ("ignore", "all_day_excluded", "skipped"),
        ("ignore", None, "skipped"),
        ("conflict", "destination_occurrence_missing", "blocked"),
        ("conflict", None, "blocked"),
        ("removal_conflict", None, "blocked"),
    ],
)
def test_activity_category_groups_each_decision(
    action: str, reason: str | None, category: ActivityCategory
) -> None:
    assert activity_category(action, reason) == category


def test_recurring_exclusions_recorded_as_conflicts_are_skips() -> None:
    # Recorded before reason codes existed; the event was never synchronized, not blocked.
    assert activity_category("conflict", SyncReason.RECURRING_UNSUPPORTED.value) == "skipped"
    assert activity_category("ignore", SyncReason.RECURRING_UNSUPPORTED.value) == "skipped"
