# Home Assistant - Dew Point

<a href="https://buymeacoffee.com/niklasv" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: auto !important;width: auto !important;" ></a>

<img alt="Maintenance" src="https://img.shields.io/maintenance/yes/2025"> <img alt="GitHub last commit" src="https://img.shields.io/github/last-commit/Nicxe/home-assistant-dew-point"><br><br>


## Overview

This integration calculates the **dew point temperature** based on data from a temperature sensor and a humidity sensor. The dew point is a key measure of thermal comfort and indicates the temperature at which air becomes saturated with moisture.


If you're interested in related integrations, check out my [Feels Like (Apparent Temperature)](https://github.com/Nicxe/felt_temperature) integration.

<details>
<summary>Uses the Arden Buck equation for accurate dew point estimation</summary>

### How Arden Buck's Equation Works
The integration uses **[Arden Buck's equation](https://yaga.no/wp-content/uploads/2021/11/Dewpoint-Equations.pdf)** to calculate the dew point. Here's a simplified explanation of how the calculation works:

1. **Saturation Vapor Pressure** (`e_s`):  
   First, the saturation vapor pressure is calculated in kilopascals (kPa) using an exponential function based on the current temperature (°C).  

2. **Actual Vapor Pressure** (`e`):  
   The actual vapor pressure is determined by multiplying the saturation vapor pressure by the relative humidity (0–1).  

3. **Dew Point Temperature** (`T_dew`):  
   Using the actual vapor pressure, the dew point is solved by taking the natural logarithm of \( \frac{e}{0.61121} \) and applying a formula to isolate \( T_\text{dew} \).  

The result is the temperature (in °C) at which water vapor condenses, providing an accurate measure of moisture in the air.

</details>




## Installation

You can install this integration as a custom repository by following one of these guides:

### With HACS (Recommended)

To install the custom component using HACS:

1. Click on the three dots in the top right corner of the HACS overview menu.
2. Select **Custom repositories**.
3. Add the repository URL: `https://github.com/Nicxe/home-assistant-dew-point`.
4. Select type: **Integration**.
5. Click the **ADD** button.

<details>
<summary>Without HACS</summary>

1. Download the latest release of the SMHI Alert integration from **[GitHub Releases](https://github.com/Nicxe/home-assistant-dew-point/releases)**.
2. Extract the downloaded files and place the `dew_point` folder in your Home Assistant `custom_components` directory (usually located in the `config/custom_components` directory).
3. Restart your Home Assistant instance to load the new integration.

</details>

## Configuration

To add the integration to your Home Assistant instance, use the button below:


<p>
    <a href="https://my.home-assistant.io/redirect/config_flow_start?domain=dew_point" class="my badge" target="_blank">
        <img src="https://my.home-assistant.io/badges/config_flow_start.svg">
    </a>
</p>

> [!TIP]
> You can easily set up multiple dew point sensors for different locations by clicking Add Entry on the Dew Point integration page in Home Assistant. No YAML configuration is required, and each sensor can have its own unique setup.



### Manual Configuration

If the button above does not work, you can also perform the following steps manually:

1. Browse to your Home Assistant instance.
2. Go to **Settings > Devices & Services**.
3. In the bottom right corner, select the **Add Integration** button.
4. From the list, select **Dew Point**.
5. Follow the on-screen instructions to complete the setup.


## Translations

This integration includes built-in English texts and can be translated into other languages.
Contributions are welcome in the files under `custom_components/dew_point/translations/`.
