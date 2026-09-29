import pytest

from calendar_sync.application.ports import AuditAction, AuditOutcome
from calendar_sync.domain.model import SyncAction


def test_stored_audit_values_are_unchanged() -> None:
    # Activity queries and existing databases match these exact strings.
    assert {action.value for action in AuditAction} == {
        "create",
        "update",
        "delete",
        "ignore",
        "conflict",
        "policy_changed",
        "remove_projection",
        "detach_projection",
        "removal_conflict",
        "rule_removed",
    }
    assert {outcome.value for outcome in AuditOutcome} == {"completed", "skipped", "blocked"}


@pytest.mark.parametrize("action", list(SyncAction))
def test_every_sync_decision_records_its_own_action(action: SyncAction) -> None:
    assert AuditAction.of(action).value == action.value


@pytest.mark.parametrize(
    ("action", "outcome"),
    [
        (SyncAction.CREATE, AuditOutcome.COMPLETED),
        (SyncAction.UPDATE, AuditOutcome.COMPLETED),
        (SyncAction.DELETE, AuditOutcome.COMPLETED),
        (SyncAction.IGNORE, AuditOutcome.SKIPPED),
        (SyncAction.CONFLICT, AuditOutcome.BLOCKED),
    ],
)
def test_a_sync_decision_records_its_outcome(action: SyncAction, outcome: AuditOutcome) -> None:
    assert AuditOutcome.of(action) is outcome
