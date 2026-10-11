"""Routes kept so clients of earlier releases keep working; new clients use their successors.

`GET /api/v1/google/configuration` answered whether Google could be connected before
`GET /api/v1/providers` listed every provider (ADR 0022). It is the only place outside the Google
package that names Google, and it answers exactly as before.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from calendar_sync.interfaces.api.dependencies import app_services, current_user
from calendar_sync.interfaces.api.routes.accounts import AuthorizationServices
from calendar_sync.interfaces.api.schemas import ProviderConfigurationResponse

Installation = Annotated[AuthorizationServices, Depends(app_services)]
router = APIRouter()

GOOGLE_SLUG = "google"


@router.get(
    "/api/v1/google/configuration",
    response_model=ProviderConfigurationResponse,
    dependencies=[Depends(current_user)],
)
def google_configuration(services: Installation) -> ProviderConfigurationResponse:
    """Whether Google can be connected, and the redirect URI to register with it."""
    descriptor = services.providers.at(GOOGLE_SLUG)
    connection = descriptor.connection if descriptor and descriptor.connectable else None
    return ProviderConfigurationResponse(
        configured=connection is not None,
        redirect_uri=connection.redirect_uri if connection is not None else None,
    )
