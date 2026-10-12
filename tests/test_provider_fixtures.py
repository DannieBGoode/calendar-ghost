"""Recorded provider answers stay synthetic. `scripts/provider_fixtures.py` replaces what names a
person, an account, or a provider's item, and no committed fixture carries one (AGENTS.md)."""

import re
from pathlib import Path
from typing import Any

from scripts.provider_fixtures import EMAIL, Sanitizer

FIXTURES = Path(__file__).parent / "fixtures" / "providers"
# A provider's opaque identifier or token: long, with both digits and capitals.
OPAQUE = re.compile(r"(?=[A-Za-z0-9+/=_-]*\d)(?=[A-Za-z0-9+/=_-]*[A-Z])[A-Za-z0-9+/=_-]{32,}")
MASTER = "AAMkAGI2TG93AAAAAA1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def test_the_sanitizer_keeps_the_shape_and_links_and_replaces_identity() -> None:
    first = {
        "dateTime": "2027-01-04T08:00:00.0000000",
        "timeZone": "UTC",
    }
    recorded: dict[str, Any] = {
        "value": [
            {
                "id": MASTER,
                "type": "seriesMaster",
                "subject": "CG weekly",
                "start": first,
                "organizer": {
                    "emailAddress": {"name": "Ada Lovelace", "address": "ada@contoso.com"}
                },
                "webLink": f"https://outlook.live.com/owa/?itemid={MASTER}&exvsurl=1",
                "cancelledOccurrences": [f"OID.{MASTER}.2027-01-11"],
            },
            {"id": "AAMkOccurrence0000000000000000000000001", "seriesMasterId": MASTER},
        ]
    }

    master, occurrence = Sanitizer().sanitize(recorded)["value"]

    assert occurrence["seriesMasterId"] == master["id"] == "item-1"
    assert master["cancelledOccurrences"] == ["OID.item-1.2027-01-11"]
    assert master["organizer"]["emailAddress"] == {
        "name": "Person 1",
        "address": "address-1@example.test",
    }
    assert master["webLink"] == "https://outlook.live.com/owa/?itemid=redacted&exvsurl=redacted"
    assert (master["subject"], master["start"]) == ("CG weekly", first)


def test_committed_fixtures_name_no_real_person_account_or_item() -> None:
    for path in FIXTURES.glob("*.json"):
        text = path.read_text()
        addresses = EMAIL.findall(text)
        assert all(address.endswith("example.test") for address in addresses), path.name
        assert not OPAQUE.findall(text), path.name
