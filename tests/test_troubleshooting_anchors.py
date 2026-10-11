"""Every troubleshooting link the service hands out reaches a section of the guide."""

import re
from pathlib import Path

import pytest

from calendar_sync.application.causes import Cause
from calendar_sync.application.installation_hints import UNRECOGNIZED_ANCHOR
from calendar_sync.application.provider_descriptors import ProviderGuide
from calendar_sync.application.providers import ProviderKind
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import calendar_providers
from calendar_sync.infrastructure.scheduling import SystemClock

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "troubleshooting.md"
# Every provider this release composes, as bootstrap describes it.
GUIDES = calendar_providers(Settings(Path("unused.db")), None, SystemClock()).guides


def github_anchor(heading: str) -> str:
    """GitHub's anchor for a heading: lowercase, punctuation dropped, spaces as hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def guide_anchors() -> set[str]:
    return {
        github_anchor(line.lstrip("#"))
        for line in GUIDE.read_text().splitlines()
        if re.match(r"#{2,4} ", line)
    }


def test_the_anchor_rule_matches_githubs() -> None:
    assert github_anchor("The Google Cloud project's daily quota is used up") == (
        "the-google-cloud-projects-daily-quota-is-used-up"
    )


def test_every_provider_is_described() -> None:
    assert {guide.kind for guide in GUIDES} == set(ProviderKind)


@pytest.mark.parametrize("guide", GUIDES, ids=lambda guide: guide.kind.value)
def test_every_section_a_provider_links_to_is_in_the_guide(guide: ProviderGuide) -> None:
    lifetime = [guide.grant_lifetime.anchor] if guide.grant_lifetime else []
    linked = {*guide.cause_anchors.values(), *lifetime, UNRECOGNIZED_ANCHOR}

    assert linked <= guide_anchors(), linked - guide_anchors()


@pytest.mark.parametrize("guide", GUIDES, ids=lambda guide: guide.kind.value)
def test_every_cause_a_provider_raises_unknown_included_has_a_section(guide: ProviderGuide) -> None:
    # A provider's failures it does not recognize, and its limits that fix themselves, are
    # always possible, so each provider explains them.
    assert {Cause.UNKNOWN, Cause.RATE_LIMITED, Cause.TEMPORARY} <= set(guide.cause_anchors)


def test_the_web_ui_reads_how_to_fix_sections_from_the_server() -> None:
    # The Web UI links each administrator's Cause where its provider's guide says, through
    # GET /api/v1/providers, so it names no section of its own.
    causes = Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "causes.ts"
    anchors = {anchor for guide in GUIDES for anchor in guide.cause_anchors.values()}

    assert not any(anchor in causes.read_text() for anchor in anchors)
