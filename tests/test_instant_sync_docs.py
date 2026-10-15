"""The Instant Sync guide holds every section the API and the Web UI link to, and the site
renders it where the Web UI opens it."""

import re
from pathlib import Path

from calendar_sync.domain.watches import AVAILABILITY_ANCHORS

REPOSITORY = Path(__file__).resolve().parents[1]
GUIDE = REPOSITORY / "docs" / "instant-sync.md"
# Each reason a rule may sync on its schedule that the guide explains.
SECTIONS = {
    "not-in-your-plan",
    "no-public-https-address",
    "providers-cannot-reach-the-installation",
    "waiting-for-the-provider",
    "this-calendar-cannot-be-watched",
}


def github_anchor(heading: str) -> str:
    """GitHub's anchor for a heading: lowercase, punctuation dropped, spaces as hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def guide_anchors() -> set[str]:
    return {
        github_anchor(line.lstrip("#"))
        for line in GUIDE.read_text().splitlines()
        if re.match(r"#{2,4} ", line)
    }


def test_every_reason_instant_sync_is_unavailable_has_its_section() -> None:
    assert not SECTIONS - guide_anchors()


def test_the_api_links_only_to_sections_of_the_guide() -> None:
    assert set(AVAILABILITY_ANCHORS.values()) <= SECTIONS


def test_the_rule_page_links_only_to_sections_of_the_guide() -> None:
    source = (REPOSITORY / "web" / "src" / "lib" / "instant-sync.ts").read_text()
    named = set(re.findall(r'^\s+[a-z_]+: "([a-z0-9-]+)",$', source, re.MULTILINE))

    assert named == SECTIONS


def test_the_web_ui_opens_the_guide_where_the_site_renders_it() -> None:
    pages = (REPOSITORY / "site" / "src" / "docs" / "pages.ts").read_text()
    brand = (REPOSITORY / "web" / "src" / "lib" / "brand.ts").read_text()

    assert '{ slug: "instant-sync", source: "docs/instant-sync.md" }' in pages
    assert "`${DOCS_URL}/instant-sync`" in brand
