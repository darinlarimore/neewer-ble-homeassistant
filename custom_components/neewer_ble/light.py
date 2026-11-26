"""Light platform for Neewer BLE Lights."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EFFECT_OFF
from .neewer_device import NeewerLightDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Neewer BLE light from a config entry."""
    _LOGGER.debug("Setting up light entity for entry: %s", entry.entry_id)

    device: NeewerLightDevice = hass.data[DOMAIN][entry.entry_id]

    _LOGGER.debug(
        "Creating light entity - Name: %s, Model: %s, RGB: %s, Infinity: %s",
        device.name,
        device.model_name,
        device.supports_rgb,
        device.uses_infinity_protocol,
    )

    async_add_entities([NeewerBLELight(device, entry)])


def brightness_to_percent(brightness: int) -> int:
    """Convert Home Assistant brightness (1-255) to the light's 1-100."""
    return max(1, min(100, round(brightness * 100 / 255)))


def percent_to_brightness(percent: int) -> int:
    """Convert the light's 0-100 to Home Assistant brightness (0-255)."""
    return round(percent * 255 / 100)


class NeewerBLELight(LightEntity):
    """Representation of a Neewer BLE Light."""

    _attr_has_entity_name = True
    _attr_name = None  # Use device name
    _attr_should_poll = False  # The lights do not report their state

    def __init__(self, device: NeewerLightDevice, entry: ConfigEntry) -> None:
        """Initialize the light."""
        self._device = device
        self._entry = entry
        self._address: str = entry.data.get(CONF_ADDRESS, device.address).upper()
        self._heard = False  # heard on Bluetooth lately; set when the entity is added

        # Entity attributes
        self._attr_unique_id = device.address.replace(":", "_").lower()

        # Determine supported color modes
        if device.supports_rgb:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.HS}
        else:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}

        # Color temperature range
        min_kelvin, max_kelvin = device.color_temp_range
        self._attr_min_color_temp_kelvin = min_kelvin
        self._attr_max_color_temp_kelvin = max_kelvin

        # Built-in effects
        if device.effect_list:
            self._attr_supported_features = LightEntityFeature.EFFECT
            self._attr_effect_list = device.effect_list

        # Device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.address)},
            name=entry.data.get(CONF_NAME, device.name),
            manufacturer="Neewer",
            model=device.model_name,
        )

    async def async_added_to_hass(self) -> None:
        """Follow the light on Bluetooth: its advertisements and its connection."""
        await super().async_added_to_hass()
        self._heard = bluetooth.async_address_present(
            self.hass, self._address, connectable=True
        )
        self.async_on_remove(self._device.add_listener(self._handle_connection_change))
        self.async_on_remove(
            bluetooth.async_register_callback(
                self.hass,
                self._handle_advertisement,
                {"address": self._address, "connectable": True},
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )
        self.async_on_remove(
            bluetooth.async_track_unavailable(
                self.hass, self._handle_unavailable, self._address, connectable=True
            )
        )

    @callback
    def _handle_connection_change(self) -> None:
        """The connection to the light opened or closed."""
        self.async_write_ha_state()

    @callback
    def _handle_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """The light was heard: connect through this device object next time."""
        self._device.set_ble_device(service_info.device)
        if not self._heard:
            self._heard = True
            self.async_write_ha_state()

    @callback
    def _handle_unavailable(self, service_info: bluetooth.BluetoothServiceInfoBleak) -> None:
        """The light was not heard for a while (a connected light does not advertise)."""
        self._heard = False
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if the light is connected or was heard on Bluetooth lately."""
        return self._heard or self._device.is_connected or self._device.recently_reached

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._device.is_on

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        return percent_to_brightness(self._device.brightness)

    @property
    def color_mode(self) -> ColorMode:
        """Return the color mode of the light."""
        if self._device.supports_rgb and self._device.hs_mode:
            return ColorMode.HS
        return ColorMode.COLOR_TEMP

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        return self._device.color_temp_kelvin

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation color value."""
        if self._device.supports_rgb:
            hue, saturation = self._device.hs_color
            return (float(hue), float(saturation))
        return None

    @property
    def effect(self) -> str | None:
        """Return the running effect ("off" for steady light)."""
        if not self._device.effect_list:
            return None
        return self._device.effect or EFFECT_OFF

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        hs_color = kwargs.get(ATTR_HS_COLOR)
        hue = saturation = None
        if hs_color is not None and self._device.supports_rgb:
            hue, saturation = int(hs_color[0]), int(hs_color[1])

        reached = await self._device.turn_on(
            brightness=brightness_to_percent(brightness) if brightness is not None else None,
            color_temp_kelvin=kwargs.get(ATTR_COLOR_TEMP_KELVIN),
            hue=hue,
            saturation=saturation,
            effect=kwargs.get(ATTR_EFFECT),
        )
        self.async_write_ha_state()
        if not reached:
            raise HomeAssistantError(
                f"{self._device.model_name} light {self._address} did not answer: "
                "is it powered and in Bluetooth range?"
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        reached = await self._device.turn_off()
        self.async_write_ha_state()
        if not reached:
            raise HomeAssistantError(
                f"{self._device.model_name} light {self._address} did not answer: "
                "is it powered and in Bluetooth range?"
            )

    async def async_will_remove_from_hass(self) -> None:
        """Handle removal from Home Assistant."""
        await self._device.disconnect()
