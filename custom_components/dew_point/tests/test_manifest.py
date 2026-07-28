"""Tests for the Dew Point integration manifest."""

from __future__ import annotations

import json
from pathlib import Path


def test_manifest_routes_dew_point_to_integrations_dashboard() -> None:
    """Dew Point is managed as a calculated service integration."""
    manifest_path = (
        Path(__file__).resolve().parents[3]
        / "custom_components"
        / "dew_point"
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())

    assert manifest["integration_type"] == "service"
