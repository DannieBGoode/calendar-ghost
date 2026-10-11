from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Query, status

from calendar_sync.application.operations.activity import OperationsQueries
from calendar_sync.application.operations.ports import IncidentSummary
from calendar_sync.interfaces.api.dependencies import current_user, user_services
from calendar_sync.interfaces.api.problems import problem
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
def list_incidents(
    services: Services,
    before: Annotated[str | None, Query(max_length=200)] = None,
) -> list[IncidentResponse]:
    """One page of incidents, open ones first; `before` names the last one of the page before."""
    return [_incident_response(incident) for incident in services.operations.incidents(before)]


@router.get(
    "/api/v1/incidents/{incident_id}",
    response_model=IncidentResponse,
    dependencies=[Depends(current_user)],
)
def get_incident(incident_id: str, services: Services) -> IncidentResponse:
    incident = services.operations.incident(incident_id)
    if incident is None:
        raise problem(status.HTTP_404_NOT_FOUND, "incident_not_found", "incident not found")
    return _incident_response(incident)


def _incident_response(incident: IncidentSummary) -> IncidentResponse:
    step = incident.step
    return IncidentResponse(
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
        step=step.value if step else None,
    )
