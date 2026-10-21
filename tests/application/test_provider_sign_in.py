"""Application orchestration consumes the flow before provider I/O."""

from unittest.mock import Mock

import pytest

from calendar_sync.application.identity.provider_sign_in import (
    BeginProviderSignIn,
    CompleteProviderSignIn,
)
from calendar_sync.application.identity.provider_sign_in_ports import (
    AdmissionCommand,
    BeginIntent,
    BrowserProof,
    ProviderCallback,
    ProviderSignInRefused,
)


def test_begin_derives_bound_secrets_and_returns_provider_url() -> None:
    authorization, flows, secrets = Mock(), Mock(), Mock()
    authorization.begin.return_value = "https://provider.test/authorize"
    begin = BeginProviderSignIn({"google": authorization}, flows, secrets)
    intent = BeginIntent("google", BrowserProof("browser"))
    assert begin.execute(intent) == "https://provider.test/authorize"
    state = flows.begin.call_args.args[1]
    assert len(state) == 43
    secrets.nonce.assert_called_once_with(state, "google")
    secrets.verifier.assert_called_once_with(state, "google")


def test_exchange_only_after_flow_claim() -> None:
    authorization, flows, secrets, admission = Mock(), Mock(), Mock(), Mock()
    complete = CompleteProviderSignIn({"google": authorization}, flows, secrets, admission)
    callback = ProviderCallback("google", "state", "code", BrowserProof("browser"))
    flows.consume.return_value = None
    with pytest.raises(ProviderSignInRefused):
        complete.execute(callback)
    authorization.exchange.assert_not_called()
    admission.complete.assert_not_called()


def test_complete_passes_immutable_claimed_flow_to_final_writer() -> None:
    authorization, flows, secrets, admission = Mock(), Mock(), Mock(), Mock()
    complete = CompleteProviderSignIn({"google": authorization}, flows, secrets, admission)
    callback = ProviderCallback("google", "state", "code", BrowserProof("browser"))
    assert complete.execute(callback) == admission.complete.return_value
    admission.complete.assert_called_once_with(
        AdmissionCommand(authorization.exchange.return_value, flows.consume.return_value, None)
    )


def test_confirmation_throttle_precedes_lookup_and_password_work() -> None:
    from calendar_sync.application.identity.errors import SignInThrottled
    from calendar_sync.application.identity.provider_links import ConfirmProviderLink

    users, passwords, throttle, flows, admission = Mock(), Mock(), Mock(), Mock(), Mock()
    throttle.wait.return_value = 10
    confirm = ConfirmProviderLink(users, passwords, throttle, flows, admission)
    with pytest.raises(SignInThrottled):
        confirm.execute(
            BrowserProof("browser"), "pending", "user@example.test", "password", "client"
        )
    users.sign_in_credentials.assert_not_called()
    passwords.verify.assert_not_called()
    flows.pending.assert_not_called()


def test_provider_maintenance_is_independent_and_bounded() -> None:
    from calendar_sync.infrastructure.identity_registration import RegistrationMaintenance
    from tests.fakes.oidc import NOW

    proofs, admission, flows, limits = Mock(), Mock(), Mock(), Mock()
    proofs.purge.side_effect = RuntimeError("synthetic")
    admission.purge.return_value = 0
    flows.purge.return_value = 250
    limits.purge.return_value = 0
    cleanup = RegistrationMaintenance(None, proofs, admission, (flows, limits))
    assert cleanup.purge(NOW, 1000)
    for store in (proofs, admission, flows, limits):
        store.purge.assert_called_once_with(NOW, 250)
