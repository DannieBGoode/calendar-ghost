"""Strict ID-token claims on top of joserfc's signature and registered-claim validation."""

from typing import cast

from joserfc.jwt import JWTClaimsRegistry

from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInRefused


def text_claim(claims: dict[str, object], name: str, limit: int = 255) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ProviderSignInRefused
    return value


def validate_claims(claims: dict[str, object], client: str, nonce: str, now: int) -> None:
    for name in ("iss", "sub", "nonce"):
        text_claim(claims, name)
    for name in ("exp", "iat", "nbf"):
        if name in claims and type(claims[name]) is not int:
            raise ProviderSignInRefused
    _validate_audience(claims, client)
    JWTClaimsRegistry(
        now=now,
        leeway=60,
        iss={"essential": True},
        sub={"essential": True},
        aud={"essential": True, "value": client},
        nonce={"essential": True, "value": nonce},
        exp={"essential": True},
        iat={"essential": True},
    ).validate(claims)
    if cast(int, claims["exp"]) < cast(int, claims["iat"]):
        raise ProviderSignInRefused
    if "email" in claims and claims["email"] is not None:
        text_claim(claims, "email", 254)


def _validate_audience(claims: dict[str, object], client: str) -> None:
    audience = claims.get("aud")
    if isinstance(audience, list):
        if not audience or len(audience) > 10 or any(not isinstance(v, str) for v in audience):
            raise ProviderSignInRefused
        if len(audience) > 1 and claims.get("azp") != client:
            raise ProviderSignInRefused
    elif not isinstance(audience, str):
        raise ProviderSignInRefused
    if "azp" in claims and claims["azp"] != client:
        raise ProviderSignInRefused
