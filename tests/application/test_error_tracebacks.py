"""Errors survive every way Python raises them, including through a context manager (#103)."""

import importlib
import inspect
import pkgutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import fields, is_dataclass

import pytest

import calendar_sync
from calendar_sync.application.sync.errors import (
    ProviderFailure,
    RemovalInterrupted,
    ReplacementInterrupted,
)
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.domain.providers import ProviderFailureKind

FAILURE = ProviderFailure(ProviderFailureKind.TEMPORARY, "synthetic outage")
REMOVAL = RemovalInterrupted(1, 2, FAILURE)


@contextmanager
def passthrough() -> Iterator[None]:
    yield


@pytest.mark.parametrize(
    "make",
    [
        lambda: ProviderFailure(ProviderFailureKind.TEMPORARY, "synthetic outage"),
        lambda: RemovalInterrupted(1, 2, FAILURE),
        lambda: ReplacementInterrupted(SyncRuleId("rule-2"), REMOVAL),
    ],
    ids=["provider failure", "removal interrupted", "replacement interrupted"],
)
def test_an_error_raised_through_a_context_manager_arrives_unchanged(
    make: Callable[[], Exception],
) -> None:
    raised = make()

    with pytest.raises(type(raised)) as caught, passthrough():
        raise raised

    assert caught.value is raised


def _exception_classes() -> Iterator[type[BaseException]]:
    for module in pkgutil.walk_packages(calendar_sync.__path__, "calendar_sync."):
        if ".interfaces.api.static" in module.name:
            continue
        for _, member in inspect.getmembers(importlib.import_module(module.name), inspect.isclass):
            if issubclass(member, BaseException) and member.__module__ == module.name:
                yield member


def test_no_error_is_a_frozen_dataclass() -> None:
    # Raising sets __traceback__ on the error, which a frozen dataclass refuses.
    frozen = [
        cls.__qualname__
        for cls in _exception_classes()
        if is_dataclass(cls) and fields(cls) and cls.__dataclass_params__.frozen
    ]

    assert frozen == []
