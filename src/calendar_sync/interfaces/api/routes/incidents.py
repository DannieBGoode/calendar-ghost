from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends

from calendar_sync.application.operations.activity import OperationsQueries
from calendar_sync.interfaces.api.dependencies import current_user, user_services
from calendar_sync.interfaces.api.schemas import IncidentResponse
from calendar_sync.interfaces.api.status_payload import message_response


class IncidentServices(Protocol):
    @property
    def operations(self) -> OperationsQueries: ...


Services = Annotated[IncidentServices, Depends(user_services)]
router = APIRouter()


@router.get(
    "/api/v1/incidents",
    response_model=list[IncidentResponse],
    dependencies=[Depends(current_user)],
)
def list_incidents(services: Services) -> list[IncidentResponse]:
    return [
        IncidentResponse(
            id=incident.id,
            rule_id=incident.rule_id,
            category=incident.category,
            state=incident.state,
            summary=incident.summary,
            opened_at=incident.opened_at.isoformat(),
            updated_at=incident.updated_at.isoformat(),
            resolved_at=incident.resolved_at.isoformat() if incident.resolved_at else None,
            resolution=incident.resolution,
            account_id=incident.account_id,
            message=message_response(incident.message),
            cause=incident.cause.value if incident.cause else None,
        )
        for incident in services.operations.incidents()
    ]
