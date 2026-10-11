"""The Microsoft package as bootstrap composes it: one descriptor (ADR 0022, ADR 0032)."""

from __future__ import annotations

from dataclasses import dataclass

from calendar_sync.application.provider_descriptors import ProviderDescriptor
from calendar_sync.infrastructure.microsoft.guide import MICROSOFT
from calendar_sync.infrastructure.oauth import OAuthClientConfig


@dataclass(frozen=True, slots=True)
class MicrosoftClient:
    """The installation's Microsoft Entra application, and which accounts may sign in to it."""

    oauth: OAuthClientConfig
    tenant: str = "common"


def microsoft_provider(client: MicrosoftClient) -> ProviderDescriptor:
    """Microsoft's descriptor; it is configured once its application is registered."""
    return ProviderDescriptor(MICROSOFT, configured=client.oauth.complete)
