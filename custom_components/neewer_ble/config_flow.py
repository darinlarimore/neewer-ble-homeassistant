"""Config flow for Neewer BLE Lights integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, BLE_SCAN_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class NeewerBLEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Neewer BLE Lights."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: dict[str, BLEDevice] = {}
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    @staticmethod
    def _is_neewer_device(name: str) -> bool:
        """Check if a device name indicates a Neewer device."""
        if not name:
            return False
        name_upper = name.upper()
        return "NEEWER" in name_upper or name_upper.startswith("NW-")

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.debug("Bluetooth discovery: %s", discovery_info)
        
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        
        self._discovery_info = discovery_info
        
        # Check if this looks like a Neewer device
        name = discovery_info.name or ""
        if not self._is_neewer_device(name):
            return self.async_abort(reason="not_neewer_device")
        
        self.context["title_placeholders"] = {"name": name}
        
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery of a Neewer device."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name or "Neewer Light",
                data={
                    CONF_ADDRESS: self._discovery_info.address,
                    CONF_NAME: self._discovery_info.name,
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovery_info.name or "Unknown",
                "address": self._discovery_info.address,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input.get(CONF_ADDRESS)

            # Check if user selected manual entry
            if address == "manual":
                return await self.async_step_manual()

            if address in self._discovered_devices:
                device = self._discovered_devices[address]
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=device.name or "Neewer Light",
                    data={
                        CONF_ADDRESS: address,
                        CONF_NAME: device.name,
                    },
                )
            else:
                errors["base"] = "device_not_found"

        # Scan for devices
        await self._async_discover_devices()

        # Build the selection schema - always include manual option
        device_options = {
            address: f"{device.name or 'Unknown'} ({address})"
            for address, device in self._discovered_devices.items()
        }
        # Add manual entry option
        device_options["manual"] = "Enter address manually..."

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(device_options),
                }
            ),
            errors=errors,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual address entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS].upper()
            name = user_input.get(CONF_NAME, "Neewer Light")
            
            # Validate address format (basic check)
            if len(address) != 17 or address.count(":") != 5:
                errors["base"] = "invalid_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_ADDRESS: address,
                        CONF_NAME: name,
                    },
                )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_NAME, default="Neewer Light"): str,
                }
            ),
            errors=errors,
        )

    async def _async_discover_devices(self) -> None:
        """Discover Neewer BLE devices."""
        self._discovered_devices = {}

        # First check already discovered bluetooth devices in HA
        try:
            for discovery_info in async_discovered_service_info(self.hass, connectable=True):
                if self._is_neewer_device(discovery_info.name):
                    self._discovered_devices[discovery_info.address] = discovery_info.device
        except Exception as err:
            _LOGGER.debug("Error checking HA bluetooth discoveries: %s", err)

        # If no devices found via HA, do a direct scan
        if not self._discovered_devices:
            _LOGGER.debug("No devices from HA, performing direct BLE scan...")
            try:
                devices = await BleakScanner.discover(timeout=BLE_SCAN_TIMEOUT)
                for device in devices:
                    if self._is_neewer_device(device.name):
                        self._discovered_devices[device.address] = device
            except Exception as err:
                _LOGGER.error("BLE scan failed: %s", err)

        _LOGGER.debug("Discovered %d Neewer device(s)", len(self._discovered_devices))
