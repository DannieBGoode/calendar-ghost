from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.domain.access import UserId
from calendar_sync.domain.email_changes import (
    CredentialRevision,
    EmailChangeMode,
    EmailChangeProof,
    email_change_mode,
)
from calendar_sync.domain.errors import DomainValidationError

NOW = datetime(2026, 10, 21, tzinfo=UTC)
OWNER = UserId("owner")
HASH = "a" * 64


@pytest.mark.parametrize(
    ("smtp_present", "configured", "initial_email", "mode"),
    [
        (False, False, False, EmailChangeMode.DIRECT),
        (False, True, False, EmailChangeMode.DIRECT),
        (True, False, False, EmailChangeMode.UNAVAILABLE),
        (True, True, False, EmailChangeMode.VERIFIED),
        (False, False, True, EmailChangeMode.DIRECT),
        (False, True, True, EmailChangeMode.DIRECT),
        (True, False, True, EmailChangeMode.DIRECT),
        (True, True, True, EmailChangeMode.DIRECT),
    ],
)
def test_email_change_mode_decision_table(
    smtp_present: bool, configured: bool, initial_email: bool, mode: EmailChangeMode
) -> None:
    assert email_change_mode(smtp_present, configured, initial_email) is mode


def test_email_proof_usability_decision_table() -> None:
    proof = EmailChangeProof(OWNER, CredentialRevision(2), HASH, NOW + timedelta(hours=24))

    assert proof.usable_by(OWNER, CredentialRevision(2), True, NOW)
    assert not proof.usable_by(OWNER, CredentialRevision(2), True, proof.expires_at)
    assert not proof.usable_by(UserId("other"), CredentialRevision(2), True, NOW)
    assert not proof.usable_by(OWNER, CredentialRevision(3), True, NOW)
    assert not proof.usable_by(OWNER, CredentialRevision(2), False, NOW)
    assert not replace(proof, used_at=NOW).usable_by(OWNER, CredentialRevision(2), True, NOW)
    assert not replace(proof, revoked_at=NOW).usable_by(OWNER, CredentialRevision(2), True, NOW)
    assert HASH not in repr(proof)


@pytest.mark.parametrize("token_hash", ["a" * 63, "A" * 64, "not-a-digest"])
def test_email_proof_refuses_a_non_sha256_digest(token_hash: str) -> None:
    with pytest.raises(DomainValidationError):
        EmailChangeProof(OWNER, CredentialRevision(0), token_hash, NOW)


def test_credential_revision_is_monotonic() -> None:
    initial = CredentialRevision(0)
    changed = initial.next()
    changed_back = changed.next()

    assert initial.value == 0
    assert changed.value == 1
    assert changed_back.value == 2
    assert changed_back != initial
    with pytest.raises(DomainValidationError):
        CredentialRevision(-1)
