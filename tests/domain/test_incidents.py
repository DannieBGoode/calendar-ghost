from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.domain.causes import Cause
from calendar_sync.domain.incidents import (
    AccountAuthorization,
    IncidentCategory,
    IncidentFacts,
    IncidentStep,
    access_renewed,
    next_step,
)
from calendar_sync.domain.model import ConnectedAccountId

FAILED_AT = datetime(2026, 10, 1, 12, tzinfo=UTC)
FAILING = ConnectedAccountId("failing")
OTHER = ConnectedAccountId("other")


def account(
    account_id: ConnectedAccountId, *, renewed: bool, connected: bool = True
) -> AccountAuthorization:
    authorized = FAILED_AT + timedelta(hours=1 if renewed else -1)
    return AccountAuthorization(account_id, connected, authorized if connected else None)


def facts(
    category: str,
    cause: Cause | None = None,
    *,
    open: bool = True,
    rule_exists: bool = True,
    rule_accounts: tuple[AccountAuthorization, ...] = (),
    failing_account: ConnectedAccountId | None = FAILING,
) -> IncidentFacts:
    return IncidentFacts(
        IncidentCategory(category),
        cause,
        open=open,
        rule_exists=rule_exists,
        rule_accounts=rule_accounts,
        failing_account=failing_account,
        last_failure=FAILED_AT,
    )


@pytest.mark.parametrize(
    ("incident", "step"),
    [
        # Only the installation's Google Cloud project can fix it, whatever the category says.
        (facts("authorization", Cause.API_DISABLED), IncidentStep.ADMINISTRATOR),
        (facts("rate_limit", Cause.QUOTA_EXCEEDED), IncidentStep.ADMINISTRATOR),
        # A calendar the account may no longer use: choose another one on the rule.
        (facts("authorization", Cause.CALENDAR_FORBIDDEN), IncidentStep.REVIEW_RULE),
        (facts("permanent", Cause.CALENDAR_NOT_FOUND), IncidentStep.REVIEW_RULE),
        # It fixes itself.
        (facts("rate_limit", Cause.RATE_LIMITED), IncidentStep.WAIT),
        (facts("temporary"), IncidentStep.WAIT),
        (facts("permanent", Cause.TEMPORARY), IncidentStep.WAIT),
        # Events still blocked.
        (facts("conflict"), IncidentStep.SEE_BLOCKED),
        # Google stopped accepting the account.
        (facts("authentication", Cause.ACCESS_REVOKED), IncidentStep.REAUTHORIZE),
        (facts("authorization"), IncidentStep.REAUTHORIZE),
        (facts("authentication", rule_exists=False), IncidentStep.REAUTHORIZE),
        # Anything else stops the rule until it is reviewed.
        (facts("permanent", Cause.UNKNOWN), IncidentStep.REVIEW_RULE),
        (facts("infrastructure"), IncidentStep.REVIEW_RULE),
    ],
)
def test_an_open_incident_has_one_next_step(incident: IncidentFacts, step: IncidentStep) -> None:
    assert next_step(incident) is step


def test_a_rule_step_needs_the_rule() -> None:
    assert next_step(facts("conflict", rule_exists=False)) is None
    assert next_step(facts("permanent", rule_exists=False)) is None
    assert next_step(facts("authorization", Cause.CALENDAR_FORBIDDEN, rule_exists=False)) is None


def test_renewed_access_leaves_only_the_rule_to_recover() -> None:
    renewed = (account(FAILING, renewed=True), account(OTHER, renewed=False))
    assert next_step(facts("authentication", rule_accounts=renewed)) is IncidentStep.RECOVER_RULE


def test_a_resolved_incident_leads_to_its_rules_history_while_the_rule_exists() -> None:
    assert next_step(facts("temporary", open=False)) is IncidentStep.SEE_HISTORY
    assert next_step(facts("temporary", open=False, rule_exists=False)) is None


def test_access_is_renewed_when_the_failing_account_was_reauthorized_since() -> None:
    assert access_renewed(facts("authentication", rule_accounts=(account(FAILING, renewed=True),)))
    assert not access_renewed(
        facts("authentication", rule_accounts=(account(FAILING, renewed=False),))
    )


def test_access_is_not_renewed_while_any_rule_account_is_disconnected() -> None:
    accounts = (account(FAILING, renewed=True), account(OTHER, renewed=True, connected=False))
    assert not access_renewed(facts("authentication", rule_accounts=accounts))


def test_without_a_failing_account_every_rule_account_must_be_reauthorized() -> None:
    one = (account(FAILING, renewed=True), account(OTHER, renewed=False))
    both = (account(FAILING, renewed=True), account(OTHER, renewed=True))
    assert not access_renewed(facts("authentication", rule_accounts=one, failing_account=None))
    assert access_renewed(facts("authentication", rule_accounts=both, failing_account=None))


def test_access_is_not_renewed_for_a_rule_with_no_accounts_known() -> None:
    assert not access_renewed(facts("authentication"))


def test_a_time_recorded_without_a_time_zone_is_read_as_utc() -> None:
    renewed = (account(FAILING, renewed=True),)
    naive = replace(
        facts("authentication", rule_accounts=renewed), last_failure=datetime(2026, 10, 1, 12)
    )
    assert access_renewed(naive)


def test_one_account_behind_both_calendars_counts_once() -> None:
    # Both calendars of the rule belong to one account, which was reauthorized since.
    shared = (account(FAILING, renewed=True), account(FAILING, renewed=True))
    assert access_renewed(facts("authentication", rule_accounts=shared, failing_account=None))


@pytest.mark.parametrize("value", ["authentication", "rate_limit", "conflict"])
def test_a_stored_category_reads_as_itself(value: str) -> None:
    assert IncidentCategory.read(value).value == value


@pytest.mark.parametrize("value", ["provider", "ownership", "", None, 3])
def test_a_category_this_release_does_not_know_reads_as_unknown(value: object) -> None:
    # Earlier releases stored categories no longer written, and storage does not constrain them.
    assert IncidentCategory.read(value) is IncidentCategory.UNKNOWN


def test_an_unknown_category_stops_its_rule_until_it_is_reviewed() -> None:
    assert next_step(facts("unknown")) is IncidentStep.REVIEW_RULE
    assert next_step(facts("unknown", rule_exists=False)) is None
