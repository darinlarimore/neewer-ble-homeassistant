"""Light platform for Neewer BLE Lights."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .neewer_device import NeewerLightDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Neewer BLE light from a config entry."""
    device: NeewerLightDevice = hass.data[DOMAIN][entry.entry_id]
    
    async_add_entities([NeewerBLELight(device, entry)])


class NeewerBLELight(LightEntity):
    """Representation of a Neewer BLE Light."""

    _attr_has_entity_name = True
    _attr_name = None  # Use device name

    def __init__(self, device: NeewerLightDevice, entry: ConfigEntry) -> None:
        """Initialize the light."""
        self._device = device
        self._entry = entry
        
        # Entity attributes
        self._attr_unique_id = device.address.replace(":", "_").lower()
        
        # Determine supported color modes
        if device.supports_rgb:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.HS}
            self._attr_color_mode = ColorMode.COLOR_TEMP
        else:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
            self._attr_color_mode = ColorMode.COLOR_TEMP
        
        # Color temperature range
        min_kelvin, max_kelvin = device.color_temp_range
        self._attr_min_color_temp_kelvin = min_kelvin
        self._attr_max_color_temp_kelvin = max_kelvin
        
        # Device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.address)},
            name=entry.data.get(CONF_NAME, device.name),
            manufacturer="Neewer",
            model=device.model_name,
        )

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._device.is_on

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        # Convert 0-100 to 0-255
        return int(self._device.brightness * 2.55)

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        return self._device.color_temp_kelvin

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation color value."""
        if self._device.supports_rgb:
            return (self._device._hue, self._device._saturation)
        return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # We consider it available even if not connected
        # Connection happens on demand
        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        color_temp_kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        hs_color = kwargs.get(ATTR_HS_COLOR)
        
        # Convert HA brightness (0-255) to Neewer (0-100)
        brightness_pct = int(brightness / 2.55) if brightness is not None else None
        
        if hs_color is not None and self._device.supports_rgb:
            # RGB mode
            hue, saturation = hs_color
            await self._device.set_rgb(
                hue=int(hue),
                saturation=int(saturation),
                brightness=brightness_pct,
            )
            self._attr_color_mode = ColorMode.HS
        else:
            # CCT mode
            await self._device.turn_on(
                brightness=brightness_pct,
                color_temp_kelvin=color_temp_kelvin,
            )
            self._attr_color_mode = ColorMode.COLOR_TEMP
        
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self._device.turn_off()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Handle removal from Home Assistant."""
        await self._device.disconnect()
