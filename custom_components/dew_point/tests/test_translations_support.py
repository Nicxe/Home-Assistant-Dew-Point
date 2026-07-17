"""Tests for Dew Point translations."""

from __future__ import annotations

from homeassistant.helpers.translation import async_get_translations

from custom_components.dew_point.const import DOMAIN


async def test_english_swedish_and_french_translations_load(hass) -> None:
    """All supported languages expose config, entity, and issue text."""
    expected = {
        "en": {
            "config": "Create a Dew Point helper",
            "weather": "Weather entity",
            "entity": "{name} condensation risk",
            "issue": "Replace the surface temperature source",
            "weather_issue": "Replace the weather source",
        },
        "sv": {
            "config": "Skapa en daggpunktshjälpare",
            "weather": "Väderentitet",
            "entity": "{name} kondensrisk",
            "issue": "Ersätt yttemperaturkällan",
            "weather_issue": "Ersätt väderkällan",
        },
        "fr": {
            "config": "Créer un assistant Point de rosée",
            "weather": "Entité météo",
            "entity": "{name} risque de condensation",
            "issue": "Remplacer la source de température de surface",
            "weather_issue": "Remplacer la source météo",
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
            config["component.dew_point.config.step.weather.data.weather_entity"]
            == text["weather"]
        )
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
        assert (
            issues[
                "component.dew_point.issues.weather_source_missing.fix_flow.step.replace_source.title"
            ]
            == text["weather_issue"]
        )
