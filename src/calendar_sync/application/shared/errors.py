"""Errors every context may raise."""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for use-case failures."""


class InfrastructureFailure(ApplicationError):
    """A local adapter failed to fulfill its contract."""
