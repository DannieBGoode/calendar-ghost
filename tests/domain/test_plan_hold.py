"""Pure Plan Hold decisions, including grace restarts and deterministic rule ranking."""

from collections.abc import Sequence
from datetime import timedelta

import pytest

from calendar_sync.domain.model import SyncRuleId
from calendar_sync.domain.plan_hold import (
    GRACE,
    PlanGrace,
    PlanNotice,
    PlanNoticeKind,
    RulePlace,
    RuleStanding,
    Settlement,
    settle,
)
from tests.helpers import NOW

A, B, C, D = (SyncRuleId(value) for value in ("a", "b", "c", "d"))
COUNTED, RESERVED, HELD = RulePlace.COUNTED, RulePlace.RESERVED, RulePlace.HELD
STARTED, HELD_NOTICE = PlanNoticeKind.GRACE_STARTED, PlanNoticeKind.RULES_HELD
FUTURE = NOW + GRACE
EXPIRED = PlanGrace(NOW, 1, 4)
PENDING = PlanGrace(FUTURE, 1, 4)


def standing(
    rule_id: SyncRuleId, place: RulePlace, order: int = 1, *, kept: bool = False
) -> RuleStanding:
    return RuleStanding(rule_id, place, order, kept)


TWO = (standing(A, COUNTED), standing(B, COUNTED, 2))
MIXED = (*TWO, standing(C, RESERVED, 3))


@pytest.mark.parametrize(
    ("standings", "limit", "grace", "admissions", "active", "expected"),
    [
        pytest.param(
            (*TWO, standing(C, HELD)),
            None,
            EXPIRED,
            4,
            False,
            Settlement((), (), (), None, None),
            id="disabled-before-unlimited",
        ),
        pytest.param(
            (standing(B, HELD, 2), standing(A, HELD)),
            None,
            EXPIRED,
            4,
            True,
            Settlement((), (), (A, B), None, None),
            id="unlimited",
        ),
        pytest.param(
            TWO,
            1,
            None,
            4,
            True,
            Settlement((), (), (), PENDING, PlanNotice(STARTED, 2, 1, 1, FUTURE)),
            id="first-excess",
        ),
        pytest.param(
            TWO,
            1,
            PlanGrace(NOW, 2, 4),
            4,
            True,
            Settlement((), (), (), PENDING, PlanNotice(STARTED, 2, 1, 1, FUTURE)),
            id="further-lowering-restarts",
        ),
        pytest.param(
            TWO,
            1,
            EXPIRED,
            5,
            True,
            Settlement((), (), (), PlanGrace(FUTURE, 1, 5), PlanNotice(STARTED, 2, 1, 1, FUTURE)),
            id="increased-admissions-restarts",
        ),
        pytest.param(
            MIXED,
            2,
            PlanGrace(FUTURE, 1, 4),
            4,
            True,
            Settlement((), (), (), PlanGrace(FUTURE, 2, 4), None),
            id="raised-limit-still-over-keeps-deadline",
        ),
        pytest.param(
            TWO,
            1,
            EXPIRED,
            4,
            True,
            Settlement((B,), (), (), EXPIRED, PlanNotice(HELD_NOTICE, 2, 1, 1, NOW)),
            id="inclusive-expiry",
        ),
        pytest.param(
            TWO,
            1,
            PlanGrace(NOW + timedelta(microseconds=1), 1, 4),
            4,
            True,
            Settlement((), (), (), PlanGrace(NOW + timedelta(microseconds=1), 1, 4), None),
            id="no-action-before-deadline",
        ),
        pytest.param(
            MIXED,
            1,
            None,
            4,
            True,
            Settlement((), (), (), PENDING, PlanNotice(STARTED, 3, 1, 1, FUTURE, reserved=1)),
            id="grace-counts-counted-and-reserved-losers-separately",
        ),
        pytest.param(
            (standing(A, COUNTED), standing(B, RESERVED, 2)),
            1,
            EXPIRED,
            4,
            True,
            Settlement((), (B,), (), EXPIRED, None),
            id="reserved-only-expiry",
        ),
        pytest.param(
            MIXED,
            1,
            EXPIRED,
            4,
            True,
            Settlement((B,), (C,), (), EXPIRED, PlanNotice(HELD_NOTICE, 3, 1, 1, NOW)),
            id="mixed-expiry-reports-only-holds",
        ),
        pytest.param(
            (standing(A, COUNTED, 1), standing(B, COUNTED, 9, kept=True)),
            1,
            EXPIRED,
            4,
            True,
            Settlement((A,), (), (), EXPIRED, PlanNotice(HELD_NOTICE, 2, 1, 1, NOW)),
            id="kept-outranks-oldest",
        ),
        pytest.param(
            (standing(B, COUNTED, 1), standing(A, COUNTED, 9)),
            1,
            EXPIRED,
            4,
            True,
            Settlement((A,), (), (), EXPIRED, PlanNotice(HELD_NOTICE, 2, 1, 1, NOW)),
            id="oldest-outranks-id",
        ),
        pytest.param(
            (standing(B, COUNTED), standing(A, COUNTED)),
            1,
            EXPIRED,
            4,
            True,
            Settlement((B,), (), (), EXPIRED, PlanNotice(HELD_NOTICE, 2, 1, 1, NOW)),
            id="id-breaks-tie",
        ),
        pytest.param(
            (
                standing(D, HELD),
                standing(C, HELD, 2),
                standing(B, HELD),
                standing(A, HELD, 9, kept=True),
            ),
            3,
            EXPIRED,
            4,
            True,
            Settlement((), (), (A, B, D), None, None),
            id="best-first-release",
        ),
        pytest.param(
            (standing(A, COUNTED),),
            1,
            EXPIRED,
            4,
            True,
            Settlement((), (), (), None, None),
            id="within-limit-clears-grace",
        ),
        pytest.param(
            (standing(A, COUNTED, 9), standing(B, HELD, 1, kept=True)),
            1,
            EXPIRED,
            4,
            True,
            Settlement((), (), (), None, None),
            id="no-automatic-swap",
        ),
        pytest.param(
            (standing(A, RESERVED), standing(B, HELD)),
            1,
            None,
            4,
            True,
            Settlement((), (), (), None, None),
            id="reserved-place-blocks-release",
        ),
    ],
)
def test_settle_decision_table(
    standings: Sequence[RuleStanding],
    limit: int | None,
    grace: PlanGrace | None,
    admissions: int,
    active: bool,
    expected: Settlement,
) -> None:
    assert settle(standings, limit, grace, admissions, NOW, active=active) == expected


def test_a_raise_and_lowering_with_an_admission_restarts_grace() -> None:
    initial = settle(TWO, 1, None, 4, NOW, active=True)
    assert initial == Settlement((), (), (), PENDING, PlanNotice(STARTED, 2, 1, 1, FUTURE))
    # Between passes, a raise admits C and removing B leaves the same count. Lowering the
    # limit again must give C a full grace: removing B did not erase C's admission.
    after_removal = (standing(A, COUNTED), standing(C, COUNTED, 3))
    next_pass = NOW + timedelta(days=1)
    result = settle(after_removal, 1, initial.grace, 5, next_pass, active=True)
    assert result == Settlement(
        (),
        (),
        (),
        PlanGrace(next_pass + GRACE, 1, 5),
        PlanNotice(STARTED, 2, 1, 1, next_pass + GRACE),
    )


def test_expired_grace_survives_until_excess_is_gone() -> None:
    first = settle(MIXED, 1, EXPIRED, 4, NOW, active=True)
    assert first == Settlement((B,), (C,), (), EXPIRED, PlanNotice(HELD_NOTICE, 3, 1, 1, NOW))
    # A caller can commit only the locked subset. Remaining excess gets no new grace.
    partial = (standing(A, COUNTED), standing(B, HELD, 2), standing(C, RESERVED, 3))
    retry = settle(partial, 1, first.grace, 4, NOW + timedelta(minutes=1), active=True)
    assert retry == Settlement((), (C,), (), EXPIRED, None)
    finished = (standing(A, COUNTED), standing(B, HELD, 2))
    assert settle(
        finished, 1, retry.grace, 4, NOW + timedelta(minutes=2), active=True
    ) == Settlement((), (), (), None, None)
