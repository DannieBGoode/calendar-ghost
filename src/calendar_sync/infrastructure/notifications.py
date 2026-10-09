from __future__ import annotations

import json
import logging
import smtplib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from typing import Protocol
from urllib.request import Request, urlopen

from calendar_sync.application.installation_health import (
    InstallationIncident,
    InstallationIncidentKind,
)
from calendar_sync.application.ports import IncidentReport
from calendar_sync.domain.access import User, UserId, UserState

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IncidentNotification:
    rule_id: str | None
    """None for an Incident about a Connected Account, such as Lapsed Authorization."""
    category: str
    summary: str
    occurred_at: str


class IncidentNotifier:
    """Best-effort delivery to the installation's own channels: its webhook and SMTP recipient.

    They hear only of installation incidents, such as a stalled scheduler; each User hears of
    their own rules' and accounts' Incidents through `OwnerNotifier` (ADR 0030).
    """

    def __init__(self, channels: Sequence[NotificationChannel]) -> None:
        self._channels = tuple(channels)

    def installation_incident_opened(self, incident: InstallationIncident) -> None:
        self.notify(
            IncidentNotification(
                None,
                incident.kind.value,
                _INSTALLATION_SUMMARIES[incident.kind],
                incident.since.isoformat(),
            )
        )

    def notify(self, incident: IncidentNotification) -> None:
        for channel in self._channels:
            try:
                channel.send(incident)
            except Exception:
                logger.exception("Incident notification delivery failed")


_INSTALLATION_SUMMARIES = {
    InstallationIncidentKind.SCHEDULER_STALLED: "Scheduled synchronization stopped running",
}


class OwnerNotifier:
    """Emails one User about their own Incidents, unless they turned it off (ADR 0030).

    The Web UI keeps every Incident whether or not the email arrives.
    """

    def __init__(self, users: UserLookup, owner: UserId, server: SmtpServer) -> None:
        self._users = users
        self._owner = owner
        self._server = server

    def incident_opened(self, incident: IncidentReport, at: datetime) -> None:
        user = self._users.get(self._owner)
        if (
            user is None
            or user.email is None
            or not user.notify_by_email
            or user.state is not UserState.ACTIVE
        ):
            return
        try:
            self._server.send(user.email, _notification(incident, at))
        except Exception:
            logger.exception("Incident notification delivery failed")


class UserLookup(Protocol):
    def get(self, user_id: UserId) -> User | None: ...


def _notification(incident: IncidentReport, at: datetime) -> IncidentNotification:
    return IncidentNotification(
        incident.rule_id.value if incident.rule_id else None,
        incident.category,
        incident.summary,
        at.isoformat(),
    )


class NotificationChannel:
    def send(self, incident: IncidentNotification) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class WebhookChannel(NotificationChannel):
    url: str

    def send(self, incident: IncidentNotification) -> None:
        body = json.dumps(
            {
                "type": "calendar_sync.incident.opened",
                "rule_id": incident.rule_id,
                "category": incident.category,
                "summary": incident.summary,
                "occurred_at": incident.occurred_at,
            }
        ).encode()
        # The installation administrator configures this URL.
        request = Request(  # noqa: S310
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10):  # noqa: S310
            pass


@dataclass(frozen=True, slots=True)
class SmtpServer:
    """The installation's outgoing mail server; it sends Users' and the installation's mail."""

    host: str
    port: int
    sender: str
    username: str = ""
    password: str = field(default="", repr=False)
    use_starttls: bool = True

    def send(self, recipient: str, incident: IncidentNotification) -> None:
        message = EmailMessage()
        message["Subject"] = f"Calendar Ghost incident: {incident.summary}"
        message["From"] = self.sender
        message["To"] = recipient
        rule = (f"Rule: {incident.rule_id}",) if incident.rule_id else ()
        message.set_content(
            "\n".join(
                (
                    incident.summary,
                    "",
                    *rule,
                    f"Category: {incident.category}",
                    f"Opened: {incident.occurred_at}",
                    "",
                    "Open Calendar Ghost Activity for current status.",
                )
            )
        )
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            if self.use_starttls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)


@dataclass(frozen=True, slots=True)
class SmtpChannel(NotificationChannel):
    """The installation's configured SMTP recipient."""

    server: SmtpServer
    recipient: str

    def send(self, incident: IncidentNotification) -> None:
        self.server.send(self.recipient, incident)
