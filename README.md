# Home Assistant — Dew Point

Dew Point is a local, event-driven Home Assistant helper that calculates dew point and related moisture measurements from an air-temperature sensor and a relative-humidity sensor. Add an optional surface-temperature sensor to monitor the margin to condensation and expose a hysteresis-controlled condensation-risk binary sensor.

All calculations run inside Home Assistant. The integration does not contact a cloud service, does not poll, and does not require YAML configuration.

## Highlights

- Immediate recalculation when a source sensor changes
- Dew point, dew point spread, and absolute humidity enabled by default
- Optional vapor-pressure, VPD, and frost-point sensors
- Optional surface-to-dew-point margin and condensation warning
- Celsius, Fahrenheit, and Kelvin temperature sources
- Native Home Assistant units, statistics, entity naming, translations, Repairs, and diagnostics
- Automatic tracking when a source entity is renamed in Home Assistant
- Migration support for existing Dew Point entries and entity-registry settings

## Requirements

- Home Assistant 2026.7 or newer is recommended. This release targets the Home Assistant 2026.7 integration APIs.
- One air-temperature sensor
- One relative-humidity sensor
- Optionally, one surface-temperature sensor

For meaningful results, the air-temperature and humidity sensors should measure the same air mass and should be mounted close enough to respond to similar conditions. Sensor calibration and placement usually have a greater effect on the result than the numerical precision of the calculation.

## Installation

### HACS (recommended)

1. Open **HACS** in Home Assistant.
2. Open the three-dot menu and select **Custom repositories**.
3. Add `https://github.com/Nicxe/home-assistant-dew-point` as an **Integration** repository.
4. Open the new **Dew Point** repository in HACS and select **Download**.
5. Restart Home Assistant when HACS asks you to do so.

Future releases can be installed from the same HACS page. Read the release notes before updating, then restart Home Assistant if HACS requests it.

### Manual installation

1. Download the latest Dew Point release from [GitHub Releases](https://github.com/Nicxe/home-assistant-dew-point/releases).
2. Extract the archive.
3. Copy the extracted `custom_components/dew_point` directory into your Home Assistant configuration directory so the result looks like this:

   ```text
   <config>/custom_components/dew_point/manifest.json
   ```

4. Restart Home Assistant.

Do not copy the repository's outer directory into `custom_components`. Home Assistant must find `manifest.json` directly inside `custom_components/dew_point`.

## Configuration

Use the button below, or go to **Settings > Devices & services > Add integration** and search for **Dew Point**.

<p>
  <a href="https://my.home-assistant.io/redirect/config_flow_start?domain=dew_point" class="my badge" target="_blank">
    <img src="https://my.home-assistant.io/badges/config_flow_start.svg" alt="Add Dew Point to Home Assistant">
  </a>
</p>

The setup form asks for:

| Setting | Required | Default | Description |
| --- | --- | --- | --- |
| Name | Yes | `Dew Point` | A descriptive name for this helper, such as `Bathroom` or `Greenhouse`. |
| Temperature source | Yes | — | The air temperature used by every calculation. |
| Relative humidity source | Yes | — | The relative humidity of the same air mass. |
| Surface temperature source | No | None | Enables the surface margin and condensation-risk entities. Choose a sensor that measures the surface you want to protect. |
| Condensation threshold | Yes | `0.0 °C` | Risk turns on when the surface-to-dew-point margin is at or below this value. Accepted range: -20 to 20 °C. |
| Condensation hysteresis | Yes | `0.5 °C` | Extra margin required before an active risk turns off. Accepted range: 0 to 20 °C. |

The form validates the selected entities and shows a live calculation preview when the Home Assistant frontend supports config-flow previews. An identical temperature, humidity, and surface-source combination cannot be added twice. You can still create multiple helpers for different rooms, sensor pairs, or surfaces.

To change the sources or condensation settings later, open **Settings > Devices & services > Dew Point**, select the integration entry, and choose **Configure**. Saved changes reload the helper automatically.

### Source requirements

| Source | Preferred device class | Required unit | Valid runtime value |
| --- | --- | --- | --- |
| Air temperature | `temperature` | `°C`, `°F`, or `K` | Finite numeric value which converts to -80 through 50 °C |
| Relative humidity | `humidity` | `%` | Finite numeric value from 0 through 100 |
| Surface temperature | `temperature` | `°C`, `°F`, or `K` | Finite numeric value; used only for the surface comparison |

The selectors prioritize sensors with the correct Home Assistant device class. For compatibility with older integrations, a sensor without a device class can still be accepted when its unit clearly identifies it as temperature or relative humidity.

A registered source that is temporarily `unknown` or `unavailable` may still be saved when its registry metadata establishes that it is compatible. Calculations resume automatically when that source reports a valid state.

## Entities

Entity IDs are assigned by Home Assistant and may differ from the examples in this document. Open the helper's entry or the **Entities** page to copy the actual entity IDs. You can safely give the entities more descriptive names and entity IDs in Home Assistant.

| Entity | Unit | Default | Purpose |
| --- | --- | --- | --- |
| Dew point | °C native temperature | Enabled | Temperature at which the current water vapor reaches saturation over liquid water. |
| Dew point spread | °C temperature difference | Enabled | Air temperature minus dew point. A smaller positive value means the air is closer to saturation. |
| Absolute humidity | g/m³ | Enabled | Mass of water vapor per volume of air. Useful when comparing inside and outside air. |
| Vapor pressure | kPa | Disabled | Actual water-vapor partial pressure calculated from temperature and RH. |
| Saturation vapor pressure | kPa | Disabled | Saturation pressure at the measured air temperature. |
| Vapor pressure deficit | kPa | Disabled | Saturation vapor pressure minus actual vapor pressure at the air temperature. |
| Frost point | °C native temperature | Disabled | Temperature at which the vapor pressure reaches saturation over ice, when a root exists in the supported ice range. |
| Surface dew point margin | °C temperature difference | Enabled when a surface source is configured | Surface temperature minus dew point. Positive is above dew point; zero or negative is at or below dew point. |
| Condensation risk | Binary sensor (`problem`) | Enabled when a surface source is configured | Hysteresis-controlled warning based on the surface margin. |

The first three sensors are enabled for every helper. Advanced pressure and frost sensors are created but disabled by default to keep the entity list and Recorder database focused. To enable one, go to **Settings > Devices & services > Entities**, open the disabled entity, and select **Enable**.

The two surface entities are only created when a surface-temperature source is configured. Adding or removing that source through **Configure** reloads the entry and updates its entity set.

### Temperature units and display precision

Temperature inputs are normalized to Celsius for calculation. Temperature and temperature-difference entities publish a stable Celsius native unit, and Home Assistant converts them to the unit selected for your system or entity. Change an entity's displayed unit or precision from its Home Assistant entity settings; these are presentation choices and do not change the underlying calculation.

The integration retains full calculation precision in the native value and supplies a sensible suggested display precision:

- 1 decimal for temperature and temperature-difference sensors
- 2 decimals for absolute humidity
- 3 decimals for pressure and VPD sensors

Avoid comparing a sensor's formatted state as text in automations. Use numeric-state triggers or convert the value with `| float` after first checking that it is numeric.

## How the calculation works

The integration uses the Buck saturation-vapor-pressure equations with the coefficient update described in the Buck Research CR-1A manual. It numerically inverts the same liquid-water equation used to calculate vapor pressure, rather than mixing different forward and inverse approximations. This makes the calculation self-consistent: at 100% water-referenced RH, dew point equals air temperature within numerical tolerance.

For air temperature `T` in °C, the saturation vapor pressure over liquid water is:

```text
eₛ,w(T) = 0.61121 × exp((18.678 - T / 234.5) × (T / (257.14 + T))) kPa
```

The ice relation used for frost point is:

```text
eₛ,i(T) = 0.61115 × exp((23.036 - T / 333.7) × (T / (279.82 + T))) kPa
```

The actual vapor pressure and vapor pressure deficit are:

```text
e = eₛ,w(T) × RH / 100
VPD = eₛ,w(T) - e
```

The liquid-water dew point is found by bounded numerical inversion of `eₛ,w`. Absolute humidity is derived from actual vapor pressure using the ideal-gas relation. Dew point spread and surface margin are then simple temperature differences:

```text
dew point spread = air temperature - dew point
surface margin   = surface temperature - dew point
```

The implementation is based on A. L. Buck, *New Equations for Computing Vapor Pressure and Enhancement Factor*, Journal of Applied Meteorology 20 (1981), with the later coefficient update documented in the [Buck Research CR-1A material](https://yaga.no/wp-content/uploads/2021/11/Dewpoint-Equations.pdf).

### Validity and water/ice semantics

- The liquid-water Buck relation is restricted to -80 through 50 °C in this integration.
- Below 0 °C, the dew-point sensor still represents saturation over supercooled liquid water.
- Frost point is calculated separately by inverting the ice relation from -80 through 0 °C. It is never silently substituted for dew point.
- Relative humidity is assumed to use the liquid-water reference used by normal home humidity sensors.
- The pressure enhancement factor is not applied because the integration has no atmospheric-pressure input.
- At 0% RH, actual vapor pressure and absolute humidity are valid zero values, while no finite dew point, frost point, or dew point spread exists. Those individually undefined entities therefore show `unknown`.
- A frost point can also be `unknown` when the current vapor pressure has no root inside the supported -80 to 0 °C ice range.

These empirical equations provide a consistent engineering estimate, not a substitute for a calibrated condensation or process-safety instrument.

## Condensation-risk logic

When a surface source is configured, the integration calculates:

```text
margin = surface temperature - dew point
```

With the default threshold of `0.0 °C`, risk turns on when the measured surface is at or below the calculated dew point. The default `0.5 °C` hysteresis keeps risk on until the margin reaches at least `0.5 °C`, preventing rapid on/off switching around the threshold.

A positive threshold provides an earlier warning before the surface reaches dew point. For example, a threshold of `1.0 °C` turns risk on when the surface comes within one degree of the dew point. Choose a margin appropriate for your sensor accuracy, placement, material, and use case.

## Availability, recovery, and source renames

The helper reads one shared snapshot and recalculates all derived values whenever any configured source changes. It does not poll on a fixed schedule.

- If the required air-temperature or humidity source is missing, `unknown`, `unavailable`, non-numeric, out of range, or has incompatible metadata, all atmospheric derived entities become `unavailable`.
- If only the optional surface source is unavailable, the normal atmospheric sensors continue working; the surface margin and condensation-risk entities become `unavailable`.
- If the input is valid but a particular result is mathematically undefined, that entity is `unknown` rather than `unavailable`. RH = 0% and a frost point outside the supported ice range are examples.
- Calculations and entity availability recover automatically when valid source data returns.
- When a source entity is renamed through Home Assistant's entity registry, the helper updates its saved source reference and reloads automatically.

Home Assistant receives one log message when a source problem begins and one when the sources recover, rather than repeated messages on every state change.

## Repairs and diagnostics

### Repairs

If a configured source is removed or becomes incompatible, Home Assistant creates a repair issue under **Settings > System > Repairs**. Open the issue to select a compatible replacement source; the helper saves the replacement, clears the issue, and reloads.

Temporary `unknown` or `unavailable` source states do not create persistent repair issues because they normally recover without user action. If an optional surface source is no longer wanted, remove it from the helper's **Configure** form.

### Diagnostics

To download diagnostics, open **Settings > Devices & services > Dew Point**, open the entry menu, and select **Download diagnostics**.

The diagnostics file includes the config-entry schema version, Dew Point settings, source entity IDs, source status, device classes, and units. It deliberately excludes source readings and full state attributes. Common secret fields are redacted. Review any diagnostic file before sharing it, because entity IDs and helper names can still describe your installation.

## State attributes and Recorder compatibility

New dashboards and automations should use the dedicated entities instead of copying changing source measurements from dew-point attributes.

The main dew-point sensor temporarily retains these legacy attributes for compatibility with existing installations:

| Attribute | Status | Replacement or purpose |
| --- | --- | --- |
| `temperature_entity_id` | Retained static reference | Identifies the configured air-temperature source. |
| `humidity_entity_id` | Retained static reference | Identifies the configured humidity source. |
| `temperature` | Deprecated dynamic attribute | Read the temperature source entity directly. |
| `temperature_unit` | Deprecated dynamic attribute | Read the source entity metadata or the diagnostics file. |
| `humidity` | Deprecated dynamic attribute | Read the humidity source entity directly. |
| `decimal_places` | Deprecated presentation attribute | Configure display precision in Home Assistant's entity settings. |
| `output_unit` | Deprecated presentation attribute | Configure the displayed unit in Home Assistant's entity settings. |

The frequently changing legacy attributes are marked as unrecorded, so Recorder does not duplicate their history on every dew-point update. They remain visible in the current state during the compatibility period but should not be used in new automations. They may be removed in a future breaking release after advance notice.

## Automation and dashboard examples

Replace every example entity ID with the IDs from your own installation. The examples below assume that the entities have been renamed descriptively in Home Assistant.

### Send a condensation warning

This example waits for two minutes of continuous risk before notifying a phone:

```yaml
alias: Bathroom - condensation warning
description: Warn when the monitored surface remains at condensation risk
triggers:
  - trigger: state
    entity_id: binary_sensor.bathroom_condensation_risk
    to: "on"
    for: "00:02:00"
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: Condensation risk in the bathroom
      message: >-
        The surface is {{ states('sensor.bathroom_surface_dew_point_margin') }}
        {{ state_attr('sensor.bathroom_surface_dew_point_margin',
                      'unit_of_measurement') }} above the current dew point.
mode: single
```

The binary sensor already applies the configured threshold and hysteresis. Add an automation `for` duration when you also want to ignore brief sensor spikes.

### Identify a useful ventilation opportunity

Absolute humidity lets you compare water content even when indoor and outdoor temperatures differ. This example sends a notification when outdoor air contains at least 0.5 g/m³ less water vapor for ten minutes:

```yaml
alias: Basement - outdoor air is drier
description: Suggest ventilation when outdoor air can remove moisture
triggers:
  - trigger: template
    value_template: >-
      {% set inside = states('sensor.basement_absolute_humidity') %}
      {% set outside = states('sensor.outdoor_absolute_humidity') %}
      {{ is_number(inside) and is_number(outside)
         and (inside | float) > (outside | float) + 0.5 }}
    for: "00:10:00"
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: Good time to ventilate the basement
      message: >-
        Inside: {{ states('sensor.basement_absolute_humidity') }} g/m³;
        outside: {{ states('sensor.outdoor_absolute_humidity') }} g/m³.
mode: single
```

Before controlling a fan or window automatically, also consider outdoor temperature, rain, air quality, security, and heating or cooling demand. The 0.5 g/m³ margin is an example, not a universal threshold.

### Monitor greenhouse VPD

Enable the disabled **Vapor pressure deficit** entity first. This example reports both a high and a low VPD condition:

```yaml
alias: Greenhouse - VPD outside target
description: Notify when air-temperature VPD leaves the example range
triggers:
  - trigger: numeric_state
    entity_id: sensor.greenhouse_vapor_pressure_deficit
    above: 1.2
    id: high
  - trigger: numeric_state
    entity_id: sensor.greenhouse_vapor_pressure_deficit
    below: 0.4
    id: low
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: Greenhouse VPD alert
      message: >-
        VPD is {{ states('sensor.greenhouse_vapor_pressure_deficit') }} kPa
        and is {{ 'above' if trigger.id == 'high' else 'below' }} the example target.
mode: single
```

VPD targets depend on plant, growth stage, lighting, airflow, and measurement method. This integration uses air temperature, not leaf temperature, so choose thresholds from guidance appropriate to your crop and sensors.

### Add a history graph

The History Graph card makes the relationship between temperature, dew point, and spread easy to inspect:

```yaml
type: history-graph
title: Bathroom moisture conditions
hours_to_show: 24
entities:
  - entity: sensor.bathroom_temperature
    name: Air temperature
  - entity: sensor.bathroom_dew_point
    name: Dew point
  - entity: sensor.bathroom_dew_point_spread
    name: Dew point spread
```

For longer comparisons, use Home Assistant's History or Statistics views. The calculated numeric sensors use measurement state classes and stable native units.

## Upgrading from an earlier release

Existing config entries are migrated automatically when the integration loads:

- Legacy settings split between config-entry data and options are moved into one canonical options structure.
- Existing temperature and humidity source selections and helper name are retained.
- The main dew-point entity receives a stable unique ID based on the config entry. The migration updates the entity registry instead of creating a replacement entity, preserving its entity ID, area, enabled state, and other registry customizations.
- A legacy output-unit choice becomes the entity's Home Assistant display-unit override.
- A legacy decimal-place choice becomes the entity's display-precision setting.
- Legacy attributes remain available during the deprecation period described above.

The integration's calculation now publishes Celsius as a stable native unit and lets Home Assistant handle display conversion. Automations should compare numeric values, not unit-specific formatted strings. Back up your Home Assistant configuration before any custom-integration upgrade and review the release notes for announced breaking changes.

Downgrading after the entry schema has been migrated is not supported unless the older release explicitly documents compatibility. A future configuration version is rejected instead of being interpreted as an older schema.

## Troubleshooting

### Dew Point does not appear in Add integration

- Confirm that `<config>/custom_components/dew_point/manifest.json` exists.
- Check that the directory is named exactly `dew_point`.
- Restart Home Assistant after installing or updating the Python files.
- Check **Settings > System > Logs** for a custom-component loading error.

### A sensor does not appear in the source selector

The selector prioritizes the expected device class. Confirm that the source is a `sensor` entity and exposes a temperature device class with `°C`, `°F`, or `K`, or a humidity device class with `%`. Older unit-only sensors can be submitted when their unit is unambiguous, but correcting the source integration's metadata is preferable.

### The form rejects a selected source

Open the source entity in **Developer tools > States** and check its device class, unit, and current state. Temperature must be finite and convertible to Celsius. Humidity must be finite, use `%`, and be between 0 and 100. A different device class such as power, pressure, or battery is not compatible.

### Derived entities are unavailable

Check both required source entities first. An unavailable, unknown, missing, non-numeric, out-of-range, or incompatible required source makes the atmospheric calculations unavailable. Also check **Settings > System > Repairs** for a guided replacement issue. Values outside -80 through 50 °C are outside the calculation range.

If only the surface entities are unavailable, check the optional surface-temperature source; the normal dew-point and humidity-derived sensors should continue to update.

### An entity is unknown but the helper is available

This indicates a valid input snapshot with an undefined individual result. At exactly 0% RH there is no finite dew point, frost point, or spread. Frost point is also unknown when no ice-relation root exists between -80 and 0 °C.

### Vapor pressure, VPD, or frost point is missing

These entities are disabled by default. Find the helper under **Settings > Devices & services > Entities**, include disabled entities in the filter, open the entity, and select **Enable**.

### Condensation risk or surface margin is missing

These entities are only created when a surface-temperature source is configured. Open the Dew Point entry, choose **Configure**, add a compatible surface source, and save. If the entities exist but are unavailable, check the surface source state and unit.

### The displayed unit or decimals are not what I expect

Open the calculated entity's settings and change its displayed unit or precision there. The integration always calculates in Celsius internally and keeps full native precision; it no longer rounds the physical result through integration options.

### A source entity was renamed or removed

A rename made through Home Assistant's entity registry should be followed automatically. A removed source creates a Repair issue. Use that flow to select a replacement, or open **Configure** to change the source manually. References hard-coded in your own dashboards and automations are separate and must still be updated by you.

### Updates appear stale

The integration recalculates on source state-change events and intentionally has no polling interval. Confirm that the source integration is publishing new states. If a device stops updating without marking its entity unavailable, Dew Point cannot independently detect that its last state is stale.

### I need to share troubleshooting data

Download integration diagnostics as described above and inspect the file before attaching it to a GitHub issue. Include the Home Assistant version, Dew Point version, expected behavior, and relevant log messages. Do not publish unrelated logs or secrets.

## Removal

1. Remove or update dashboards, scripts, and automations that depend on the calculated entities.
2. Go to **Settings > Devices & services > Dew Point**.
3. Open the menu for each Dew Point entry and select **Delete**.
4. If installed through HACS, open the Dew Point repository in HACS and select **Remove** after all entries have been deleted. For a manual installation, delete `<config>/custom_components/dew_point`.
5. Restart Home Assistant after removing the custom-component files.

Deleting an integration entry removes its current entities but does not necessarily purge their historical Recorder data immediately. Manage retained history with Home Assistant's Recorder tools if required.

## Known limitations

- Results depend on source-sensor accuracy, calibration, placement, and update timing.
- Temperature and humidity source changes are separate Home Assistant events, so a calculation uses the newest currently available state from each source rather than an atomic hardware sample.
- The integration cannot detect a stale source if that source continues to expose an apparently valid state.
- The liquid-water Buck calculation is intentionally limited to -80 through 50 °C; frost-point inversion is limited to -80 through 0 °C.
- Relative humidity is interpreted as water-referenced RH. There is currently no user setting for an ice-referenced humidity instrument.
- No atmospheric-pressure enhancement factor is applied.
- VPD uses air temperature rather than leaf or canopy temperature.
- Condensation risk is an estimate at the selected sensor location. Thermal bridges, sensor lag, mounting, airflow, material properties, and calibration can cause a real surface to condense earlier or later.
- The helper does not provide a subjective comfort category; comfort thresholds vary by climate, activity, and preference.
- YAML configuration and user-configurable polling intervals are not supported.
- This is a custom integration and is not part of the official Home Assistant distribution.

## Translations

The integration includes English, French, and Swedish user-interface translations. Translation contributions and corrections are welcome in `custom_components/dew_point/translations`.

## Support

Before reporting a problem, review **Troubleshooting**, check Home Assistant Repairs, and download the integration diagnostics. Report reproducible issues in the [GitHub issue tracker](https://github.com/Nicxe/home-assistant-dew-point/issues).

If you find the project useful, you can support its development at [Buy Me a Coffee](https://buymeacoffee.com/niklasv).
