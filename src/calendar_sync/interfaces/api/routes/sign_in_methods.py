"""Sign-in methods of the owning signed-in User."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from calendar_sync.application.identity.provider_sign_in_ports import (
    BeginIntent,
    ProviderSignInRefused,
)
from calendar_sync.domain.access import UserId
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE, current_user
from calendar_sync.interfaces.api.oidc_schemas import (
    LinkedIdentityResponse,
    ProviderStartResponse,
    SetPasswordRequest,
    SignInMethodsResponse,
)
from calendar_sync.interfaces.api.provider_boundary import (
    Services,
    browser_proof,
    client,
    provider_errors,
    require_origin,
    resolve_owner,
    runtime,
    set_proof,
)
from calendar_sync.interfaces.api.sign_in_cookies import (
    BROWSER_COOKIE,
)

router = APIRouter()
SignedIn = Annotated[UserId, Depends(current_user)]


@router.get("/api/v1/account/sign-in-methods", response_model=SignInMethodsResponse)
def methods(services: Services, user: SignedIn) -> SignInMethodsResponse:
    with provider_errors():
        found = services.provider_sign_in.methods.methods.show(user)
        return SignInMethodsResponse(
            has_password=found.has_password,
            identities=[
                LinkedIdentityResponse(id=item.id, provider=item.provider)
                for item in found.identities
            ],
        )


@router.post("/api/v1/account/sign-in-methods/{slug}/start", response_model=ProviderStartResponse)
def start(
    slug: str, request: Request, response: Response, services: Services, user: SignedIn
) -> ProviderStartResponse:
    with provider_errors():
        service = services.provider_sign_in
        require_origin(request, service)
        use = runtime(service)
        use.limits.admit(client(request), "begin")
        owner = resolve_owner(request, service)
        if owner is None or owner.user_id != user:
            raise ProviderSignInRefused
        proof = browser_proof(request, fresh=True)
        answer = ProviderStartResponse(
            authorization_url=use.begin.execute(BeginIntent(slug, proof, owner=owner))
        )
        set_proof(response, BROWSER_COOKIE, proof.value, service.secure)
        return answer


@router.delete("/api/v1/account/sign-in-methods/{identity_id}", status_code=204)
def unlink(identity_id: str, request: Request, services: Services, user: SignedIn) -> None:
    with provider_errors():
        service = services.provider_sign_in
        require_origin(request, service)
        owner = resolve_owner(request, service)
        if owner is None or owner.user_id != user:
            raise ProviderSignInRefused
        service.methods.unlink.execute(owner, identity_id)


@router.post("/api/v1/account/password", status_code=204)
def password(
    payload: SetPasswordRequest, request: Request, services: Services, user: SignedIn
) -> None:
    with provider_errors():
        service = services.provider_sign_in
        require_origin(request, service)
        service.methods.set_password.execute(
            user, payload.password, request.cookies.get(SESSION_COOKIE, "")
        )
