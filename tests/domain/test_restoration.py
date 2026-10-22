"""Conservative restoration never inherits authority from a backup."""

from dataclasses import replace

import pytest

from calendar_sync.domain.access import RegistrationPolicy, Role, User, UserId, UserState
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.restoration import RestoreAuthority, decide_restoration
from tests.helpers import NOW

ADMIN = User(
    UserId("admin"), "admin@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW
)


@pytest.mark.parametrize("policy", list(RegistrationPolicy))
@pytest.mark.parametrize("count", [1, 3])
@pytest.mark.parametrize("state", list(UserState))
def test_conservative_restoration_decision(
    policy: RegistrationPolicy, count: int, state: UserState
) -> None:
    decision = decide_restoration(policy, count, replace(ADMIN, state=state))
    expected = policy
    if policy is RegistrationPolicy.OPEN:
        expected = RegistrationPolicy.ONLY_ME if count == 1 else RegistrationPolicy.INVITATION_ONLY
    assert decision.registration_policy is expected
    assert decision.administrator_id == ADMIN.id
    assert decision.administrator_state is UserState.ACTIVE
    assert decision.other_user_state is UserState.DISABLED
    assert decision.disconnect_accounts is True
    assert decision.invalidate == frozenset(RestoreAuthority)
    assert len(decision.invalidate) == 15


@pytest.mark.parametrize(
    ("count", "administrator"),
    [(0, ADMIN), (-1, ADMIN), (1, None), (2, replace(ADMIN, role=Role.USER))],
)
def test_restoration_refuses_nonexecutable_selection(
    count: int, administrator: User | None
) -> None:
    with pytest.raises(DomainValidationError):
        decide_restoration(RegistrationPolicy.OPEN, count, administrator)
