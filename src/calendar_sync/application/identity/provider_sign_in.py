"""Browser-bound provider sign-in orchestration, separate from calendar consent."""

import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from calendar_sync.application.identity.provider_sign_in_ports import (
    AdmissionCommand,
    BeginIntent,
    ProviderAdmission,
    ProviderAuthorization,
    ProviderCallback,
    ProviderFlows,
    ProviderSignInRefused,
    ProviderSignInResult,
    ProviderSignInSetting,
    ProviderSignInSettings,
)


class ProviderProofSecrets(Protocol):
    def nonce(self, state: str, provider: str) -> str: ...

    def verifier(self, state: str, provider: str) -> str: ...


@dataclass(slots=True)
class BeginProviderSignIn:
    providers: Mapping[str, ProviderAuthorization]
    flows: ProviderFlows
    proofs: ProviderProofSecrets
    settings: ProviderSignInSettings

    def execute(self, intent: BeginIntent) -> str:
        provider = self.providers.get(intent.provider)
        if provider is None:
            raise ProviderSignInRefused
        configuration = _require_enabled(self.settings, intent.provider)
        if intent.invitation is not None and not configuration.can_verify_email:
            raise ProviderSignInRefused
        state = secrets.token_urlsafe(32)
        self.flows.begin(intent, state)
        return provider.begin(
            state,
            self.proofs.nonce(state, intent.provider),
            self.proofs.verifier(state, intent.provider),
        )


@dataclass(slots=True)
class CompleteProviderSignIn:
    providers: Mapping[str, ProviderAuthorization]
    flows: ProviderFlows
    proofs: ProviderProofSecrets
    settings: ProviderSignInSettings
    admission: ProviderAdmission

    def execute(self, callback: ProviderCallback) -> ProviderSignInResult:
        provider = self.providers.get(callback.provider)
        if provider is None:
            raise ProviderSignInRefused
        flow = self.flows.consume(callback)
        if flow is None:
            raise ProviderSignInRefused
        _require_enabled(self.settings, callback.provider)
        claims = provider.exchange(
            callback.code,
            self.proofs.nonce(callback.state, callback.provider),
            self.proofs.verifier(callback.state, callback.provider),
        )
        return self.admission.complete(AdmissionCommand(claims, flow, None))


def _require_enabled(settings: ProviderSignInSettings, provider: str) -> ProviderSignInSetting:
    for item in settings.list():
        if item.provider == provider and item.enabled and item.available:
            return item
    raise ProviderSignInRefused
