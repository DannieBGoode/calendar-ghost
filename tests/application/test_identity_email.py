"""Identity email admission and delivery never confuse queuing with readiness."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.identity_email import (
    DeliverIdentityEmailTest,
    EmailTest,
    EmailTestState,
    IdentityEmailNotConfigured,
    IdentityEmailQueueBusy,
    IdentityEmailReason,
    IdentityEmailSetup,
    IdentityEmailTestThrottled,
    RequestIdentityEmailTest,
    ShowIdentityEmail,
)
from calendar_sync.application.identity.ports import UserDirectory
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters
from calendar_sync.domain.access import Role, UserState
from tests.adapters.test_users_store import FIRST
from tests.helpers import NOW
from tests.identity_email_fakes import MemoryIdentityEmailTests


class FixedClock:
    def now(self) -> datetime:
        return NOW


class Queue:
    def __init__(self) -> None:
        self.tests: list[EmailTest] = []
        self.accept = True

    def submit(self, test: EmailTest) -> bool:
        self.tests.append(test)
        return self.accept

    def state(self, actor: object) -> EmailTestState:
        return EmailTestState.QUEUED if self.tests else EmailTestState.IDLE


class Sender:
    def __init__(self) -> None:
        self.recipients: list[str] = []

    def send_test(self, recipient: str) -> None:
        self.recipients.append(recipient)

    def send_reset(self, recipient: str, token: str) -> None:
        self.recipients.append(recipient)

    def send_registration(self, recipient: str, token: str) -> None:
        self.recipients.append(recipient)

    def send_email_change(self, recipient: str, token: str) -> None:
        self.recipients.append(recipient)

    def send_email_changed(self, recipient: str) -> None:
        self.recipients.append(recipient)


def services(tmp_path: Path) -> tuple[UserDirectory, MemoryIdentityEmailTests, Queue, FixedClock]:
    adapters = build_adapters(Settings(tmp_path / "identity.db"))
    adapters.users.add(FIRST, "synthetic")
    tests = MemoryIdentityEmailTests({FIRST.id: FIRST})
    return adapters.users, tests, Queue(), FixedClock()


def test_only_active_administrators_can_test_email(tmp_path: Path) -> None:
    users, tests, queue, clock = services(tmp_path)
    request = RequestIdentityEmailTest(
        users, tests, IdentityEmailSetup("current", None), queue, clock
    )
    show = ShowIdentityEmail(users, tests, request.setup, queue)
    for user in (replace(FIRST, role=Role.USER), replace(FIRST, state=UserState.DISABLED)):
        # A second administrator permits changing the first administrator's state/role.
        if users.count() == 1:
            users.add(
                replace(FIRST, id=type(FIRST.id)("second"), email="second@example.test"), "hash"
            )
        users.set_role(FIRST.id, user.role)
        users.set_state(FIRST.id, user.state)
        with pytest.raises(AdministratorRequired):
            request.execute(FIRST.id)
        with pytest.raises(AdministratorRequired):
            show.execute(FIRST.id)
    assert not tests.attempts


def test_unconfigured_email_never_admits(tmp_path: Path) -> None:
    users, tests, queue, clock = services(tmp_path)
    setup = IdentityEmailSetup(None, IdentityEmailReason.SMTP_MISSING)
    with pytest.raises(IdentityEmailNotConfigured):
        RequestIdentityEmailTest(users, tests, setup, queue, clock).execute(FIRST.id)
    assert not tests.attempts
    status = ShowIdentityEmail(users, tests, setup, queue).execute(FIRST.id)
    assert not status.configured
    assert status.tested_at is None


def test_admission_counts_before_queue_submission(tmp_path: Path) -> None:
    users, tests, queue, clock = services(tmp_path)
    queue.accept = False
    with pytest.raises(IdentityEmailQueueBusy):
        RequestIdentityEmailTest(
            users, tests, IdentityEmailSetup("current", None), queue, clock
        ).execute(FIRST.id)
    assert len(tests.attempts) == 1
    assert tests.tested_at("current") is None


def test_dispatch_rechecks_actor_and_configuration(tmp_path: Path) -> None:
    users, tests, _, clock = services(tmp_path)
    test = tests.admit(FIRST.id, "current", NOW)
    sender = Sender()
    delivery = DeliverIdentityEmailTest(
        users, tests, IdentityEmailSetup("changed", None), sender, clock
    )
    assert delivery.prepare(test) is None
    delivery = replace(delivery, setup=IdentityEmailSetup("current", None))
    assert delivery.prepare(test) is not None
    users.set_email(FIRST.id, "new@example.test")
    prepared = delivery.prepare(test)
    assert prepared is not None
    assert prepared.recipient == "new@example.test"
    users.add(replace(FIRST, id=type(FIRST.id)("second"), email="second@example.test"), "hash")
    users.set_state(FIRST.id, UserState.DISABLED)
    assert delivery.prepare(test) is None


def test_test_mail_ignores_notification_preference(tmp_path: Path) -> None:
    users, tests, _, clock = services(tmp_path)
    users.set_notification_email(FIRST.id, False)
    sender = Sender()
    delivery = DeliverIdentityEmailTest(
        users, tests, IdentityEmailSetup("current", None), sender, clock
    )
    prepared = delivery.prepare(tests.admit(FIRST.id, "current", NOW))
    assert prepared is not None
    delivery.send(prepared)
    assert sender.recipients == [FIRST.email]
    assert delivery.complete(prepared)
    assert tests.tested_at("current") == NOW


@pytest.mark.parametrize("state", [EmailTestState.QUEUED, EmailTestState.SENDING])
def test_known_pending_requests_preserve_allowance(tmp_path: Path, state: EmailTestState) -> None:
    users, tests, queue, clock = services(tmp_path)
    request = RequestIdentityEmailTest(
        users, tests, IdentityEmailSetup("current", None), queue, clock
    )
    with patch.object(queue, "state", return_value=state):
        for _ in range(4):
            with pytest.raises(IdentityEmailQueueBusy):
                request.execute(FIRST.id)
    assert not tests.attempts
    request.execute(FIRST.id)
    assert len(tests.attempts) == 1


@pytest.mark.parametrize("observed", [EmailTestState.IDLE, EmailTestState.ACCEPTED])
def test_submission_refusal_keeps_admission_charged(
    tmp_path: Path, observed: EmailTestState
) -> None:
    users, tests, queue, clock = services(tmp_path)
    request = RequestIdentityEmailTest(
        users, tests, IdentityEmailSetup("current", None), queue, clock
    )
    # The queue may fill, or another request may win, after the nonpending precheck.
    queue.accept = False
    with patch.object(queue, "state", return_value=observed):
        for _ in range(3):
            with pytest.raises(IdentityEmailQueueBusy):
                request.execute(FIRST.id)
        with pytest.raises(IdentityEmailTestThrottled):
            request.execute(FIRST.id)
    assert len(tests.attempts) == len(queue.tests) == 3
