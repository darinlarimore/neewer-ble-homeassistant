# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Home Assistant custom integration for controlling Neewer LED lights via Bluetooth Low Energy (BLE). Uses the [bleak](https://bleak.readthedocs.io/) library for BLE communication.

## Architecture

```
custom_components/neewer_ble/
├── __init__.py      # Integration setup, config entry handling
├── const.py         # Constants, BLE UUIDs, supported model definitions
├── config_flow.py   # Device discovery and configuration UI
├── light.py         # Home Assistant LightEntity implementation
├── neewer_device.py # BLE device communication handler
└── manifest.json    # Integration metadata
```

### Key Components

- **NeewerLightDevice** (`neewer_device.py`): Core BLE communication class. Handles connection management, command building, and protocol differences between standard and "Infinity" protocol devices.

- **NeewerBLELight** (`light.py`): Home Assistant `LightEntity` that wraps `NeewerLightDevice`. Converts between HA's 0-255 brightness and Neewer's 0-100 scale.

### BLE Protocol

Two command prefix variants:
- **Standard**: `[0x78, 0x87, ...]` - older devices
- **Infinity**: `[0x78, 0x8A, ...]` - newer devices (MS150B, GL1, CB series)

Command types defined in `const.py`: CCT (brightness + color temp), HSI (RGB via hue/saturation/intensity), power control.

### Model Detection

Device capabilities (RGB support, color temp range, protocol) are determined by matching the BLE device name against `SUPPORTED_MODELS` in `const.py`. Unknown devices default to bi-color CCT-only mode.

## Development

No build system - this is a Python-based Home Assistant custom component.

### Testing Locally

1. Copy `custom_components/neewer_ble/` to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Check logs at **Settings → System → Logs** filtered by "neewer"

### Adding New Device Support

Add entries to `SUPPORTED_MODELS` dict in `const.py`:
```python
"model_code": {"name": "ModelName", "rgb": bool, "cct_range": (min_k, max_k), "infinity": bool}
```

The `model_code` should match what appears in the device's BLE advertised name.
