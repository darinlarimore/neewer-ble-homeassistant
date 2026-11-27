# Neewer BLE Lights for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

[![Validate](https://github.com/darinlarimore/neewer-ble-homeassistant/actions/workflows/validate.yml/badge.svg)](https://github.com/darinlarimore/neewer-ble-homeassistant/actions/workflows/validate.yml)

A Home Assistant custom integration for controlling Neewer LED lights via Bluetooth Low Energy (BLE).

## Status: a work in progress, built by the people who own the lights

Neewer does not publish its Bluetooth protocol. Every model here is set up from the
reverse-engineering work in NeewerLite and NeewerLite-Python, and **only two have been tried on
real hardware**. The rest are best guesses that need someone who owns the light.

**If you have a Neewer light, please tell us how it behaves**, working or not:
[send a light test report](https://github.com/darinlarimore/neewer-ble-homeassistant/issues/new?template=light_report.yml).
It takes a few minutes and is the most useful contribution there is. To add a model or fix
something yourself, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Supported Devices

| Light | Type | Status |
|---|---|---|
| **CB60B** | 70W bi-color COB | Tested on 0.3.0 (two units), including effects |
| **MS150B** | 130W bi-color COB | Tested up to 0.2.1; not yet re-tested on 0.3.0 |
| CB100C | RGB COB | Reported: color resets when brightness changes ([#4](https://github.com/darinlarimore/neewer-ble-homeassistant/issues/4)); 0.3.0 should fix it, unconfirmed |
| RGB168 | RGB panel | Reported: inconsistent response ([#8](https://github.com/darinlarimore/neewer-ble-homeassistant/issues/8)) |
| PL60C, AP150C | | Reported: discovered but no control ([#9](https://github.com/darinlarimore/neewer-ble-homeassistant/issues/9)) |
| SNL1320 | Bi-color panel | Reported: discovered but no control ([#10](https://github.com/darinlarimore/neewer-ble-homeassistant/issues/10)) |
| MS60C, CB300B, GL1 | COB and key lights | Untested |
| RGB660, RGB660 PRO, RGB480, RGB530, RGB530 PRO, RGB176, RGB960 | RGB panels | Untested |
| RGB512, RGB800 | RGB panels | Untested |
| SL-80, SNL-660, SNL-530, SNL-480 | Bi-color panels | Untested |
| RGB1, TL60 RGB | Wand and tube | Untested |

A light that is not in the table is set up as a generic bi-color light (3200 K to 5600 K). It may
work, partly work or not respond: [ask for it to be added](https://github.com/darinlarimore/neewer-ble-homeassistant/issues/new?template=new_model.yml).

## Features

- **Brightness control** (0-100%)
- **Color temperature control** (varies by model, typically 2700K-6500K)
- **RGB color control** (for supported models)
- **Built-in effects** (CB60B: lightning, paparazzi, candlelight, TV screen and eight more)
- **Auto-discovery** via Home Assistant's Bluetooth integration
- **Manual device entry** for devices not auto-discovered

## Requirements

- Home Assistant 2024.1.0 or newer
- Bluetooth adapter on your Home Assistant host
- OR an ESPHome Bluetooth Proxy

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right corner
3. Select "Custom repositories"
4. Add this repository URL: `https://github.com/darinlarimore/neewer-ble-homeassistant`
5. Select "Integration" as the category
6. Click "Add"
7. Search for "Neewer BLE" and install it
8. Restart Home Assistant

### Manual Installation

1. Download the `custom_components/neewer_ble` folder from this repository
2. Copy it to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

### Automatic Discovery

If your Neewer light is powered on and in range, Home Assistant should automatically discover it. You'll see a notification to configure the new device.

### Manual Setup

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "Neewer BLE"
4. Select your light from the discovered devices, or enter the Bluetooth address manually

### Options

Each light has options under **Configure** on its page:

- **Default brightness** and **default color temperature**: what the light starts at.
- **Keep the Bluetooth connection open**: how many seconds the connection stays open after a
  command (10 minutes by default). While it is open, the next command arrives at once instead of
  after a reconnect of about 3 seconds, **but the Neewer phone app cannot connect to the light**.
  Set it to 0 to close the connection after every command.

## Usage

Once configured, your Neewer light will appear as a light entity in Home Assistant. You can:

- Turn it on/off
- Adjust brightness
- Change color temperature (in Kelvin)
- Set RGB colors (if supported by your model)

### Example Automations

```yaml
# Turn on light when camera is active
automation:
  - alias: "Studio Light On When Recording"
    trigger:
      - platform: state
        entity_id: binary_sensor.camera_active
        to: "on"
    action:
      - service: light.turn_on
        target:
          entity_id: light.neewer_ms150b
        data:
          brightness_pct: 80
          color_temp_kelvin: 5600
```

```yaml
# Dim lights for video call
script:
  video_call_lighting:
    sequence:
      - service: light.turn_on
        target:
          entity_id: light.neewer_ms150b
        data:
          brightness_pct: 60
          color_temp_kelvin: 4500
```

## Troubleshooting

### Light Not Discovered

1. Make sure the light is powered on
2. Ensure Bluetooth is enabled on your Home Assistant host
3. Try moving the light closer to your Bluetooth adapter
4. Check that no other device (like the Neewer app) is connected to the light

### Connection Issues

Bluetooth connections can be finicky. Try:
- Restarting the light
- Restarting Home Assistant
- Using an ESPHome Bluetooth Proxy for better range/reliability

### Light Not Responding

Some Neewer lights use different BLE protocols. If your light isn't responding,
[send a light test report](https://github.com/darinlarimore/neewer-ble-homeassistant/issues/new?template=light_report.yml)
with its model and Bluetooth name. [CONTRIBUTING.md](CONTRIBUTING.md) shows where to find the name
and how to turn on debug logging.

### The Neewer App Cannot Connect

Home Assistant keeps its connection to the light open for a while after a command, and a light
accepts one connection at a time. Set **Keep the Bluetooth connection open** to 0 in the light's
options, or wait for it to close.

## Contributing

This is a community effort: the integration only gets better on a model when someone who owns it
reports back. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to test your light, add a model, or
send a fix. Thanks to everyone who has sent reports and pull requests.

## Protocol Information

This integration is based on the reverse-engineered Neewer BLE protocol from:
- [NeewerLite](https://github.com/keefo/NeewerLite) (macOS)
- [NeewerLite-Python](https://github.com/taburineagle/NeewerLite-Python) (Cross-platform)

## License

MIT License - see [LICENSE](LICENSE) for details.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by Neewer.
