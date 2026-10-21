"""Public provider sign-in: browser-bound flows and fixed redirect targets only."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from calendar_sync.application.identity.provider_sign_in_ports import (
    BeginIntent,
    InvitationIntent,
    ProviderCallback,
    ProviderSignInRefused,
    ProviderSignInResult,
)
from calendar_sync.interfaces.api.dependencies import set_session_cookie
from calendar_sync.interfaces.api.oidc_schemas import (
    AvailableProvidersResponse,
    ConfirmProviderRequest,
    PendingProviderResponse,
    ProviderStartRequest,
    ProviderStartResponse,
)
from calendar_sync.interfaces.api.provider_boundary import (
    Services,
    browser_proof,
    client,
    provider_errors,
    require_anonymous,
    require_origin,
    resolve_owner,
    runtime,
    set_proof,
)
from calendar_sync.interfaces.api.routes.session import signed_in
from calendar_sync.interfaces.api.schemas.identity import SessionResponse
from calendar_sync.interfaces.api.sign_in_cookies import (
    BROWSER_COOKIE,
    PENDING_COOKIE,
    cookie_proof,
)

router = APIRouter()
FAILED = "/sign-in?provider_result=unavailable"


@router.get("/api/v1/sign-in/providers", response_model=AvailableProvidersResponse)
def providers(services: Services) -> AvailableProvidersResponse:
    with provider_errors():
        return AvailableProvidersResponse(
            providers=[
                item.provider
                for item in services.provider_sign_in.settings.list()
                if item.enabled and item.available
            ]
        )


@router.post("/api/v1/sign-in/{slug}/start", response_model=ProviderStartResponse)
def start(
    slug: str,
    request: Request,
    response: Response,
    services: Services,
    payload: ProviderStartRequest | None = None,
) -> ProviderStartResponse:
    with provider_errors():
        service = services.provider_sign_in
        require_origin(request, service)
        use = runtime(service)
        use.limits.admit(client(request), "begin")
        require_anonymous(request, service)
        proof = browser_proof(request, fresh=True)
        invitation = (
            InvitationIntent(payload.invitation_token, payload.email)
            if payload and payload.invitation_token and payload.email
            else None
        )
        answer = ProviderStartResponse(
            authorization_url=use.begin.execute(BeginIntent(slug, proof, invitation))
        )
        set_proof(response, BROWSER_COOKIE, proof.value, service.secure)
        return answer


def _callback(request: Request, slug: str, services: Services) -> ProviderSignInResult:
    query = request.query_params
    if any(len(query.getlist(key)) != 1 for key in query):
        raise ProviderSignInRefused
    state, code = query.get("state", ""), query.get("code", "")
    if not state or len(state) > 128 or not state.isascii():
        raise ProviderSignInRefused
    if len(code) > 4096 or not code.isascii():
        raise ProviderSignInRefused
    service = services.provider_sign_in
    use = runtime(service)
    use.limits.admit(client(request), "callback")
    callback = ProviderCallback(
        slug, state, code, browser_proof(request), resolve_owner(request, service)
    )
    if "error" in query or not code:
        use.flows.consume(callback)
        raise ProviderSignInRefused
    return use.complete.execute(callback)


@router.get("/api/v1/sign-in/{slug}/callback", response_class=RedirectResponse, status_code=303)
def callback(slug: str, request: Request, services: Services) -> RedirectResponse:
    try:
        result = _callback(request, slug, services)
        response = _completed(result, services)
    except Exception:
        # Do not reflect arbitrary provider errors, query parameters or exception text.
        return RedirectResponse(FAILED, status_code=303)
    return response


def _completed(result: ProviderSignInResult, services: Services) -> RedirectResponse:
    secure = services.provider_sign_in.secure
    if result.pending is not None:
        response = RedirectResponse("/provider-link", status_code=303)
        set_proof(response, PENDING_COOKIE, result.pending.token, secure)
        return response
    if result.session is None:
        return RedirectResponse("/settings/account", status_code=303)
    answers = services.registrations.answers
    user = answers.get(result.session.user_id)
    if user is None:
        raise ProviderSignInRefused
    # Assemble every signed-in read before emitting any cookie, with capped SQLite waits.
    signed_in(user, answers)
    response = RedirectResponse("/overview", status_code=303)
    response.delete_cookie(PENDING_COOKIE, path="/")
    set_session_cookie(response, result.session.token, secure)
    return response


@router.get("/api/v1/sign-in/pending", response_model=PendingProviderResponse)
def pending(request: Request, services: Services) -> PendingProviderResponse:
    with provider_errors():
        service = services.provider_sign_in
        require_anonymous(request, service)
        token = cookie_proof(request, PENDING_COOKIE)
        proof = cookie_proof(request, BROWSER_COOKIE)
        usable = bool(
            token and proof and runtime(service).flows.pending(browser_proof(request), token)
        )
        return PendingProviderResponse(password_required=usable)


@router.post("/api/v1/sign-in/confirm", response_model=SessionResponse)
def confirm(
    payload: ConfirmProviderRequest, request: Request, response: Response, services: Services
) -> SessionResponse:
    with provider_errors():
        service = services.provider_sign_in
        require_origin(request, service)
        use = runtime(service)
        use.limits.admit(client(request), "confirmation")
        require_anonymous(request, service)
        session = use.confirm.execute(
            browser_proof(request),
            cookie_proof(request, PENDING_COOKIE) or "",
            payload.email,
            payload.password,
            client(request),
        )
        answers = services.registrations.answers
        user = answers.get(session.user_id)
        if user is None:
            raise ProviderSignInRefused
        answer = signed_in(user, answers)
        response.delete_cookie(PENDING_COOKIE, path="/")
        set_session_cookie(response, session.token, service.secure)
        return answer
