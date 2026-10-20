from __future__ import annotations

import json
import logging
import smtplib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import quote
from urllib.request import Request, urlopen

from calendar_sync.application.operations.installation_health import (
    InstallationIncident,
    InstallationIncidentKind,
)
from calendar_sync.domain.access import User, UserId, UserState
from calendar_sync.domain.incidents import IncidentFacts, IncidentReport, IncidentStep, next_step
from calendar_sync.domain.plan_hold import PlanNotice, PlanNoticeKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IncidentNotification:
    rule_id: str | None
    """None for an Incident about a Connected Account, such as Lapsed Authorization."""
    category: str
    summary: str
    occurred_at: str
    link: str | None = None
    """The Web UI page holding the owner's next step; it names no calendar, account, or event."""


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
                _installation_summary(incident),
                incident.since.isoformat(),
            )
        )

    def notify(self, incident: IncidentNotification) -> None:
        for channel in self._channels:
            try:
                channel.send(incident)
            except Exception:
                logger.exception("Incident notification delivery failed")


def _installation_summary(incident: InstallationIncident) -> str:
    secret = incident.secret
    if incident.kind is InstallationIncidentKind.CLIENT_SECRET_EXPIRING and secret is not None:
        if incident.expired:
            return (
                f"The {secret.name} client secret expired on {secret.expires.isoformat()}, so "
                f"every {secret.name} account stopped; put a new one in place to restart them"
            )
        return (
            f"The {secret.name} client secret expires on {secret.expires.isoformat()}; "
            "put a new one in place before then"
        )
    return "Scheduled synchronization stopped running"


class OwnerNotifier:
    """Emails one User about their own Incidents, unless they turned it off (ADR 0030).

    The Web UI keeps every Incident whether or not the email arrives.
    """

    def __init__(
        self,
        users: UserLookup,
        owner: UserId,
        server: SmtpServer,
        public_url: str | None = None,
    ) -> None:
        self._users = users
        self._owner = owner
        self._server = server
        # Without the installation's public address the email has no link, as before.
        self._public_url = public_url

    def incident_opened(self, incident: IncidentReport, at: datetime) -> None:
        user = self._users.get(self._owner)
        if (
            user is None
            or user.email is None
            or not user.notify_by_email
            or user.state is not UserState.ACTIVE
        ):
            return
        notification = _notification(incident, at)
        if self._public_url is not None:
            notification = replace(notification, link=self._public_url + _step_path(incident))
        try:
            self._server.send(user.email, notification)
        except Exception:
            logger.exception("Incident notification delivery failed")

    def plan_changed(self, notice: PlanNotice) -> None:
        user = self._users.get(self._owner)
        if (
            user is None
            or user.email is None
            or not user.notify_by_email
            or user.state is not UserState.ACTIVE
        ):
            return
        link = self._public_url + "/settings/account#your-plan" if self._public_url else None
        try:
            self._server.send_plan(user.email, notice, link)
        except Exception as error:
            logger.error("Plan notice delivery failed (%s)", type(error).__name__)


class UserLookup(Protocol):
    def get(self, user_id: UserId) -> User | None: ...


def _notification(incident: IncidentReport, at: datetime) -> IncidentNotification:
    return IncidentNotification(
        incident.rule_id.value if incident.rule_id else None,
        incident.category,
        incident.summary,
        at.isoformat(),
    )


def _step_path(incident: IncidentReport) -> str:
    """The page holding the owner's one next step, as the domain decides it for the Web UI too
    (ADR 0033): their calendar connections to reauthorize, the rule to review, its blocked events,
    or the Overview when there is nothing for them to do. Its rule exists, having just run, and
    nobody has renewed access since it failed. A rule is named only by its internal identifier."""
    step = next_step(
        IncidentFacts(
            incident.category, incident.cause, open=True, rule_exists=incident.rule_id is not None
        )
    )
    rule = quote(incident.rule_id.value, safe="") if incident.rule_id else ""
    if step is IncidentStep.REAUTHORIZE:
        return "/settings/connections"
    if step in {IncidentStep.RECOVER_RULE, IncidentStep.REVIEW_RULE}:
        return f"/rules/{rule}"
    if step is IncidentStep.SEE_BLOCKED:
        return f"/activity?rule={rule}&show=blocked"
    return "/"


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
        next_step = (
            f"What to do next: {incident.link}"
            if incident.link
            else "Open Calendar Ghost Activity for current status."
        )
        message.set_content(
            "\n".join(
                (
                    incident.summary,
                    "",
                    *rule,
                    f"Category: {incident.category}",
                    f"Opened: {incident.occurred_at}",
                    "",
                    next_step,
                )
            )
        )
        self._deliver(message)

    def send_plan(self, recipient: str, notice: PlanNotice, link: str | None) -> None:
        message = EmailMessage()
        message["Subject"] = "Calendar Ghost: your plan"
        message["From"] = self.sender
        message["To"] = recipient
        body = _plan_body(notice)
        if link is not None:
            body += "\n\n" + link
        message.set_content(body)
        self._deliver(message)

    def _deliver(self, message: EmailMessage) -> None:
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


def _plan_body(notice: PlanNotice) -> str:
    if notice.kind is PlanNoticeKind.RULES_HELD:
        return (
            f"{notice.held} of your rules are now held by your plan. They keep their events "
            "and resume by themselves when your plan has room."
        )
    at = notice.holds_at.astimezone(UTC)
    body = f"{notice.count} of your rules count toward your plan, which allows {notice.limit}."
    deadline = at.strftime("%Y-%m-%d at %H:%M UTC")
    if notice.held:
        body += f" After {deadline}, {notice.held} of them will be held until your plan has room."
    else:
        body += f" Your grace ends after {deadline}."
    body += " You can choose which rules keep syncing under Settings, Your account, Your plan."
    if notice.reserved:
        body += (
            f" {notice.reserved} replacement drafts will also give up their reserved places "
            "and will need a Start within your plan's limit."
        )
    return body
