from calendar_sync.application.sync.errors import ProviderFailureKind


def test_every_provider_failure_names_its_incidents_category() -> None:
    # A new failure kind fails here until the domain's categories, and so its next steps, know it.
    for kind in ProviderFailureKind:
        assert kind.incident_category.value == kind.value
