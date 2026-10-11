"""What each calendar provider tells the rest of Calendar Ghost about itself.

A provider's package describes itself to bootstrap with one ProviderDescriptor: its Provider Kind,
the names messages use, where the troubleshooting guide explains each Cause it can raise, any
Installation Hint only it explains, and the adapters it offers. Routing, Installation Hints, and
the Web API read the descriptors, so no code outside a provider's package asks which provider it
is talking to (ADR 0022).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from calendar_sync.application.causes import Cause
from calendar_sync.application.ports import AccountAuthorization, AccountCalendars, CalendarProvider
from calendar_sync.application.providers import ProviderKind


@dataclass(frozen=True, slots=True)
class GrantLifetime:
    """A provider that refuses grants a fixed time after they were given while the
    installation's app registration has some setting, such as an app still being tested. Two or
    more Users whose grants lapse that long after authorizing suggest it (ADR 0031)."""

    lifetime: timedelta
    tolerance: timedelta
    """How far from the lifetime a lapse still counts: a refused grant is noticed only at its next
    refresh, and a scheduler that was down notices it later."""
    anchor: str
    """The section of docs/troubleshooting.md that explains the setting."""


@dataclass(frozen=True, slots=True)
class ProviderGuide:
    """How Calendar Ghost names one provider and where its troubleshooting guide helps."""

    kind: ProviderKind
    slug: str
    """Where its connection flow lives, under `/api/v1/oauth/{slug}/`; it never changes, because
    every installation registers the callback there with the provider."""
    display_name: str
    """The provider's own name, which accounts are named after, such as "Example account"."""
    calendar_name: str
    """How English messages name its calendar service, such as in "Example Calendar is limiting
    requests"; the Web UI names it from its catalogs by Provider Kind."""
    cause_anchors: Mapping[Cause, str]
    """The section of docs/troubleshooting.md explaining each Cause this provider can raise. A
    Cause missing here is one it never raises."""
    grant_lifetime: GrantLifetime | None = None


@dataclass(frozen=True, slots=True)
class ProviderConnection:
    """How a User connects an account of the provider: its OAuth flow, which returns the browser
    to `redirect_uri`."""

    authorization: AccountAuthorization
    redirect_uri: str


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """One provider as its package describes it to bootstrap.

    Every provider this release knows has a descriptor. Without the installation master key no
    account can be stored, so it offers no connection flow or adapters; until the installation
    registers its OAuth client with the provider, it is not configured and nobody can connect it.
    """

    guide: ProviderGuide
    configured: bool = False
    """Whether the installation registered its OAuth client, so Users may connect accounts."""
    connection: ProviderConnection | None = None
    calendars: AccountCalendars | None = None
    provider: CalendarProvider | None = None

    @property
    def kind(self) -> ProviderKind:
        return self.guide.kind

    @property
    def connectable(self) -> bool:
        """Whether a User can connect an account of it now."""
        return self.configured and self.connection is not None


@dataclass(frozen=True, slots=True)
class ProviderDirectory:
    """Every provider's descriptor, in the order bootstrap composed them."""

    descriptors: Sequence[ProviderDescriptor] = field(default_factory=tuple)

    @property
    def guides(self) -> tuple[ProviderGuide, ...]:
        return tuple(descriptor.guide for descriptor in self.descriptors)

    @property
    def connectable(self) -> tuple[ProviderDescriptor, ...]:
        """The providers a User can connect an account of now."""
        return tuple(descriptor for descriptor in self.descriptors if descriptor.connectable)

    def of(self, kind: ProviderKind) -> ProviderDescriptor | None:
        return next((d for d in self.descriptors if d.kind is kind), None)

    def at(self, slug: str) -> ProviderDescriptor | None:
        """The provider whose connection flow lives under `slug`, configured or not."""
        return next((d for d in self.descriptors if d.guide.slug == slug), None)
