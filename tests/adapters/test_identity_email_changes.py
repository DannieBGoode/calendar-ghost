"""Email-change delivery revalidates ownership before exposing a one-time proof."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from calendar_sync.application.identity.email_changes import EmailChangeMailRequest
from calendar_sync.application.identity.identity_email import IdentityEmailSetup
from calendar_sync.domain.access import UserState
from calendar_sync.infrastructure.identity_email_changes import EmailChangeDelivery
from tests.adapters.test_email_change_store import setup
from tests.adapters.test_users_store import FIRST, SECOND


@pytest.mark.parametrize(
    "stale", ["replacement", "cancel", "disable", "password", "reset", "fingerprint"]
)
def test_worker_rechecks_current_request_and_revision(tmp_path: Path, stale: str) -> None:
    _, clock, h, store, expected, session = setup(tmp_path)
    pending = store.request(expected, "new@example.test", session.token)
    sender = Mock()
    delivery = EmailChangeDelivery(store, IdentityEmailSetup("current", None), sender)
    request = EmailChangeMailRequest(pending.id, "current")
    replacement = None
    if stale == "replacement":
        replacement = store.request(expected, "replacement@example.test", session.token)
    elif stale == "cancel":
        store.cancel(SECOND.id, pending.id)
    elif stale == "disable":
        h.users.set_state(SECOND.id, UserState.DISABLED)
    elif stale == "password":
        h.changes.change_password(expected, "new-hash", session.token)
    elif stale == "reset":
        reset = h.links.issue(SECOND.id, FIRST.id, clock.now())
        h.links.reset(reset.token, "reset-hash")
    else:
        request = replace(request, fingerprint="stale")
    assert delivery.prepare(request) is None
    sender.send_email_change.assert_not_called()
    if replacement:
        assert store.pending(SECOND.id) == replacement
        assert delivery.prepare(EmailChangeMailRequest(replacement.id, "current")) is not None


def test_delivery_ignores_notification_preferences_and_uses_proposed_address(
    tmp_path: Path,
) -> None:
    _, _, h, store, expected, session = setup(tmp_path)
    h.users.set_notification_email(SECOND.id, False)
    pending = store.request(expected, "new@example.test", session.token)
    sender = Mock()
    delivery = EmailChangeDelivery(store, IdentityEmailSetup("current", None), sender)
    prepared = delivery.prepare(EmailChangeMailRequest(pending.id, "current"))
    assert prepared
    delivery.send(prepared)
    sender.send_email_change.assert_called_once_with("new@example.test", prepared.token)
    assert prepared.recipient not in repr(prepared)
    assert prepared.token not in repr(prepared)
