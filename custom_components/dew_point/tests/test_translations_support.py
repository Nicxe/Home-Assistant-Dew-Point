"""Tests for Dew Point translations."""

from __future__ import annotations

from homeassistant.helpers.translation import async_get_translations

from custom_components.dew_point.const import DOMAIN


async def test_english_swedish_and_french_translations_load(hass) -> None:
    """All supported languages expose config, entity, and issue text."""
    expected = {
        "en": {
            "config": "Create a Dew Point helper",
            "entity": "{name} condensation risk",
            "issue": "Replace the surface temperature source",
        },
        "sv": {
            "config": "Skapa en daggpunktshjälpare",
            "entity": "{name} kondensrisk",
            "issue": "Ersätt yttemperaturkällan",
        },
        "fr": {
            "config": "Créer un assistant Point de rosée",
            "entity": "{name} risque de condensation",
            "issue": "Remplacer la source de température de surface",
        },
    }

    for language, text in expected.items():
        config = await async_get_translations(
            hass, language, "config", integrations={DOMAIN}, config_flow=True
        )
        entities = await async_get_translations(
            hass, language, "entity", integrations={DOMAIN}
        )
        issues = await async_get_translations(
            hass, language, "issues", integrations={DOMAIN}
        )
        assert config["component.dew_point.config.step.user.title"] == text["config"]
        assert (
            entities["component.dew_point.entity.binary_sensor.condensation_risk.name"]
            == text["entity"]
        )
        assert (
            issues[
                "component.dew_point.issues.surface_temperature_source_missing.fix_flow.step.replace_source.title"
            ]
            == text["issue"]
        )
