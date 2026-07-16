"""Fixtures for Dew Point tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations) -> None:
    """Enable loading the custom integration in tests."""
