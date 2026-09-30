import pytest
from cryptography.exceptions import InvalidTag

from calendar_sync.infrastructure.security import CredentialCipher, HistoryCipher, InvalidMasterKey

KEY = CredentialCipher.generate_key()
CONTEXT = "rule-1|personal-account|personal-calendar|event-1"


def test_sealed_values_open_under_the_same_key_and_context() -> None:
    sealed = HistoryCipher(KEY).seal("Dial in: 1234#", CONTEXT)

    assert HistoryCipher(KEY).open(sealed, CONTEXT) == "Dial in: 1234#"
    assert b"1234" not in sealed


def test_values_sealed_for_another_event_do_not_open() -> None:
    sealed = HistoryCipher(KEY).seal("agenda", CONTEXT)

    assert (
        HistoryCipher(KEY).open(sealed, "rule-1|personal-account|personal-calendar|other") is None
    )


def test_values_sealed_under_another_master_key_do_not_open() -> None:
    sealed = HistoryCipher(CredentialCipher.generate_key()).seal("agenda", CONTEXT)

    assert HistoryCipher(KEY).open(sealed, CONTEXT) is None
    assert HistoryCipher(KEY).open(b"", CONTEXT) is None


def test_history_is_sealed_with_a_key_of_its_own() -> None:
    sealed = HistoryCipher(KEY).seal("agenda", CONTEXT)

    with pytest.raises(InvalidTag):
        CredentialCipher(KEY).decrypt(sealed[1:])


def test_an_invalid_master_key_is_rejected() -> None:
    with pytest.raises(InvalidMasterKey):
        HistoryCipher("not-a-key")
