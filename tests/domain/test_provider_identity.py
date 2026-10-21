"""Provider identity ownership and new User admission are separate decisions."""

from dataclasses import replace
from itertools import product

import pytest

from calendar_sync.domain.access import InvalidEmail, RegistrationPolicy, UserId
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.provider_identity import (
    LinkDecision,
    ProviderAdmissionFacts,
    ProviderClaims,
    ProviderIdentityKey,
    decide_provider_link,
    may_admit_provider_user,
    may_remove_sign_in_method,
)

OWNER = UserId("owner")
OTHER = UserId("other")


def test_link_decision_values() -> None:
    assert {decision.value for decision in LinkDecision} == {
        "existing",
        "link",
        "password_required",
        "refuse",
    }


def test_identity_key_uses_issuer_and_subject() -> None:
    key = ProviderIdentityKey("https://identity.example.test", "Subject-1")
    assert key == ProviderIdentityKey("https://identity.example.test", "Subject-1")
    assert key != replace(key, issuer="https://another.example.test")
    assert key != replace(key, subject="Subject-2")
    assert key != replace(key, subject="subject-1")
    assert key != replace(key, issuer="https://identity.example.test/")
    assert len({key, replace(key, issuer="https://another.example.test")}) == 2

    claims = ProviderClaims(key, "person@example.test", True)
    assert replace(claims, email="changed@example.test").key == claims.key


@pytest.mark.parametrize("field", ["issuer", "subject"])
@pytest.mark.parametrize("empty", ["", " ", "\n"])
def test_identity_key_requires_nonempty_values(field: str, empty: str) -> None:
    values = {"issuer": "https://identity.example.test", "subject": "Subject-1", field: empty}
    with pytest.raises(DomainValidationError):
        ProviderIdentityKey(**values)


def test_claims_normalize_email_and_hide_identity_data() -> None:
    key = ProviderIdentityKey("https://identity.example.test", "Subject-1")
    claims = ProviderClaims(key, " Person@Example.TEST ", True)

    assert claims.email == "person@example.test"
    assert ProviderClaims(key, None, False).email is None
    assert key.issuer not in repr(key)
    assert key.subject not in repr(key)
    assert key.issuer not in repr(claims)
    assert key.subject not in repr(claims)
    assert claims.email not in repr(claims)
    with pytest.raises(InvalidEmail):
        ProviderClaims(key, "not-an-address", True)


@pytest.mark.parametrize("email_verified", [False, True])
@pytest.mark.parametrize(
    ("existing_owner", "signed_in_user", "matching_email_user", "unverified", "verified"),
    [
        (OWNER, None, None, LinkDecision.EXISTING, LinkDecision.EXISTING),
        (OWNER, None, OWNER, LinkDecision.EXISTING, LinkDecision.EXISTING),
        (OWNER, None, OTHER, LinkDecision.EXISTING, LinkDecision.EXISTING),
        (OWNER, OWNER, None, LinkDecision.EXISTING, LinkDecision.EXISTING),
        (OWNER, OWNER, OWNER, LinkDecision.EXISTING, LinkDecision.EXISTING),
        (OWNER, OWNER, OTHER, LinkDecision.EXISTING, LinkDecision.EXISTING),
        (OWNER, OTHER, None, LinkDecision.REFUSE, LinkDecision.REFUSE),
        (OWNER, OTHER, OWNER, LinkDecision.REFUSE, LinkDecision.REFUSE),
        (OWNER, OTHER, OTHER, LinkDecision.REFUSE, LinkDecision.REFUSE),
        (None, OWNER, None, LinkDecision.LINK, LinkDecision.LINK),
        (None, OWNER, OWNER, LinkDecision.LINK, LinkDecision.LINK),
        (None, OWNER, OTHER, LinkDecision.LINK, LinkDecision.LINK),
        (None, None, OWNER, LinkDecision.PASSWORD_REQUIRED, LinkDecision.LINK),
        (None, None, None, LinkDecision.REFUSE, LinkDecision.REFUSE),
    ],
)
def test_link_decision_table(
    existing_owner: UserId | None,
    signed_in_user: UserId | None,
    matching_email_user: UserId | None,
    unverified: LinkDecision,
    verified: LinkDecision,
    email_verified: bool,
) -> None:
    assert decide_provider_link(
        existing_owner, signed_in_user, matching_email_user, email_verified
    ) is (verified if email_verified else unverified)


@pytest.mark.parametrize(
    ("operational", "verified", "invitation_matches", "closed_admits", "open_admits"),
    [
        (False, False, False, False, False),
        (False, False, True, False, False),
        (False, True, False, False, False),
        (False, True, True, True, False),
        (True, False, False, False, False),
        (True, False, True, False, False),
        (True, True, False, False, True),
        (True, True, True, True, True),
    ],
)
@pytest.mark.parametrize("policy", list(RegistrationPolicy))
def test_provider_admission_table(
    policy: RegistrationPolicy,
    operational: bool,
    verified: bool,
    invitation_matches: bool,
    closed_admits: bool,
    open_admits: bool,
) -> None:
    facts = ProviderAdmissionFacts(policy, operational, verified, invitation_matches)
    expected = open_admits if policy is RegistrationPolicy.OPEN else closed_admits
    assert may_admit_provider_user(facts) is expected


@pytest.mark.parametrize(
    ("has_password", "remaining_enabled", "allowed"),
    [
        (False, -1, False),
        (False, 0, False),
        (False, 1, True),
        (False, 2, True),
        (True, 0, True),
        (True, 1, True),
        (True, 2, True),
    ],
)
def test_last_method_table(has_password: bool, remaining_enabled: int, allowed: bool) -> None:
    assert may_remove_sign_in_method(has_password, remaining_enabled) is allowed


def test_new_user_admission_is_separate_from_linking_existing_users() -> None:
    for operational, invitation in product((False, True), repeat=2):
        assert decide_provider_link(None, None, None, True) is LinkDecision.REFUSE
        assert (
            may_admit_provider_user(
                ProviderAdmissionFacts(RegistrationPolicy.OPEN, operational, True, invitation)
            )
            is operational
        )
