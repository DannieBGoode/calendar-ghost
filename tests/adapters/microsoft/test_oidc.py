import json
from urllib.parse import parse_qs, urlsplit

import pytest

from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInRefused
from calendar_sync.infrastructure.microsoft.oidc import MicrosoftAuthorization
from calendar_sync.infrastructure.oidc import OidcClientConfig
from tests.fakes.oidc import CLIENT, NONCE, PERSONAL, TENANT, VERIFIER, OidcFake


def adapter(fake: OidcFake, tenant: str = "common") -> MicrosoftAuthorization:
    return MicrosoftAuthorization(
        OidcClientConfig(
            CLIENT, "secret", "https://calendar.example.test/api/v1/sign-in/microsoft/callback"
        ),
        tenant,
        fake.clock,
        fake,
    )


@pytest.mark.parametrize(
    ("selector", "tid", "key_issuer", "allowed"),
    [
        ("common", TENANT, "https://login.microsoftonline.com/{tenantid}/v2.0", True),
        ("organizations", TENANT, "https://login.microsoftonline.com/{tenantid}/v2.0", True),
        (TENANT, TENANT, f"https://login.microsoftonline.com/{TENANT}/v2.0", True),
        ("consumers", PERSONAL, f"https://login.microsoftonline.com/{PERSONAL}/v2.0", True),
        ("organizations", PERSONAL, "https://login.microsoftonline.com/{tenantid}/v2.0", False),
        ("consumers", TENANT, "https://login.microsoftonline.com/{tenantid}/v2.0", False),
        (TENANT, PERSONAL, "https://login.microsoftonline.com/{tenantid}/v2.0", False),
        ("common", TENANT, f"https://login.microsoftonline.com/{PERSONAL}/v2.0", False),
        ("common", "not-guid", "https://login.microsoftonline.com/{tenantid}/v2.0", False),
        ("common", TENANT, "", False),
    ],
)
def test_tenant_and_signing_key_issuer(
    selector: str, tid: str, key_issuer: str, allowed: bool
) -> None:
    fake = OidcFake(issuer=f"https://login.microsoftonline.com/{tid}/v2.0")
    claims = fake.claims() | {"tid": tid}
    fake.token = fake.signed(claims)
    key = fake.key.as_dict(private=False) | {"issuer": key_issuer}
    fake.responses["https://login.microsoftonline.com/common/discovery/v2.0/keys"] = json.dumps(
        {"keys": [key]}
    ).encode()
    if allowed:
        result = adapter(fake, selector).exchange("code", NONCE, VERIFIER)
        assert result.key.issuer == fake.issuer
        assert not result.email_verified
    else:
        with pytest.raises(ProviderSignInRefused):
            adapter(fake, selector).exchange("code", NONCE, VERIFIER)


def test_unverified_email_never_becomes_verified() -> None:
    fake = OidcFake(issuer=f"https://login.microsoftonline.com/{TENANT}/v2.0")
    fake.token = fake.signed(
        fake.claims()
        | {
            "tid": TENANT,
            "email_verified": True,
            "preferred_username": "admin@example.test",
            "upn": "admin@example.test",
        }
    )
    assert not adapter(fake).exchange("code", NONCE, VERIFIER).email_verified


@pytest.mark.parametrize("token_tenant", [TENANT, PERSONAL])
def test_domain_tenant_requires_concrete_metadata_issuer(token_tenant: str) -> None:
    fake = OidcFake(issuer=f"https://login.microsoftonline.com/{token_tenant}/v2.0")
    fake.token = fake.signed(fake.claims() | {"tid": token_tenant})
    fake.responses[
        "https://login.microsoftonline.com/contoso.example/v2.0/.well-known/openid-configuration"
    ] = json.dumps(
        {
            "issuer": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "jwks_uri": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
        }
    ).encode()
    if token_tenant == TENANT:
        assert not adapter(fake, "contoso.example").exchange("code", NONCE, VERIFIER).email_verified
    else:
        with pytest.raises(ProviderSignInRefused):
            adapter(fake, "contoso.example").exchange("code", NONCE, VERIFIER)


@pytest.mark.parametrize(
    "selector",
    [
        "foo/bar",
        "evil.test?x=y",
        "user@evil.test",
        "evil.test:443",
        "evil.test#x",
        "évil.test",
        "-evil.test",
        "evil..test",
    ],
)
def test_malformed_tenant_rejected_before_http(selector: str) -> None:
    fake = OidcFake()
    with pytest.raises((ValueError, ProviderSignInRefused)):
        adapter(fake, selector)
    assert not fake.calls


def test_domain_tenant_cannot_use_a_template_issuer() -> None:
    fake = OidcFake(issuer=f"https://login.microsoftonline.com/{TENANT}/v2.0")
    fake.token = fake.signed(fake.claims() | {"tid": TENANT})
    with pytest.raises(ProviderSignInRefused):
        adapter(fake, "contoso.example").exchange("code", NONCE, VERIFIER)


def test_client_credentials_stay_in_their_protocol_fields() -> None:
    fake = OidcFake(issuer=f"https://login.microsoftonline.com/{TENANT}/v2.0")
    fake.token = fake.signed(fake.claims() | {"tid": TENANT})
    service = adapter(fake)
    url = service.begin("s" * 43, NONCE, VERIFIER)
    assert "secret" not in url
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == [CLIENT]
    service.exchange("code", NONCE, VERIFIER)
    form = parse_qs(next(call[2] or "" for call in fake.calls if call[0] == "POST"))
    assert form["client_id"] == [CLIENT]
    assert form["client_secret"] == ["secret"]
    assert form["redirect_uri"] == query["redirect_uri"]
