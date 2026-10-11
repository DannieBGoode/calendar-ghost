"""Incidents: what Calendar Ghost reports when a rule or account needs attention."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from calendar_sync.domain.causes import Cause, CauseOwner
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId


@dataclass(frozen=True, slots=True)
class IncidentMessage:
    """What an Incident says, as a stable code and parameters the Web UI translates (ADR 0026)."""

    code: str
    params: Mapping[str, str | int | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IncidentReport:
    """An Incident to open or refresh; repeated reports under one key update one Incident."""

    key: str
    rule_id: SyncRuleId | None
    """None for an Incident about a Connected Account rather than one rule."""
    category: str
    summary: str
    """Operational wording only; never an event title or other event content."""
    account_id: ConnectedAccountId | None = None
    """The Connected Account whose failure opened or last refreshed the Incident, if known."""
    message: IncidentMessage | None = None
    """The summary as a code and parameters; the English `summary` stays for email and logs."""
    cause: Cause | None = None
    """Why the provider failure behind it happened, when one did (ADR 0031)."""


class IncidentResolution(StrEnum):
    """Why an Incident resolved, so Activity can tell recovery apart from removal."""

    SYNC_SUCCEEDED = "sync_succeeded"
    BLOCKS_CLEARED = "blocks_cleared"
    RULE_REMOVED = "rule_removed"
    ACCESS_RESTORED = "access_restored"
    """The account's Lapsed Authorization cleared (ADR 0027)."""


class IncidentStep(StrEnum):
    """The one next step an Incident offers its owner, in the Web UI and in its email."""

    REAUTHORIZE = "reauthorize"
    """Google stopped accepting the account: reauthorize it in Settings."""
    RECOVER_RULE = "recover_rule"
    """Access is renewed, but the rule stays stopped until it is recovered."""
    REVIEW_RULE = "review_rule"
    """The rule stopped, or names a calendar its account may not use: review it."""
    SEE_BLOCKED = "see_blocked"
    """Events are still blocked: see them in the rule's Activity."""
    WAIT = "wait"
    """Nothing to do: Calendar Ghost tries again and closes it after the next successful sync."""
    ADMINISTRATOR = "administrator"
    """Only the installation's Google Cloud project, so its administrator, can fix it."""
    SEE_HISTORY = "see_history"
    """Resolved: the rule's Activity shows the runs around it."""


@dataclass(frozen=True, slots=True)
class AccountAuthorization:
    """One of a rule's Connected Accounts, as far as an Incident's next step weighs it."""

    account_id: ConnectedAccountId
    connected: bool
    authorized_at: datetime | None
    """When it was last connected or reauthorized; None while disconnected."""


@dataclass(frozen=True, slots=True)
class IncidentFacts:
    """What an Incident's next step depends on: what it records, and its rule as it is now."""

    category: str
    cause: Cause | None
    open: bool
    rule_exists: bool
    """Whether the Incident's rule still exists; False for an account's or the installation's."""
    rule_accounts: tuple[AccountAuthorization, ...] = ()
    failing_account: ConnectedAccountId | None = None
    """The account whose failure opened or last refreshed it, when that was recorded."""
    last_failure: datetime | None = None
    """When it last recorded a failure."""


# Failure kinds named by the Incidents they open; the application's ProviderFailureKind values.
AUTHORIZATION_CATEGORIES = frozenset({"authentication", "authorization"})
RETRIED_CATEGORIES = frozenset({"rate_limit", "temporary"})
BLOCKED_CATEGORY = "conflict"

_FIXES_ITSELF = frozenset({Cause.RATE_LIMITED, Cause.TEMPORARY})
_CALENDAR_CAUSES = frozenset({Cause.CALENDAR_FORBIDDEN, Cause.CALENDAR_NOT_FOUND})
# Steps taken on the Incident's rule, so offered only while it exists.
_RULE_STEPS = frozenset(
    {IncidentStep.RECOVER_RULE, IncidentStep.REVIEW_RULE, IncidentStep.SEE_BLOCKED}
)


def next_step(facts: IncidentFacts) -> IncidentStep | None:
    """The Incident's one next step (ADR 0033): its Cause first, as the provider gave it, then its
    category. A step on the rule needs the rule; None when nothing fits."""
    if not facts.open:
        return IncidentStep.SEE_HISTORY if facts.rule_exists else None
    step = _step_for(facts)
    if step in _RULE_STEPS and not facts.rule_exists:
        return None
    return step


def _step_for(facts: IncidentFacts) -> IncidentStep:
    cause = facts.cause
    if cause is not None and cause.owner is CauseOwner.ADMINISTRATOR:
        return IncidentStep.ADMINISTRATOR
    if cause in _CALENDAR_CAUSES:
        return IncidentStep.REVIEW_RULE
    if cause in _FIXES_ITSELF or facts.category in RETRIED_CATEGORIES:
        return IncidentStep.WAIT
    if facts.category == BLOCKED_CATEGORY:
        return IncidentStep.SEE_BLOCKED
    if cause is Cause.ACCESS_REVOKED or facts.category in AUTHORIZATION_CATEGORIES:
        if facts.rule_exists and access_renewed(facts):
            return IncidentStep.RECOVER_RULE
        return IncidentStep.REAUTHORIZE
    return IncidentStep.REVIEW_RULE


def access_renewed(facts: IncidentFacts) -> bool:
    """Whether the rule's access was renewed after the Incident last recorded a failure. An
    authorization failure leaves its account connected, so being connected proves nothing; only
    reauthorizing the account that failed does, with every account of the rule connected. When
    the failing account was not recorded, every account of the rule must have been reauthorized."""
    accounts = facts.rule_accounts
    if not accounts or not all(account.connected for account in accounts):
        return False
    renewed = {
        account.account_id
        for account in accounts
        if account.authorized_at is not None
        and facts.last_failure is not None
        and _utc(account.authorized_at) > _utc(facts.last_failure)
    }
    if facts.failing_account is None:
        # A rule whose calendars share one account names it twice; it counts once.
        return renewed == {account.account_id for account in accounts}
    return facts.failing_account in renewed


def _utc(moment: datetime) -> datetime:
    # Times recorded before time zones were stored are UTC, as Calendar Ghost wrote them.
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
