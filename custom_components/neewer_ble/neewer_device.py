"""Neewer BLE device communication handler."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .const import (
    NEEWER_SERVICE_UUID,
    NEEWER_WRITE_CHARACTERISTIC_UUID,
    CMD_PREFIX_STANDARD,
    CMD_PREFIX_INFINITY,
    CMD_SET_CCT,
    CMD_SET_HSI,
    CMD_POWER_ON,
    CMD_POWER_OFF,
    SUPPORTED_MODELS,
    MAX_CONNECTION_RETRIES,
    CONNECTION_RETRY_DELAY,
)

_LOGGER = logging.getLogger(__name__)


class NeewerLightDevice:
    """Represents a Neewer BLE light device."""

    def __init__(self, ble_device: BLEDevice, model_info: dict | None = None) -> None:
        """Initialize the Neewer light device."""
        self._ble_device = ble_device
        self._client: BleakClient | None = None
        self._lock = asyncio.Lock()
        
        # Device info
        self._address = ble_device.address
        self._name = ble_device.name or "Unknown Neewer Light"
        self._model_info = model_info or self._detect_model()
        
        # State
        self._is_on = False
        self._brightness = 100
        self._color_temp = 56  # Internal 0-100 scale (maps to Kelvin)
        self._hue = 0
        self._saturation = 100
        self._connected = False

    def _detect_model(self) -> dict:
        """Detect model info from device name."""
        name = self._name.upper()
        
        # Check for model code in name (newer Infinity protocol devices)
        for code, info in SUPPORTED_MODELS.items():
            if code in name or info["name"].upper() in name:
                _LOGGER.debug("Detected model: %s", info["name"])
                return info
        
        # Default to generic bi-color light
        _LOGGER.debug("Unknown model, using defaults for: %s", self._name)
        return {
            "name": "Unknown",
            "rgb": False,
            "cct_range": (3200, 5600),
            "infinity": False,
        }

    @property
    def address(self) -> str:
        """Return the BLE address."""
        return self._address

    @property
    def name(self) -> str:
        """Return the device name."""
        return self._name

    @property
    def model_name(self) -> str:
        """Return the model name."""
        return self._model_info.get("name", "Unknown")

    @property
    def supports_rgb(self) -> bool:
        """Return True if device supports RGB."""
        return self._model_info.get("rgb", False)

    @property
    def uses_infinity_protocol(self) -> bool:
        """Return True if device uses the newer Infinity protocol."""
        return self._model_info.get("infinity", False)

    @property
    def color_temp_range(self) -> tuple[int, int]:
        """Return the color temperature range in Kelvin."""
        return self._model_info.get("cct_range", (3200, 5600))

    @property
    def is_on(self) -> bool:
        """Return True if light is on."""
        return self._is_on

    @property
    def brightness(self) -> int:
        """Return brightness (0-100)."""
        return self._brightness

    @property
    def color_temp_kelvin(self) -> int:
        """Return color temperature in Kelvin."""
        min_k, max_k = self.color_temp_range
        # Convert internal 0-100 scale to Kelvin
        return int(min_k + (self._color_temp / 100) * (max_k - min_k))

    @property
    def is_connected(self) -> bool:
        """Return True if connected."""
        return self._connected and self._client is not None and self._client.is_connected

    async def connect(self) -> bool:
        """Connect to the device."""
        if self.is_connected:
            return True

        async with self._lock:
            for attempt in range(MAX_CONNECTION_RETRIES):
                try:
                    _LOGGER.debug(
                        "Connecting to %s (attempt %d/%d)",
                        self._address,
                        attempt + 1,
                        MAX_CONNECTION_RETRIES,
                    )
                    
                    self._client = BleakClient(self._ble_device)
                    await self._client.connect()
                    self._connected = True
                    _LOGGER.info("Connected to %s", self._name)
                    return True
                    
                except BleakError as err:
                    _LOGGER.warning(
                        "Connection attempt %d failed: %s",
                        attempt + 1,
                        err,
                    )
                    if self._client:
                        try:
                            await self._client.disconnect()
                        except Exception:
                            pass
                    self._client = None
                    
                    if attempt < MAX_CONNECTION_RETRIES - 1:
                        await asyncio.sleep(CONNECTION_RETRY_DELAY)

            _LOGGER.error("Failed to connect to %s after %d attempts", self._name, MAX_CONNECTION_RETRIES)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        async with self._lock:
            if self._client:
                try:
                    await self._client.disconnect()
                except Exception as err:
                    _LOGGER.debug("Error disconnecting: %s", err)
                finally:
                    self._client = None
                    self._connected = False

    async def _send_command(self, command: list[int]) -> bool:
        """Send a command to the device."""
        if not await self.connect():
            return False

        try:
            _LOGGER.debug("Sending command: %s", [hex(b) for b in command])
            await self._client.write_gatt_char(
                NEEWER_WRITE_CHARACTERISTIC_UUID,
                bytes(command),
                response=False,
            )
            return True
        except BleakError as err:
            _LOGGER.error("Failed to send command: %s", err)
            self._connected = False
            return False

    def _build_cct_command(self, brightness: int, color_temp: int) -> list[int]:
        """Build a CCT (brightness + color temperature) command.
        
        Args:
            brightness: 0-100
            color_temp: 0-100 (internal scale, 0=warm, 100=cool)
        """
        if self.uses_infinity_protocol:
            # Infinity protocol format
            # [0x78, 0x8A, 0x02, brightness, color_temp, 0x02, checksum]
            cmd = CMD_PREFIX_INFINITY + [CMD_SET_CCT, brightness, color_temp, 0x02]
        else:
            # Standard protocol format
            # [0x78, 0x87, 0x02, brightness, color_temp]
            cmd = CMD_PREFIX_STANDARD + [CMD_SET_CCT, brightness, color_temp]
        
        return cmd

    def _build_hsi_command(self, hue: int, saturation: int, intensity: int) -> list[int]:
        """Build an HSI (hue, saturation, intensity) command for RGB lights.
        
        Args:
            hue: 0-360
            saturation: 0-100
            intensity: 0-100 (brightness)
        """
        # Hue is sent as two bytes (little endian)
        hue_low = hue & 0xFF
        hue_high = (hue >> 8) & 0xFF
        
        if self.uses_infinity_protocol:
            cmd = CMD_PREFIX_INFINITY + [CMD_SET_HSI, intensity, hue_low, hue_high, saturation]
        else:
            cmd = CMD_PREFIX_STANDARD + [CMD_SET_HSI, intensity, hue_low, hue_high, saturation]
        
        return cmd

    def _build_power_command(self, on: bool) -> list[int]:
        """Build a power on/off command."""
        cmd_type = CMD_POWER_ON if on else CMD_POWER_OFF
        
        if self.uses_infinity_protocol:
            return CMD_PREFIX_INFINITY + [cmd_type]
        else:
            return CMD_PREFIX_STANDARD + [cmd_type]

    def _kelvin_to_internal(self, kelvin: int) -> int:
        """Convert Kelvin to internal 0-100 scale."""
        min_k, max_k = self.color_temp_range
        kelvin = max(min_k, min(max_k, kelvin))
        return int(((kelvin - min_k) / (max_k - min_k)) * 100)

    def _internal_to_kelvin(self, internal: int) -> int:
        """Convert internal 0-100 scale to Kelvin."""
        min_k, max_k = self.color_temp_range
        return int(min_k + (internal / 100) * (max_k - min_k))

    async def turn_on(
        self,
        brightness: int | None = None,
        color_temp_kelvin: int | None = None,
        hue: int | None = None,
        saturation: int | None = None,
    ) -> bool:
        """Turn on the light with optional parameters."""
        self._is_on = True
        
        if brightness is not None:
            self._brightness = max(0, min(100, brightness))
        
        if color_temp_kelvin is not None:
            self._color_temp = self._kelvin_to_internal(color_temp_kelvin)
        
        # For RGB lights with hue/saturation
        if self.supports_rgb and hue is not None:
            self._hue = max(0, min(360, hue))
            if saturation is not None:
                self._saturation = max(0, min(100, saturation))
            
            cmd = self._build_hsi_command(self._hue, self._saturation, self._brightness)
        else:
            # CCT mode
            cmd = self._build_cct_command(self._brightness, self._color_temp)
        
        return await self._send_command(cmd)

    async def turn_off(self) -> bool:
        """Turn off the light."""
        self._is_on = False
        # Send brightness 0 command (most Neewer lights don't have explicit off)
        cmd = self._build_cct_command(0, self._color_temp)
        return await self._send_command(cmd)

    async def set_brightness(self, brightness: int) -> bool:
        """Set brightness (0-100)."""
        self._brightness = max(0, min(100, brightness))
        self._is_on = brightness > 0
        
        cmd = self._build_cct_command(self._brightness, self._color_temp)
        return await self._send_command(cmd)

    async def set_color_temp(self, kelvin: int) -> bool:
        """Set color temperature in Kelvin."""
        self._color_temp = self._kelvin_to_internal(kelvin)
        
        if self._is_on:
            cmd = self._build_cct_command(self._brightness, self._color_temp)
            return await self._send_command(cmd)
        return True

    async def set_rgb(self, hue: int, saturation: int, brightness: int | None = None) -> bool:
        """Set RGB color using HSI values."""
        if not self.supports_rgb:
            _LOGGER.warning("Device %s does not support RGB", self._name)
            return False
        
        self._hue = max(0, min(360, hue))
        self._saturation = max(0, min(100, saturation))
        if brightness is not None:
            self._brightness = max(0, min(100, brightness))
        
        self._is_on = True
        cmd = self._build_hsi_command(self._hue, self._saturation, self._brightness)
        return await self._send_command(cmd)


async def discover_neewer_lights(timeout: float = 10.0) -> list[BLEDevice]:
    """Discover Neewer BLE lights."""
    _LOGGER.debug("Scanning for Neewer lights...")
    
    devices = []
    
    def detection_callback(device: BLEDevice, advertisement_data):
        if device.name and "NEEWER" in device.name.upper():
            _LOGGER.debug("Found Neewer device: %s (%s)", device.name, device.address)
            devices.append(device)
    
    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    
    _LOGGER.info("Found %d Neewer device(s)", len(devices))
    return devices
