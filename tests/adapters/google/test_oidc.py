"""OIDC is validated through signed JWTs and an injected HTTP boundary."""

import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from joserfc.jwk import RSAKey

from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInRefused
from calendar_sync.infrastructure.google.oidc import GoogleAuthorization
from calendar_sync.infrastructure.oidc import OidcClientConfig
from tests.fakes.oidc import CLIENT, NONCE, VERIFIER, OidcFake


def adapter(fake: OidcFake) -> GoogleAuthorization:
    return GoogleAuthorization(
        OidcClientConfig(
            CLIENT, "secret", "https://calendar.example.test/api/v1/sign-in/google/callback"
        ),
        fake.clock,
        fake,
    )


def test_begin_and_exchange() -> None:
    fake = OidcFake()
    service = adapter(fake)
    query = parse_qs(urlsplit(service.begin("s" * 43, NONCE, VERIFIER)).query)
    assert query["client_id"] == [CLIENT]
    assert "secret" not in service.begin("s" * 43, NONCE, VERIFIER)
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] != [VERIFIER]
    assert query["nonce"] == [NONCE]
    claims = service.exchange("code", NONCE, VERIFIER)
    assert claims.key.issuer == "https://accounts.google.com"
    assert claims.email_verified
    form = parse_qs(next(call[2] or "" for call in fake.calls if call[0] == "POST"))
    assert form["client_id"] == [CLIENT]
    assert form["client_secret"] == ["secret"]
    assert form["code_verifier"] == [VERIFIER]
    assert form["redirect_uri"] == query["redirect_uri"]
    assert len(fake.calls) == 3


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "https://attacker.test"),
        ("aud", "other"),
        ("aud", [CLIENT, "other"]),
        ("azp", "other"),
        ("sub", ""),
        ("sub", 2),
        ("nonce", "other"),
        ("exp", 1),
        ("iat", 9999999999),
        ("nbf", 9999999999),
        ("exp", "9999999999"),
        ("iat", True),
        ("sub", "x" * 256),
        ("email", "x" * 255),
        ("aud", {}),
    ],
)
def test_jwt_rejection_table(claim: str, value: object) -> None:
    fake = OidcFake()
    claims = fake.claims()
    claims[claim] = value
    fake.token = fake.signed(claims)
    with pytest.raises(ProviderSignInRefused):
        adapter(fake).exchange("code", NONCE, VERIFIER)


@pytest.mark.parametrize("claim", ["iss", "aud", "sub", "nonce", "exp", "iat"])
def test_required_claims(claim: str) -> None:
    fake = OidcFake()
    claims = fake.claims()
    del claims[claim]
    fake.token = fake.signed(claims)
    with pytest.raises(ProviderSignInRefused):
        adapter(fake).exchange("code", NONCE, VERIFIER)


@pytest.mark.parametrize("verified", [False, "true", 1, None])
def test_unverified_email_never_becomes_verified(verified: object) -> None:
    fake = OidcFake()
    claims = fake.claims()
    claims["email_verified"] = verified
    fake.token = fake.signed(claims)
    assert not adapter(fake).exchange("code", NONCE, VERIFIER).email_verified


def test_jwks_rotation_and_fetch_bounds() -> None:
    fake = OidcFake()
    service = adapter(fake)
    service.exchange("code", NONCE, VERIFIER)
    fake.key = RSAKey.generate_key(2048, {"kid": "rotated"})
    service.exchange("code", NONCE, VERIFIER)
    assert sum("certs" in call[1] for call in fake.calls) == 2
    fake.token = fake.signed(kid="unknown")
    with pytest.raises(ProviderSignInRefused):
        service.exchange("code", NONCE, VERIFIER)
    assert sum("certs" in call[1] for call in fake.calls) == 3
    fake.clock.value += timedelta(hours=1)
    fake.token = ""
    service.exchange("code", NONCE, VERIFIER)
    assert sum("well-known" in call[1] for call in fake.calls) == 2


@pytest.mark.parametrize(
    "token", ["broken", "x" * 16385, "eyJhbGciOiJub25lIn0.e30.", "WyJhbGciXQ.e30.eA"]
)
def test_malformed_algorithm_and_oversized_tokens(token: str) -> None:
    fake = OidcFake(token=token)
    with pytest.raises(ProviderSignInRefused):
        adapter(fake).exchange("code", NONCE, VERIFIER)
    assert len(fake.calls) == 1


def test_signature_and_header_urls_are_refused() -> None:
    fake = OidcFake()
    fake.token = fake.signed()
    fake.key = RSAKey.generate_key(2048, {"kid": "first"})
    with pytest.raises(ProviderSignInRefused):
        adapter(fake).exchange("code", NONCE, VERIFIER)
    fake.token = fake.signed(jku="https://attacker.test/keys")
    with pytest.raises(ProviderSignInRefused):
        adapter(fake).exchange("code", NONCE, VERIFIER)
    assert all("attacker" not in call[1] for call in fake.calls)


def test_discovery_may_not_supply_an_untrusted_jwks() -> None:
    fake = OidcFake()
    fake.responses["https://accounts.google.com/.well-known/openid-configuration"] = json.dumps(
        {"issuer": fake.issuer, "jwks_uri": "https://attacker.test/keys"}
    ).encode()
    with pytest.raises(ProviderSignInRefused):
        adapter(fake).exchange("code", NONCE, VERIFIER)
    assert len(fake.calls) == 2


@pytest.mark.parametrize("variant", ["canonical", "legacy", "multiple-audience", "clock-skew"])
def test_valid_claim_variants(variant: str) -> None:
    fake = OidcFake()
    claims = fake.claims()
    if variant == "legacy":
        claims["iss"] = "accounts.google.com"
    if variant == "multiple-audience":
        claims.update(aud=[CLIENT, "second"], azp=CLIENT)
    if variant == "clock-skew":
        now = int(fake.clock.now().timestamp())
        claims.update(iat=now - 120, exp=now - 59, nbf=now + 59)
    fake.token = fake.signed(claims)
    assert (
        adapter(fake).exchange("code", NONCE, VERIFIER).key.issuer == "https://accounts.google.com"
    )


@pytest.mark.parametrize(
    "variant",
    ["oversized-jwks", "duplicate-kid", "too-many-keys", "oversized-key", "wrong-algorithm"],
)
def test_jwks_and_algorithm_bounds(variant: str) -> None:
    fake = OidcFake()
    key = fake.key.as_dict(private=False)
    document = {"keys": [key]}
    if variant == "duplicate-kid":
        document["keys"] = [key, key]
    if variant == "too-many-keys":
        document["keys"] = [key] * 101
    if variant == "oversized-key":
        key["n"] = "x" * 1025
    if variant == "wrong-algorithm":
        fake.token = fake.signed(alg="PS256")
    raw = b"x" * (1024 * 1024 + 1) if variant == "oversized-jwks" else json.dumps(document).encode()
    fake.responses["https://www.googleapis.com/oauth2/v3/certs"] = raw
    with pytest.raises(ProviderSignInRefused):
        adapter(fake).exchange("code", NONCE, VERIFIER)


@pytest.mark.parametrize(
    "uri",
    [
        "http://public.example.test/callback",
        "https://u:p@host.test/callback",
        "https://host.test/callback?secret=x",
        "https://host.test/callback#fragment",
    ],
)
def test_callback_must_be_a_trusted_origin(uri: str) -> None:
    with pytest.raises(ValueError, match="trusted callback"):
        OidcClientConfig(CLIENT, "secret", uri)


@pytest.mark.parametrize(("ahead", "accepted"), [(59, True), (60, True), (61, False), (120, False)])
def test_issued_at_clock_skew_with_valid_lifetime(ahead: int, accepted: bool) -> None:
    fake = OidcFake()
    claims = fake.claims()
    now = int(fake.clock.now().timestamp())
    claims.update(iat=now + ahead, exp=now + 600)
    fake.token = fake.signed(claims)
    if accepted:
        assert adapter(fake).exchange("code", NONCE, VERIFIER).email_verified
    else:
        with pytest.raises(ProviderSignInRefused):
            adapter(fake).exchange("code", NONCE, VERIFIER)
