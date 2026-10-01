from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse

from calendar_sync.application.errors import FileLoggingOff, InvalidActivityAge, StorageBusy
from calendar_sync.application.ports import DatabaseUsage, LogUsage
from calendar_sync.application.storage import ACTIVITY_AGES, StorageAdministration
from calendar_sync.interfaces.api.dependencies import app_services, require_admin
from calendar_sync.interfaces.api.schemas import (
    ClearableActivityResponse,
    ClearActivityRequest,
    ClearedActivityResponse,
    DatabaseUsageResponse,
    LogUsageResponse,
    StorageResponse,
)


class StorageServices(Protocol):
    @property
    def storage(self) -> StorageAdministration: ...


Services = Annotated[StorageServices, Depends(app_services)]
router = APIRouter()
ADMIN = [Depends(require_admin)]


@router.get("/api/v1/storage", response_model=StorageResponse, dependencies=ADMIN)
def storage_usage(services: Services) -> StorageResponse:
    usage = services.storage.usage()
    return StorageResponse(
        database=_database(usage.database),
        logs=_logs(usage.logs) if usage.logs is not None else None,
        activity_ages=list(ACTIVITY_AGES),
    )


@router.get(
    "/api/v1/storage/activity", response_model=ClearableActivityResponse, dependencies=ADMIN
)
def clearable_activity(
    services: Services, older_than_days: Annotated[int, Query()]
) -> ClearableActivityResponse:
    try:
        entries = services.storage.clearable_activity(older_than_days)
    except InvalidActivityAge as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return ClearableActivityResponse(older_than_days=older_than_days, entries=entries)


@router.post(
    "/api/v1/storage/activity/clear",
    response_model=ClearedActivityResponse,
    dependencies=ADMIN,
)
def clear_activity(services: Services, payload: ClearActivityRequest) -> ClearedActivityResponse:
    try:
        cleared = services.storage.clear_activity(payload.older_than_days)
    except InvalidActivityAge as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except StorageBusy as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    return ClearedActivityResponse(removed=cleared.removed, database=_database(cleared.database))


@router.get("/api/v1/storage/logs", dependencies=ADMIN)
def download_logs(services: Services) -> StreamingResponse:
    try:
        chunks = services.storage.log_chunks()
    except FileLoggingOff as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    name = f"calendar-sync-logs-{datetime.now(UTC):%Y-%m-%d}.txt"
    return StreamingResponse(
        chunks,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.delete("/api/v1/storage/logs", status_code=status.HTTP_204_NO_CONTENT, dependencies=ADMIN)
def purge_logs(services: Services) -> Response:
    try:
        services.storage.purge_logs()
    except FileLoggingOff as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _database(usage: DatabaseUsage) -> DatabaseUsageResponse:
    return DatabaseUsageResponse(
        bytes=usage.bytes,
        reclaimable_bytes=usage.reclaimable_bytes,
        activity_entries=usage.activity_entries,
        oldest_activity_at=(
            usage.oldest_activity_at.isoformat() if usage.oldest_activity_at else None
        ),
    )


def _logs(usage: LogUsage) -> LogUsageResponse:
    return LogUsageResponse(
        bytes=usage.bytes,
        files=usage.files,
        oldest_at=usage.oldest_at.isoformat() if usage.oldest_at else None,
        newest_at=usage.newest_at.isoformat() if usage.newest_at else None,
    )
