"""Every troubleshooting link the service hands out reaches a section of the guide."""

import re
from pathlib import Path

from calendar_sync.application.installation_hints import (
    CAUSE_ANCHORS,
    TESTING_MODE_ANCHOR,
    UNRECOGNIZED_ANCHOR,
)

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "troubleshooting.md"


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


def test_every_hint_links_to_a_section_of_the_guide() -> None:
    anchors = guide_anchors()
    linked = {*CAUSE_ANCHORS.values(), TESTING_MODE_ANCHOR, UNRECOGNIZED_ANCHOR}

    assert linked <= anchors, linked - anchors
