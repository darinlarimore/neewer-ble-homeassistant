# Neewer BLE Lights for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration for controlling Neewer LED lights via Bluetooth Low Energy (BLE).

## Supported Devices

This integration supports Neewer lights that use Bluetooth for control, including:

### Tested
- **MS150B** - 130W Bi-Color COB Light

### Should Work (Untested)
- MS60C - 65W RGB COB Light
- RGB660 / RGB660 PRO - Panel Lights
- RGB480 / RGB530 - Panel Lights
- SL-80 - Bi-Color Panel
- SNL-660 - Bi-Color Panel
- GL1 - Key Light
- CB100C / CB300B - COB Lights
- RGB1 - Light Wand
- TL60 RGB - Tube Light

## Features

- **Brightness control** (0-100%)
- **Color temperature control** (varies by model, typically 2700K-6500K)
- **RGB color control** (for supported models)
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

Some Neewer lights use different BLE protocols. If your light isn't responding:
1. Open an issue with your light model
2. Include the Bluetooth device name (visible in the Neewer app or via a BLE scanner)

## Contributing

Contributions are welcome! If you have a Neewer light that isn't working:

1. Fork this repository
2. Add your light's model info to `const.py`
3. Test the integration
4. Submit a pull request

## Protocol Information

This integration is based on the reverse-engineered Neewer BLE protocol from:
- [NeewerLite](https://github.com/keefo/NeewerLite) (macOS)
- [NeewerLite-Python](https://github.com/taburineagle/NeewerLite-Python) (Cross-platform)

## License

MIT License - see [LICENSE](LICENSE) for details.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by Neewer.
