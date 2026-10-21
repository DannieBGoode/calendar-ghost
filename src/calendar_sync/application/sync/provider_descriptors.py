"""What each calendar provider tells the rest of Calendar Ghost about itself.

A provider's package describes itself to bootstrap with one ProviderDescriptor: its Provider Kind,
the names messages use, where the troubleshooting guide explains each Cause it can raise, any
Installation Hint only it explains, and the adapters it offers, including how Instant Sync
watches its calendars and reads its notices. Routing, Installation Hints, the notice route, and
the Web API read the descriptors, so no code outside a provider's package asks which provider it
is talking to (ADR 0022, ADR 0036).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from calendar_sync.application.sync.account_ports import AccountAuthorization, AccountCalendars
from calendar_sync.application.sync.provider_ports import CalendarProvider
from calendar_sync.application.sync.watch_ports import CalendarWatcher, NoticeReader
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.causes import Cause


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
    """Where its connection flow lives, under `/api/v1/oauth/{slug}/`, and where its watch notices
    arrive, under `/api/v1/watch-notices/{slug}/`; it never changes, because every installation
    registers the callback there with the provider, and live watches point there."""
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
class ClientSecretExpiry:
    """When an installation's OAuth client secret expires, as its administrator recorded it.

    The provider does not say: reading it would need an application permission no calendar sync
    should ask for, so the administrator copies the date into the installation's settings.
    """

    provider: ProviderKind
    name: str
    """How English messages name the provider, such as "Example"."""
    expires: date


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
    secret_expires: date | None = None
    """When the installation's OAuth client secret expires, where the administrator recorded it,
    so Installation Health warns before every account of the provider stops at once."""
    watcher: CalendarWatcher | None = None
    """How Instant Sync watches the provider's calendars, when the provider can (ADR 0036)."""
    notice_reader: NoticeReader | None = None
    """How the provider's watch notices are read, at `/api/v1/watch-notices/{slug}/`."""

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

    @property
    def client_secrets(self) -> tuple[ClientSecretExpiry, ...]:
        """When each configured provider's client secret expires, where the administrator said."""
        return tuple(
            ClientSecretExpiry(d.kind, d.guide.display_name, d.secret_expires)
            for d in self.descriptors
            if d.configured and d.secret_expires is not None
        )

    def of(self, kind: ProviderKind) -> ProviderDescriptor | None:
        return next((d for d in self.descriptors if d.kind is kind), None)

    def at(self, slug: str) -> ProviderDescriptor | None:
        """The provider whose connection flow lives under `slug`, configured or not."""
        return next((d for d in self.descriptors if d.guide.slug == slug), None)

    def watching(self, slug: str) -> ProviderDescriptor | None:
        """The provider whose watch notices arrive under `slug`, when it reads them."""
        found = self.at(slug)
        return found if found is not None and found.notice_reader is not None else None

    def slug_of(self, kind: ProviderKind) -> str:
        """Where `kind`'s connection flow and watch notices live. Every provider this release
        knows has a descriptor, so a missing one is a composition error."""
        found = self.of(kind)
        if found is None:
            raise LookupError(f"no descriptor for provider {kind.value}")
        return found.guide.slug
