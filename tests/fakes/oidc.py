"""Signed, synthetic OIDC responses; no live identity endpoints."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from joserfc import jwt
from joserfc.jwk import RSAKey

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
CLIENT = "synthetic-client"
NONCE = "n" * 43
VERIFIER = "v" * 43
TENANT = "11111111-2222-4333-8444-555555555555"
PERSONAL = "9188040d-6c67-4c5b-b112-36a304b66dad"


@dataclass
class FixedClock:
    value: datetime = NOW

    def now(self) -> datetime:
        return self.value


@dataclass
class OidcFake:
    issuer: str = "https://accounts.google.com"
    key: RSAKey = field(default_factory=lambda: RSAKey.generate_key(2048, {"kid": "first"}))
    clock: FixedClock = field(default_factory=lambda: FixedClock(NOW))
    calls: list[tuple[str, str, str | None]] = field(default_factory=list)
    responses: dict[str, bytes] = field(default_factory=dict)
    token: str = ""

    def claims(self) -> dict[str, object]:
        return {
            "iss": self.issuer,
            "aud": CLIENT,
            "sub": "synthetic-subject",
            "nonce": NONCE,
            "iat": int(self.clock.now().timestamp()),
            "exp": int(self.clock.now().timestamp()) + 300,
            "email": "synthetic@example.test",
            "email_verified": True,
        }

    def signed(self, claims: dict[str, object] | None = None, **headers: str) -> str:
        return jwt.encode(
            {"alg": "RS256", "kid": self.key.kid, **headers},
            claims or self.claims(),
            self.key,
            algorithms=[headers.get("alg", "RS256")],
        )

    def request(self, method: str, url: str, body: str | None = None) -> bytes:
        self.calls.append((method, url, body))
        if url in self.responses:
            return self.responses[url]
        if method == "POST":
            return json.dumps(
                {"id_token": self.token or self.signed(), "access_token": "discard-me"}
            ).encode()
        if "well-known" in url:
            microsoft = "microsoft" in url
            return json.dumps(
                {
                    "issuer": "https://login.microsoftonline.com/{tenantid}/v2.0"
                    if microsoft
                    else self.issuer,
                    "jwks_uri": "https://login.microsoftonline.com/common/discovery/v2.0/keys"
                    if microsoft
                    else "https://www.googleapis.com/oauth2/v3/certs",
                }
            ).encode()
        key = self.key.as_dict(private=False)
        if "microsoft" in url:
            key["issuer"] = "https://login.microsoftonline.com/{tenantid}/v2.0"
        return json.dumps({"keys": [key]}).encode()
