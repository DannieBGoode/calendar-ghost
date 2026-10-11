from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    log_level: str = "INFO"
    log_directory: Path | None = None
    secure_cookies: bool = False
    master_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/oauth/google/callback"
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_redirect_uri: str = "http://localhost:8000/api/v1/oauth/microsoft/callback"
    microsoft_tenant: str = "common"
    """Which Microsoft accounts may connect; "common" admits personal and work or school ones."""
    incident_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_sender: str = ""
    smtp_recipient: str = ""
    smtp_starttls: bool = True
    public_url: str = ""
    """Where people reach the Web UI, so incident email can link to their next step."""

    @classmethod
    def from_environment(cls) -> Settings:
        database_path = Path(os.environ.get("CALENDAR_SYNC_DATABASE_PATH", "./calendar-sync.db"))
        configured_logs = os.environ.get("CALENDAR_SYNC_LOG_DIR")
        log_directory = (
            database_path.parent / "logs"
            if configured_logs is None
            else (Path(configured_logs) if configured_logs.strip() else None)
        )
        return cls(
            database_path=database_path,
            log_level=os.environ.get("CALENDAR_SYNC_LOG_LEVEL", "INFO"),
            log_directory=log_directory,
            secure_cookies=os.environ.get("CALENDAR_SYNC_SECURE_COOKIES", "false").lower()
            in {"1", "true", "yes"},
            master_key=os.environ.get("CALENDAR_SYNC_MASTER_KEY", ""),
            google_client_id=os.environ.get("CALENDAR_SYNC_GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.environ.get("CALENDAR_SYNC_GOOGLE_CLIENT_SECRET", ""),
            google_redirect_uri=os.environ.get(
                "CALENDAR_SYNC_GOOGLE_REDIRECT_URI",
                "http://localhost:8000/api/v1/oauth/google/callback",
            ),
            microsoft_client_id=os.environ.get("CALENDAR_SYNC_MICROSOFT_CLIENT_ID", ""),
            microsoft_client_secret=os.environ.get("CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET", ""),
            microsoft_redirect_uri=os.environ.get(
                "CALENDAR_SYNC_MICROSOFT_REDIRECT_URI",
                "http://localhost:8000/api/v1/oauth/microsoft/callback",
            ),
            microsoft_tenant=os.environ.get("CALENDAR_SYNC_MICROSOFT_TENANT", "") or "common",
            incident_webhook_url=os.environ.get("CALENDAR_SYNC_INCIDENT_WEBHOOK_URL", ""),
            smtp_host=os.environ.get("CALENDAR_SYNC_SMTP_HOST", ""),
            smtp_port=int(os.environ.get("CALENDAR_SYNC_SMTP_PORT", "587")),
            smtp_username=os.environ.get("CALENDAR_SYNC_SMTP_USERNAME", ""),
            smtp_password=os.environ.get("CALENDAR_SYNC_SMTP_PASSWORD", ""),
            smtp_sender=os.environ.get("CALENDAR_SYNC_SMTP_SENDER", ""),
            smtp_recipient=os.environ.get("CALENDAR_SYNC_SMTP_RECIPIENT", ""),
            smtp_starttls=os.environ.get("CALENDAR_SYNC_SMTP_STARTTLS", "true").lower()
            in {"1", "true", "yes"},
            public_url=os.environ.get("CALENDAR_SYNC_PUBLIC_URL", ""),
        )
