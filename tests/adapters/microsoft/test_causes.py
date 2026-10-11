"""Microsoft's reasons translated to Causes, read from codes only, never from message text
(ADR 0031, ADR 0032)."""

import logging

import pytest

from calendar_sync.application.causes import Cause, CauseOwner
from calendar_sync.application.errors import ProviderFailure
from calendar_sync.infrastructure.microsoft.causes import cause_of
from calendar_sync.infrastructure.microsoft.graph import GraphRefusal, TokenRefusal
from calendar_sync.infrastructure.microsoft.guide import MICROSOFT
from tests.adapters.microsoft.test_calendar_provider_contract import outlook
from tests.fake_microsoft_graph_api import graph_error
from tests.helpers import NOW, endpoint

# Every token endpoint answer the adapter maps, with the AADSTS number Microsoft documents for
# a case of it (https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes).
# The `error` field decides; the number is only logged.
TOKEN_CASES = [
    # An invalid or expired client secret, and an application deleted from its directory: only
    # the installation's administrator fixes them.
    ("invalid_client", 7000215, Cause.OAUTH_CLIENT_INVALID),
    ("invalid_client", 7000222, Cause.OAUTH_CLIENT_INVALID),
    ("unauthorized_client", 700016, Cause.OAUTH_CLIENT_INVALID),
    # A grant that expired, was revoked, ended with a password reset, or that the person's
    # organization has not consented to: the person reauthorizes.
    ("invalid_grant", 70008, Cause.ACCESS_REVOKED),
    ("invalid_grant", 700082, Cause.ACCESS_REVOKED),
    ("invalid_grant", 50173, Cause.ACCESS_REVOKED),
    ("invalid_grant", 65001, Cause.ACCESS_REVOKED),
    ("interaction_required", 50076, Cause.ACCESS_REVOKED),
    ("interaction_required", 53003, Cause.ACCESS_REVOKED),
    ("consent_required", 90094, Cause.ACCESS_REVOKED),
    ("temporarily_unavailable", 0, Cause.TEMPORARY),
]

# Every Graph answer the adapter maps: `error.code` and the HTTP status Graph documents
# (https://learn.microsoft.com/en-us/graph/errors, https://learn.microsoft.com/en-us/graph/throttling,
# and Exchange's response codes, which Outlook answers in `error.code`).
GRAPH_CASES = [
    (429, "TooManyRequests", Cause.RATE_LIMITED),
    (429, "ApplicationThrottled", Cause.RATE_LIMITED),
    (429, "activityLimitReached", Cause.RATE_LIMITED),
    (503, "ServiceNotAvailable", Cause.TEMPORARY),
    (504, "UnknownError", Cause.TEMPORARY),
    (500, "ErrorInternalServerError", Cause.TEMPORARY),
    (401, "InvalidAuthenticationToken", Cause.ACCESS_REVOKED),
    (403, "Authorization_RequestDenied", Cause.ACCESS_REVOKED),
    (403, "ErrorAccessDenied", Cause.CALENDAR_FORBIDDEN),
    (403, "accessDenied", Cause.CALENDAR_FORBIDDEN),
    (404, "ErrorItemNotFound", Cause.CALENDAR_NOT_FOUND),
    (404, "itemNotFound", Cause.CALENDAR_NOT_FOUND),
    (404, "ErrorFolderNotFound", Cause.CALENDAR_NOT_FOUND),
    (400, "MailboxNotEnabledForRESTAPI", Cause.UNKNOWN),
    (400, "ErrorInvalidRequest", Cause.UNKNOWN),
]


@pytest.mark.parametrize(("error", "code", "cause"), TOKEN_CASES)
def test_each_token_refusal_has_its_cause(error: str, code: int, cause: Cause) -> None:
    refusal = TokenRefusal(400, error, (code,))

    assert cause_of(refusal) is cause


@pytest.mark.parametrize(("status", "code", "cause"), GRAPH_CASES)
def test_each_graph_refusal_has_its_cause(status: int, code: str, cause: Cause) -> None:
    assert cause_of(GraphRefusal(status, (code,))) is cause


def test_the_innermost_code_graph_names_is_read_first() -> None:
    nested = GraphRefusal(403, ("accessDenied", "ErrorAccessDenied"))
    generic = GraphRefusal(400, ("invalidRequest", "ErrorItemNotFound"))

    assert cause_of(nested) is Cause.CALENDAR_FORBIDDEN
    assert cause_of(generic) is Cause.CALENDAR_NOT_FOUND


def test_a_missing_event_names_no_calendar() -> None:
    # A write to one event of a calendar that just answered: the event, not the calendar, is gone.
    assert cause_of(GraphRefusal(404, ("ErrorItemNotFound",)), event_scoped=True) is Cause.UNKNOWN


def test_no_answer_at_all_is_temporary() -> None:
    assert cause_of(GraphRefusal(None)) is Cause.TEMPORARY
    assert cause_of(TokenRefusal(None)) is Cause.TEMPORARY


def test_only_microsoft_client_failures_are_the_administrators() -> None:
    owners = {
        cause.owner
        for cause in {cause for *_, cause in TOKEN_CASES} | {cause for *_, cause in GRAPH_CASES}
    }
    assert Cause.OAUTH_CLIENT_INVALID.owner is CauseOwner.ADMINISTRATOR
    assert owners == {CauseOwner.ADMINISTRATOR, CauseOwner.USER}
    # Graph never answers that the API is off or a project quota is used up.
    raised = {cause for *_, cause in TOKEN_CASES} | {cause for *_, cause in GRAPH_CASES}
    assert raised <= set(MICROSOFT.cause_anchors)


def test_an_unrecognized_reason_is_logged_as_a_short_code_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="calendar_sync.infrastructure.microsoft.causes")

    graph = cause_of(GraphRefusal(400, ("ErrorSomethingNew",)))
    token = cause_of(TokenRefusal(400, "invalid_request", (9002313,)))
    sentence = cause_of(GraphRefusal(400, ("Not a code: private-marker said no",)))

    assert graph is token is sentence is Cause.UNKNOWN
    assert "reason=ErrorSomethingNew" in caplog.text
    assert "reason=invalid_request" in caplog.text
    assert "codes=AADSTS9002313" in caplog.text
    assert "private-marker" not in caplog.text
    assert "provider=outlook" in caplog.text


def test_a_failure_the_adapter_raises_carries_its_cause_without_microsofts_words() -> None:
    provider, graph = outlook()
    graph.refuse(graph_error(403, "ErrorAccessDenied"))

    with pytest.raises(ProviderFailure) as raised:
        provider.list_events(endpoint("personal-account", "personal-calendar"), NOW)

    assert raised.value.cause is Cause.CALENDAR_FORBIDDEN
    assert "private-marker" not in str(raised.value)
