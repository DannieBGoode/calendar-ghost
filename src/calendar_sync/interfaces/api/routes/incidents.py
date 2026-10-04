from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends

from calendar_sync.application.activity import OperationsQueries
from calendar_sync.interfaces.api.dependencies import app_services, require_admin
from calendar_sync.interfaces.api.schemas import IncidentResponse
from calendar_sync.interfaces.api.status_payload import message_response


class IncidentServices(Protocol):
    @property
    def operations(self) -> OperationsQueries: ...


Services = Annotated[IncidentServices, Depends(app_services)]
router = APIRouter()


@router.get(
    "/api/v1/incidents",
    response_model=list[IncidentResponse],
    dependencies=[Depends(require_admin)],
)
def list_incidents(services: Services) -> list[IncidentResponse]:
    return [
        IncidentResponse(
            id=incident.id,
            rule_id=incident.rule_id,
            category=incident.category,
            state=incident.state,
            summary=incident.summary,
            opened_at=incident.opened_at,
            updated_at=incident.updated_at,
            resolved_at=incident.resolved_at,
            resolution=incident.resolution,
            account_id=incident.account_id,
            message=message_response(incident.message),
        )
        for incident in services.operations.incidents()
    ]
