"""The Neewer BLE Lights integration."""

from __future__ import annotations

import logging

from bleak.backends.device import BLEDevice

from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DOMAIN,
    PLATFORMS,
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLOR_TEMP,
    CONF_DEFAULT_BRIGHTNESS,
    CONF_DEFAULT_COLOR_TEMP,
)
from .neewer_device import NeewerLightDevice

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Neewer BLE Lights from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    name: str = entry.data.get("name", "Neewer Light")

    _LOGGER.info("Setting up Neewer BLE device: %s (%s)", name, address)

    # Try to get the BLE device
    ble_device = async_ble_device_from_address(hass, address.upper(), connectable=True)

    if ble_device is None:
        _LOGGER.warning(
            "Device %s not found via HA Bluetooth, creating placeholder with name '%s'",
            address,
            name,
        )
        # Create a minimal BLE device object for connection attempts
        # The actual connection will happen when commands are sent
        ble_device = BLEDevice(
            address=address,
            name=name,
            details={},
            rssi=-100,
        )
    else:
        _LOGGER.info("Found BLE device: %s (%s)", ble_device.name, ble_device.address)

    # Get options with defaults
    default_brightness = entry.options.get(CONF_DEFAULT_BRIGHTNESS, DEFAULT_BRIGHTNESS)
    default_color_temp = entry.options.get(CONF_DEFAULT_COLOR_TEMP, DEFAULT_COLOR_TEMP)

    # Create the device handler
    device = NeewerLightDevice(
        ble_device,
        default_brightness=default_brightness,
        default_color_temp=default_color_temp,
    )
    _LOGGER.info(
        "Created device handler - Model: %s, RGB: %s, Infinity: %s, Default Bri: %d, Default CT: %dK",
        device.model_name,
        device.supports_rgb,
        device.uses_infinity_protocol,
        default_brightness,
        default_color_temp,
    )

    # Store the device
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = device

    # Set up platforms
    _LOGGER.debug("Forwarding setup to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info("Setup complete for %s", name)
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    device: NeewerLightDevice = hass.data[DOMAIN][entry.entry_id]

    default_brightness = entry.options.get(CONF_DEFAULT_BRIGHTNESS, DEFAULT_BRIGHTNESS)
    default_color_temp = entry.options.get(CONF_DEFAULT_COLOR_TEMP, DEFAULT_COLOR_TEMP)

    device.set_defaults(default_brightness, default_color_temp)
    _LOGGER.info(
        "Updated defaults for %s - Brightness: %d, Color Temp: %dK",
        device.name,
        default_brightness,
        default_color_temp,
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Neewer BLE device: %s", entry.data.get(CONF_ADDRESS))
    
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        # Disconnect and clean up
        device: NeewerLightDevice = hass.data[DOMAIN].pop(entry.entry_id)
        await device.disconnect()
    
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", entry.version)
    
    # No migrations needed yet
    return True
