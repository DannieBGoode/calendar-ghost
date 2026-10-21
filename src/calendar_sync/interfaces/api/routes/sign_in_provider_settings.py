"""Administrator-only provider sign-in configuration and readiness."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from calendar_sync.domain.access import UserId
from calendar_sync.interfaces.api.dependencies import administrator
from calendar_sync.interfaces.api.oidc_schemas import (
    ProviderSettingRequest,
    ProviderSettingResponse,
)
from calendar_sync.interfaces.api.provider_boundary import Services, provider_errors, require_origin

router = APIRouter()
Administrator = Annotated[UserId, Depends(administrator)]


@router.get("/api/v1/settings/sign-in-providers", response_model=list[ProviderSettingResponse])
def settings(services: Services, _actor: Administrator) -> list[ProviderSettingResponse]:
    with provider_errors():
        return [
            ProviderSettingResponse(
                provider=item.provider,
                enabled=item.enabled,
                available=item.available,
                reason=item.reason,
            )
            for item in services.provider_sign_in.settings.list()
        ]


@router.put("/api/v1/settings/sign-in-providers/{slug}", status_code=204)
def enable(
    slug: str,
    payload: ProviderSettingRequest,
    request: Request,
    services: Services,
    actor: Administrator,
) -> None:
    with provider_errors():
        require_origin(request, services.provider_sign_in)
        services.provider_sign_in.settings.set_enabled(actor, slug, payload.enabled)
