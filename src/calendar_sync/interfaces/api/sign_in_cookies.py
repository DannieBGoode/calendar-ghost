"""Browser context comes only from cookies received by the HTTP boundary."""

from fastapi import Request

from calendar_sync.application.identity.ports import SignInBrowser
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE

BROWSER_COOKIE = "calendar_sync_sign_in_browser"
PENDING_COOKIE = "calendar_sync_provider_pending"


def browser_context(request: Request) -> SignInBrowser | None:
    token, proof = request.cookies.get(SESSION_COOKIE), cookie_proof(request, BROWSER_COOKIE)
    return SignInBrowser(token, proof) if token or proof else None


def cookie_proof(request: Request, name: str) -> str | None:
    value = request.cookies.get(name)
    return value if value and 32 <= len(value) <= 128 and value.isascii() else None
