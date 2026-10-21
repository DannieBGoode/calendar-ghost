"""Registration admission and email proof decisions are provider-independent."""

from datetime import timedelta
from itertools import product

import pytest

from calendar_sync.domain.access import RegistrationPolicy
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.registration import (
    RegistrationProof,
    may_accept_invitation_directly,
    may_finish_registration,
    may_issue_invitation,
    registration_expiry,
)
from tests.helpers import NOW


def test_registration_policy_decisions() -> None:
    for policy, bound, operational in product(RegistrationPolicy, (False, True), (False, True)):
        assert may_issue_invitation(policy) == (policy is not RegistrationPolicy.ONLY_ME)
        assert may_accept_invitation_directly(policy) == (
            policy is RegistrationPolicy.INVITATION_ONLY
        )
        expected = (policy is RegistrationPolicy.OPEN and operational) or (
            policy is RegistrationPolicy.INVITATION_ONLY and bound
        )
        assert may_finish_registration(policy, bound, operational) == expected


def test_proof_usability() -> None:
    expiry = NOW + timedelta(hours=24)
    proof = RegistrationProof("a" * 64, "new@example.test", expiry)
    assert proof.usable(NOW)
    assert not proof.usable(expiry)
    assert not RegistrationProof("a" * 64, "new@example.test", expiry, used_at=NOW).usable(NOW)
    assert not RegistrationProof("a" * 64, "new@example.test", expiry, revoked_at=NOW).usable(NOW)
    for digest in ("", "a" * 63, "g" * 64, "A" * 64, "a" * 64 + "\n"):
        with pytest.raises(DomainValidationError):
            RegistrationProof(digest, "new@example.test", expiry)


def test_registration_deadline() -> None:
    assert registration_expiry(NOW) == NOW + timedelta(hours=24)
    assert registration_expiry(NOW, NOW + timedelta(days=7)) == NOW + timedelta(hours=24)
    assert registration_expiry(NOW, NOW + timedelta(hours=2)) == NOW + timedelta(hours=2)
