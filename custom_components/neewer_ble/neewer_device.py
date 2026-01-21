"""Neewer BLE device communication handler."""

from __future__ import annotations

import asyncio
import logging
import platform
import subprocess
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

from .const import (
    NEEWER_SERVICE_UUID,
    NEEWER_WRITE_CHARACTERISTIC_UUID,
    SUPPORTED_MODELS,
    MAX_CONNECTION_RETRIES,
    CONNECTION_RETRY_DELAY,
)

_LOGGER = logging.getLogger(__name__)

# Protocol constants (from NeewerLite-Python)
# Standard protocol: [0x78, CMD, LEN, ...params, checksum]
# Infinity protocol: [0x78, CMD, LEN, MAC(6), ...params, checksum]

# Standard protocol command bytes
STD_POWER_CMD = 0x81   # 129 - Power on/off
STD_BRI_CMD = 0x82     # 130 - Brightness only (for old CCT lights)
STD_TEMP_CMD = 0x83    # 131 - Color temperature only (for old CCT lights)
STD_HSI_CMD = 0x86     # 134 - HSI mode (hue, sat, brightness)
STD_CCT_CMD = 0x87     # 135 - CCT mode (brightness, temp, GM)

# Infinity protocol command bytes
INF_POWER_CMD = 0x8D   # 141 - Power on/off
INF_CCT_CMD = 0x90     # 144 - CCT mode
INF_HSI_CMD = 0x8F     # 143 - HSI mode (NOT 0x91!)


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

        # Hardware MAC address (needed for Infinity protocol)
        # On macOS, bleak returns UUIDs, not real MAC addresses
        self._hw_mac_address: str | None = None

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

    def _get_hardware_mac_macos(self) -> str | None:
        """Get hardware MAC address on macOS using system_profiler.

        On macOS, bleak returns UUIDs instead of real MAC addresses.
        We need the real MAC for Infinity protocol commands.
        """
        try:
            result = subprocess.run(
                ["system_profiler", "SPBluetoothDataType"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = result.stdout

            # Find the device by name
            name_offset = output.find(self._name)
            if name_offset == -1:
                _LOGGER.debug("Device %s not found in system_profiler output", self._name)
                return None

            # Find "Address:" after the device name
            address_offset = output.find("Address:", name_offset)
            if address_offset == -1:
                _LOGGER.debug("Address not found for %s", self._name)
                return None

            # Extract the MAC address (format: XX-XX-XX-XX-XX-XX or XX:XX:XX:XX:XX:XX)
            # Address is 17 chars after "Address: "
            mac_start = address_offset + 9
            mac_str = output[mac_start:mac_start + 17].strip()

            # Validate it looks like a MAC address
            mac_clean = mac_str.replace("-", ":").upper()
            parts = mac_clean.split(":")
            if len(parts) == 6 and all(len(p) == 2 for p in parts):
                _LOGGER.debug("Found hardware MAC for %s: %s", self._name, mac_clean)
                return mac_clean

            _LOGGER.debug("Invalid MAC format found: %s", mac_str)
            return None

        except subprocess.TimeoutExpired:
            _LOGGER.warning("system_profiler timed out")
            return None
        except Exception as err:
            _LOGGER.debug("Error getting hardware MAC: %s", err)
            return None

    def _get_mac_bytes(self) -> list[int]:
        """Convert MAC address string to list of integer bytes."""
        # For Infinity protocol on macOS, we need the real hardware MAC
        if self.uses_infinity_protocol and platform.system() == "Darwin":
            if self._hw_mac_address is None:
                self._hw_mac_address = self._get_hardware_mac_macos()

            if self._hw_mac_address:
                mac = self._hw_mac_address.replace("-", ":")
                parts = mac.split(":")
                if len(parts) == 6:
                    return [int(p, 16) for p in parts]

            _LOGGER.warning(
                "Could not get hardware MAC for %s on macOS, Infinity commands may fail",
                self._name
            )

        # For non-macOS or non-Infinity, use the BLE address directly
        mac = self._address.replace("-", ":")
        parts = mac.split(":")
        if len(parts) == 6:
            return [int(p, 16) for p in parts]

        # Fallback - return zeros if MAC format is unexpected
        _LOGGER.warning("Unexpected MAC format: %s", self._address)
        return [0, 0, 0, 0, 0, 0]

    def _calculate_checksum(self, data: list[int]) -> int:
        """Calculate checksum for command (sum of all bytes & 0xFF)."""
        checksum = 0
        for byte in data:
            if byte < 0:
                checksum += byte + 256
            else:
                checksum += byte
        return checksum & 0xFF

    def _add_checksum(self, cmd: list[int]) -> list[int]:
        """Add checksum byte to command."""
        return cmd + [self._calculate_checksum(cmd)]

    async def connect(self) -> bool:
        """Connect to the device using bleak-retry-connector for reliability."""
        if self.is_connected:
            return True

        async with self._lock:
            try:
                _LOGGER.debug("Connecting to %s", self._address)

                # Use bleak-retry-connector for reliable connection
                self._client = await establish_connection(
                    BleakClientWithServiceCache,
                    self._ble_device,
                    self._name,
                    max_attempts=MAX_CONNECTION_RETRIES,
                )
                self._connected = True
                _LOGGER.info("Connected to %s", self._name)
                return True

            except BleakError as err:
                _LOGGER.error("Failed to connect to %s: %s", self._name, err)
                self._client = None
                self._connected = False
                return False
            except Exception as err:
                _LOGGER.error("Unexpected error connecting to %s: %s", self._name, err)
                self._client = None
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
            _LOGGER.info(
                "Sending to %s: %s (decimal: %s)",
                self._name,
                [hex(b) for b in command],
                command,
            )
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
        finally:
            # Always disconnect after sending to free up BLE connection slots
            await self.disconnect()

    def _build_cct_command(self, brightness: int, color_temp: int) -> list[int]:
        """Build a CCT (brightness + color temperature) command.

        From NeewerLite-Python:
        - Standard: [120, 135, 2, brightness, temp] + checksum
          where temp is 32-56 (for 3200K-5600K)
        - Infinity: [120, 144, 11, MAC(6), 135, brightness, temp, GM, 4] + checksum

        Args:
            brightness: 0-100
            color_temp: 0-100 (internal scale, maps to kelvin range)
        """
        # Convert 0-100 internal scale to 32-56 protocol temp value
        temp_protocol = int(32 + (color_temp / 100) * 24)
        gm_value = 50  # Neutral green-magenta tint

        if self.uses_infinity_protocol:
            # Infinity: [0x78, 0x90, 0x0B, MAC(6), 0x87, brightness, temp, GM, 0x04] + checksum
            cmd = [0x78, INF_CCT_CMD, 0x0B]
            cmd.extend(self._get_mac_bytes())
            cmd.extend([STD_CCT_CMD, brightness, temp_protocol, gm_value, 0x04])
        else:
            # Standard: [0x78, 0x87, 0x02, brightness, temp] + checksum
            # Note: length byte 0x02 = 2 data bytes (no GM for standard protocol)
            cmd = [0x78, STD_CCT_CMD, 0x02, brightness, temp_protocol]

        return self._add_checksum(cmd)

    def _build_hsi_command(self, hue: int, saturation: int, intensity: int) -> list[int]:
        """Build an HSI (hue, saturation, intensity) command for RGB lights.

        From NeewerLite-Python:
        - Standard: [120, 134, 4, hue_low, hue_high, saturation, brightness] + checksum
        - Infinity: [120, 143, 11, MAC(6), 134, hue_low, hue_high, saturation, brightness] + checksum

        Args:
            hue: 0-360
            saturation: 0-100
            intensity: 0-100 (brightness)
        """
        # Hue is sent as two bytes (little endian)
        hue_low = hue & 0xFF
        hue_high = (hue >> 8) & 0xFF

        if self.uses_infinity_protocol:
            # Infinity: [0x78, 0x8F, 0x0B, MAC(6), 0x86, hue_low, hue_high, sat, brightness] + checksum
            cmd = [0x78, INF_HSI_CMD, 0x0B]
            cmd.extend(self._get_mac_bytes())
            cmd.extend([STD_HSI_CMD, hue_low, hue_high, saturation, intensity])
        else:
            # Standard: [0x78, 0x86, 0x04, hue_low, hue_high, saturation, brightness] + checksum
            cmd = [0x78, STD_HSI_CMD, 0x04, hue_low, hue_high, saturation, intensity]

        return self._add_checksum(cmd)

    def _build_power_command(self, on: bool) -> list[int]:
        """Build a power on/off command.

        From NeewerLite-Python:
        - Standard: [120, 129, 1, 1/2] + checksum (1=on, 2=off)
        - Infinity: [120, 141, 8, MAC(6), 129, 1/0] + checksum (1=on, 0=off)
        """
        if self.uses_infinity_protocol:
            # Infinity: [0x78, 0x8D, 0x08, MAC(6), 0x81, on/off] + checksum
            cmd = [0x78, INF_POWER_CMD, 0x08]
            cmd.extend(self._get_mac_bytes())
            cmd.extend([STD_POWER_CMD, 1 if on else 0])
        else:
            # Standard: [0x78, 0x81, 0x01, on/off] + checksum (1=on, 2=off)
            cmd = [0x78, STD_POWER_CMD, 0x01, 1 if on else 2]

        return self._add_checksum(cmd)

    def _build_brightness_only_command(self, brightness: int) -> list[int]:
        """Build a brightness-only command for old CCT lights.

        From NeewerLite-Python:
        - [120, 130, 1, brightness] + checksum

        Args:
            brightness: 0-100
        """
        cmd = [0x78, STD_BRI_CMD, 0x01, brightness]
        return self._add_checksum(cmd)

    def _build_temp_only_command(self, color_temp: int) -> list[int]:
        """Build a color temperature-only command for old CCT lights.

        From NeewerLite-Python:
        - [120, 131, 1, temp] + checksum
          where temp is 32-56 (for 3200K-5600K)

        Args:
            color_temp: 0-100 (internal scale, maps to kelvin range)
        """
        # Convert 0-100 internal scale to 32-56 protocol temp value
        temp_protocol = int(32 + (color_temp / 100) * 24)
        cmd = [0x78, STD_TEMP_CMD, 0x01, temp_protocol]
        return self._add_checksum(cmd)

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
            return await self._send_command(cmd)

        # CCT mode
        if self.uses_infinity_protocol:
            # Infinity lights use combined CCT command
            cmd = self._build_cct_command(self._brightness, self._color_temp)
            return await self._send_command(cmd)
        else:
            # Standard protocol lights need separate brightness and temp commands
            # First send power on, then brightness, then temp (per NeewerLite-Python)
            power_cmd = self._build_power_command(on=True)
            await self._send_command(power_cmd)

            bri_cmd = self._build_brightness_only_command(self._brightness)
            await self._send_command(bri_cmd)

            temp_cmd = self._build_temp_only_command(self._color_temp)
            return await self._send_command(temp_cmd)

    async def turn_off(self) -> bool:
        """Turn off the light."""
        self._is_on = False
        # Use power off command
        cmd = self._build_power_command(on=False)
        return await self._send_command(cmd)

    async def set_brightness(self, brightness: int) -> bool:
        """Set brightness (0-100)."""
        self._brightness = max(0, min(100, brightness))
        self._is_on = brightness > 0

        if self.uses_infinity_protocol:
            cmd = self._build_cct_command(self._brightness, self._color_temp)
            return await self._send_command(cmd)
        else:
            # Standard protocol uses separate brightness command
            cmd = self._build_brightness_only_command(self._brightness)
            return await self._send_command(cmd)

    async def set_color_temp(self, kelvin: int) -> bool:
        """Set color temperature in Kelvin."""
        self._color_temp = self._kelvin_to_internal(kelvin)

        if self._is_on:
            if self.uses_infinity_protocol:
                cmd = self._build_cct_command(self._brightness, self._color_temp)
                return await self._send_command(cmd)
            else:
                # Standard protocol uses separate temp command
                cmd = self._build_temp_only_command(self._color_temp)
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


def _is_neewer_device(name: str) -> bool:
    """Check if a device name indicates a Neewer device."""
    if not name:
        return False
    name_upper = name.upper()
    return "NEEWER" in name_upper or name_upper.startswith("NW-")


async def discover_neewer_lights(timeout: float = 10.0) -> list[BLEDevice]:
    """Discover Neewer BLE lights."""
    _LOGGER.debug("Scanning for Neewer lights...")

    devices = []

    def detection_callback(device: BLEDevice, advertisement_data):
        if _is_neewer_device(device.name):
            _LOGGER.debug("Found Neewer device: %s (%s)", device.name, device.address)
            devices.append(device)
    
    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    
    _LOGGER.info("Found %d Neewer device(s)", len(devices))
    return devices
