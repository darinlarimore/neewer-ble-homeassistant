"""Neewer BLE device communication handler."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import platform
import subprocess

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import (
    CCT_EFFECTS,
    CMD_GET_CHANNEL_STATUS,
    CMD_GET_POWER_STATUS,
    DEFAULT_DISCONNECT_AFTER,
    EFFECT_GM,
    EFFECT_OFF,
    EFFECT_SPARKS,
    EFFECT_SPEED,
    MAX_CONNECTION_RETRIES,
    NEEWER_NOTIFY_CHARACTERISTIC_UUID,
    NEEWER_WRITE_CHARACTERISTIC_UUID,
    SUPPORTED_MODELS,
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
STD_FX_CMD = 0x8B      # 139 - Scene effect (effect id, then its parameters)

# Infinity protocol command bytes
INF_POWER_CMD = 0x8D   # 141 - Power on/off
INF_CCT_CMD = 0x90     # 144 - CCT mode
INF_HSI_CMD = 0x8F     # 143 - HSI mode (NOT 0x91!)

# Pause between two packets of one command
PACKET_GAP = 0.05

# Give up connecting after this long. A light in range connects in 3-10 s;
# without the limit a command to an unpowered light blocks for more than half a minute.
CONNECT_TIMEOUT = 20.0

# A light is still shown as available for this long after its connection closed:
# it needs a moment before it advertises again.
REACHABLE_GRACE = 90.0


class NeewerLightDevice:
    """Represents a Neewer BLE light device.

    The device keeps the state Home Assistant asked for and sends it to the light.
    The Bluetooth connection stays open for a while after a command, so the next
    one does not have to connect again, and commands for one light never overlap:
    when several arrive while one is being sent, only the latest state goes out.
    """

    def __init__(
        self,
        ble_device: BLEDevice,
        model_info: dict | None = None,
        default_brightness: int = 100,
        default_color_temp: int = 3200,
        disconnect_after: int = DEFAULT_DISCONNECT_AFTER,
    ) -> None:
        """Initialize the Neewer light device."""
        self._ble_device = ble_device
        self._client: BleakClientWithServiceCache | None = None
        self._connect_lock = asyncio.Lock()
        self._command_lock = asyncio.Lock()
        self._disconnect_after = disconnect_after
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._idle_task: asyncio.Task | None = None
        self._listeners: list[Callable[[], None]] = []
        self._generation = 0
        self._last_reached: float | None = None

        # Device info
        self._address = ble_device.address
        self._name = ble_device.name or "Unknown Neewer Light"
        self._model_info = model_info or self._detect_model()

        # Hardware MAC address (needed for Infinity protocol)
        # On macOS, bleak returns UUIDs, not real MAC addresses
        self._hw_mac_address: str | None = None

        # Default values (configurable via options)
        self._default_brightness = default_brightness
        self._default_color_temp = default_color_temp

        # State - initialize to defaults
        self._is_on = False
        self._brightness = default_brightness
        self._kelvin = self._snap_kelvin(default_color_temp)
        self._effect: str | None = None
        self._hs_mode = False
        self._hue = 0
        self._saturation = 100
        # What the light was last told about power (lights with real power commands only)
        self._light_power: bool | None = None

        # For status polling via notifications
        self._notify_data: bytes | None = None
        self._notify_event = asyncio.Event()
        self._last_poll_success = False

    def _detect_model(self) -> dict:
        """Detect the light model from its name.

        Light types per NeewerLite-Python:
          0 = Standard: CCT uses [0x78, 0x87, 0x02, bri, temp] (5 bytes, no GM)
          1 = Infinity: Full infinity protocol with MAC address
          2 = Infinity-hybrid: CCT uses [0x78, 0x87, 0x03, bri, temp, GM] (6 bytes)

        cct_only lights use separate 0x82 (brightness) and 0x83 (temp) commands.
        """
        name = self._name.upper()

        # Remove common prefixes for matching
        name_clean = name.replace("NEEWER-", "").replace("NEEWER", "").replace("-", "").replace(" ", "")

        # Check for the model code or the model name in the device name; the longest match wins.
        # The model name counts too, so a light added by hand as "Neewer CB60B" is recognized
        # while it is switched off and its advertised name is not known.
        best: dict | None = None
        best_length = 0
        for code, info in SUPPORTED_MODELS.items():
            code_clean = code.upper().replace("-", "").replace(" ", "")
            model_clean = info["name"].upper().replace("-", "").replace(" ", "")
            for key in (code_clean, model_clean):
                if key in name_clean and len(key) > best_length:
                    best, best_length = info, len(key)
        if best is None and name_clean:
            # The device name is only a part of a model code
            for code, info in SUPPORTED_MODELS.items():
                if name_clean in code.upper().replace("-", "").replace(" ", ""):
                    best = info
                    break
        if best is not None:
            _LOGGER.debug("Detected model: %s (light_type=%d, cct_only=%s)",
                          best["name"], best.get("light_type", 0), best.get("cct_only", False))
            return best

        # Default to generic standard protocol light
        _LOGGER.debug("Unknown model, using defaults for: %s", self._name)
        return {
            "name": "Unknown",
            "rgb": False,
            "cct_range": (3200, 5600),
            "cct_only": False,
            "light_type": 0,
        }

    # ------------------------------------------------------------------ properties

    @property
    def address(self) -> str:
        """Return the device address."""
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
    def light_type(self) -> int:
        """Return the light type (0=standard, 1=infinity, 2=infinity-hybrid)."""
        return self._model_info.get("light_type", 0)

    @property
    def uses_infinity_protocol(self) -> bool:
        """Return True if device uses full Infinity protocol (type 1)."""
        return self.light_type == 1

    @property
    def is_cct_only(self) -> bool:
        """Return True if device is CCT-only (uses separate brightness/temp commands)."""
        return self._model_info.get("cct_only", False)

    @property
    def uses_real_power(self) -> bool:
        """Return True if "off" is the power command instead of brightness 0."""
        return self._model_info.get("real_power", False)

    @property
    def effect_list(self) -> list[str] | None:
        """Return the built-in effects of this model, or None if it has none."""
        if not self._model_info.get("effects", False):
            return None
        return [EFFECT_OFF, *CCT_EFFECTS]

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
        """Return current brightness (0-100)."""
        return self._brightness

    @property
    def color_temp_kelvin(self) -> int:
        """Return color temperature in Kelvin (the lights take steps of 100 K)."""
        return self._kelvin

    @property
    def effect(self) -> str | None:
        """Return the running effect, or None for steady light."""
        return self._effect

    @property
    def hs_mode(self) -> bool:
        """Return True if an RGB light shows a hue/saturation color."""
        return self._hs_mode

    @property
    def hs_color(self) -> tuple[int, int]:
        """Return hue (0-360) and saturation (0-100)."""
        return (self._hue, self._saturation)

    @property
    def is_connected(self) -> bool:
        """Return True if connected."""
        return self._client is not None and self._client.is_connected

    @property
    def recently_reached(self) -> bool:
        """Return True if the light was connected a moment ago."""
        if self._last_reached is None:
            return False
        return asyncio.get_running_loop().time() - self._last_reached < REACHABLE_GRACE

    # ------------------------------------------------------------------ connection

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        """Use the device object of the newest advertisement for the next connection."""
        self._ble_device = ble_device

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call listener when the connection opens or closes. Returns a function that removes it."""
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 - a listener must not break the connection handling
                _LOGGER.exception("Listener of %s failed", self._name)

    def _mark_reached(self) -> None:
        self._last_reached = asyncio.get_running_loop().time()

    async def _ensure_connected(self) -> None:
        """Connect if there is no open connection. Raises BleakError or TimeoutError."""
        if self.is_connected:
            return
        async with self._connect_lock:
            if self.is_connected:
                return
            _LOGGER.debug("Connecting to %s", self._address)
            async with asyncio.timeout(CONNECT_TIMEOUT):
                self._client = await establish_connection(
                    BleakClientWithServiceCache,
                    self._ble_device,
                    self._name,
                    disconnected_callback=self._handle_disconnect,
                    max_attempts=MAX_CONNECTION_RETRIES,
                    ble_device_callback=lambda: self._ble_device,
                )
            _LOGGER.debug("Connected to %s", self._name)
            self._mark_reached()
        self._notify_listeners()

    async def connect(self) -> bool:
        """Connect to the device. Returns False if it cannot be reached."""
        try:
            await self._ensure_connected()
        except (BleakError, TimeoutError, OSError) as err:
            _LOGGER.error("Failed to connect to %s: %s", self._name, err)
            return False
        return True

    def _handle_disconnect(self, client: BleakClientWithServiceCache) -> None:
        """The connection closed: the light lost power, went out of range, or we closed it."""
        if client is not self._client:
            return
        _LOGGER.debug("Disconnected from %s", self._name)
        self._client = None
        # The light may have lost mains power and be back in standby when it returns:
        # send the power command again on the next "on".
        self._light_power = None
        self._cancel_disconnect_timer()
        self._mark_reached()
        self._notify_listeners()

    def _cancel_disconnect_timer(self) -> None:
        if self._disconnect_timer is not None:
            self._disconnect_timer.cancel()
            self._disconnect_timer = None

    async def _after_command(self) -> None:
        """Keep the connection open for a while, or close it right away when set to 0."""
        self._mark_reached()
        self._cancel_disconnect_timer()
        if self._disconnect_after <= 0:
            await self._close()
            return
        self._disconnect_timer = asyncio.get_running_loop().call_later(
            self._disconnect_after, self._idle_timeout
        )

    def _idle_timeout(self) -> None:
        self._disconnect_timer = None
        self._idle_task = asyncio.get_running_loop().create_task(self._idle_disconnect())

    async def _idle_disconnect(self) -> None:
        async with self._command_lock:
            if self._disconnect_timer is not None:
                return  # a command came in meanwhile and wants the connection kept
            _LOGGER.debug("Closing idle connection to %s", self._name)
            await self._close()

    async def _close(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        self._mark_reached()
        try:
            # Add timeout to prevent hanging on disconnect
            await asyncio.wait_for(client.disconnect(), timeout=5.0)
        except TimeoutError:
            _LOGGER.warning("Timeout disconnecting from %s, forcing cleanup", self._name)
        except (BleakError, OSError) as err:
            _LOGGER.debug("Error disconnecting from %s: %s", self._name, err)
        self._notify_listeners()

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        self._cancel_disconnect_timer()
        await self._close()

    # ------------------------------------------------------------------ packets

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

    def _snap_kelvin(self, kelvin: int) -> int:
        """Bring a Kelvin value into the light's range, in the steps of 100 K the lights take."""
        min_k, max_k = self.color_temp_range
        return int(round(max(min_k, min(max_k, kelvin)) / 100)) * 100

    def _temp_byte(self) -> int:
        """Return the color temperature as the lights take it: Kelvin / 100."""
        return self._kelvin // 100

    def _build_cct_command(self, brightness: int, temp_byte: int) -> list[int]:
        """Build a CCT (brightness + color temperature) command.

        From NeewerLite-Python, based on light_type:
        - Type 0 (standard): [0x78, 0x87, 0x02, brightness, temp] + checksum (5 bytes, no GM)
        - Type 1 (infinity): [0x78, 0x90, 0x0B, MAC(6), 0x87, brightness, temp, GM, 0x04] + checksum
        - Type 2 (infinity-hybrid): [0x78, 0x87, 0x03, brightness, temp, GM] + checksum (6 bytes)

        Args:
            brightness: 0-100
            temp_byte: color temperature in Kelvin / 100
        """
        gm_value = 50  # Neutral green-magenta tint

        if self.light_type == 1:
            # Infinity (type 1): [0x78, 0x90, 0x0B, MAC(6), 0x87, brightness, temp, GM, 0x04] + checksum
            cmd = [0x78, INF_CCT_CMD, 0x0B]
            cmd.extend(self._get_mac_bytes())
            cmd.extend([STD_CCT_CMD, brightness, temp_byte, gm_value, 0x04])
        elif self.light_type == 2:
            # Infinity-hybrid (type 2): [0x78, 0x87, 0x03, brightness, temp, GM] + checksum
            cmd = [0x78, STD_CCT_CMD, 0x03, brightness, temp_byte, gm_value]
        else:
            # Standard (type 0): [0x78, 0x87, 0x02, brightness, temp] + checksum (no GM!)
            cmd = [0x78, STD_CCT_CMD, 0x02, brightness, temp_byte]

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
        - Infinity: [120, 141, 8, MAC(6), 129, 1/2] + checksum (1=on, 2=off; 0 is ignored,
          checked on an RGB1 in #11)
        """
        if self.uses_infinity_protocol:
            # Infinity: [0x78, 0x8D, 0x08, MAC(6), 0x81, on/off] + checksum
            cmd = [0x78, INF_POWER_CMD, 0x08]
            cmd.extend(self._get_mac_bytes())
            cmd.extend([STD_POWER_CMD, 1 if on else 2])
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

    def _build_temp_only_command(self, temp_byte: int) -> list[int]:
        """Build a color temperature-only command for old CCT lights.

        From NeewerLite-Python:
        - [120, 131, 1, temp] + checksum, temp in Kelvin / 100
        """
        cmd = [0x78, STD_TEMP_CMD, 0x01, temp_byte]
        return self._add_checksum(cmd)

    def _build_effect_command(self, effect: str) -> list[int]:
        """Build a scene effect command: [0x78, 0x8B, length, effect id, parameters...] + checksum.

        The effect takes the current brightness and color temperature.
        """
        effect_id, layout = CCT_EFFECTS[effect]
        min_k, max_k = self.color_temp_range
        values = {
            "bri": self._brightness,
            "dim": max(1, round(self._brightness / 5)),
            "cct": self._temp_byte(),
            "cct_min": min_k // 100,
            "cct_max": max_k // 100,
            "gm": EFFECT_GM,
            "speed": EFFECT_SPEED,
            "sparks": EFFECT_SPARKS,
        }
        params = [effect_id] + [values[item] if isinstance(item, str) else item for item in layout]
        return self._add_checksum([0x78, STD_FX_CMD, len(params), *params])

    def _state_packets(self) -> list[list[int]]:
        """Build the packets that bring the light to the wanted state."""
        if not self._is_on:
            if self.uses_real_power:
                return [self._build_power_command(False)]
            # Brightness 0 instead of the power command, which puts some lights
            # into deep sleep with Bluetooth disabled.
            if self.is_cct_only:
                return [self._build_brightness_only_command(0)]
            return [self._build_cct_command(0, self._temp_byte())]

        packets: list[list[int]] = []
        if self.uses_real_power and self._light_power is not True:
            packets.append(self._build_power_command(True))

        if self._effect is not None:
            packets.append(self._build_effect_command(self._effect))
        elif self._hs_mode and self.supports_rgb:
            packets.append(self._build_hsi_command(self._hue, self._saturation, self._brightness))
        elif self.is_cct_only:
            # Old CCT-only lights need separate brightness and temp commands
            packets.append(self._build_brightness_only_command(self._brightness))
            packets.append(self._build_temp_only_command(self._temp_byte()))
        else:
            packets.append(self._build_cct_command(self._brightness, self._temp_byte()))
        return packets

    # ------------------------------------------------------------------ sending

    async def _write(self, packets: list[list[int]]) -> bool:
        """Send packets over the open connection, connecting first if needed.

        A connection that turns out to be dead is dropped and opened again once.
        Call with the command lock held.
        """
        for attempt in (1, 2):
            had_connection = self.is_connected
            try:
                await self._ensure_connected()
                client = self._client
                if client is None:
                    raise BleakError("connection closed")
                for index, packet in enumerate(packets):
                    if index:
                        await asyncio.sleep(PACKET_GAP)
                    _LOGGER.debug("Sending to %s: %s", self._name, bytes(packet).hex(" "))
                    await client.write_gatt_char(
                        NEEWER_WRITE_CHARACTERISTIC_UUID,
                        bytes(packet),
                        response=False,
                    )
            except (BleakError, TimeoutError, OSError) as err:
                self._cancel_disconnect_timer()
                await self._close()
                if had_connection and attempt == 1:
                    # The open connection was dead (the light lost power meanwhile): connect anew
                    _LOGGER.debug("Connection to %s was stale (%s), reconnecting", self._name, err)
                    continue
                _LOGGER.error("Failed to send to %s: %s", self._name, err or type(err).__name__)
                return False
            await self._after_command()
            return True
        return False

    def _snapshot(self) -> tuple:
        return (self._is_on, self._brightness, self._kelvin, self._effect,
                self._hs_mode, self._hue, self._saturation)

    def _restore(self, snapshot: tuple) -> None:
        (self._is_on, self._brightness, self._kelvin, self._effect,
         self._hs_mode, self._hue, self._saturation) = snapshot

    async def _commit(self, previous: tuple) -> bool:
        """Send the wanted state to the light.

        Returns False and puts the previous state back if the light cannot be reached.
        """
        self._generation += 1
        generation = self._generation
        async with self._command_lock:
            if generation != self._generation:
                # A newer change is waiting behind this one and sends the final state
                return True
            if await self._write(self._state_packets()):
                if self.uses_real_power:
                    self._light_power = self._is_on
                return True
            if generation == self._generation:
                self._restore(previous)
            self._light_power = None
            return False

    async def turn_on(
        self,
        brightness: int | None = None,
        color_temp_kelvin: int | None = None,
        hue: int | None = None,
        saturation: int | None = None,
        effect: str | None = None,
    ) -> bool:
        """Turn on the light with optional parameters.

        Args:
            brightness: 0-100
            color_temp_kelvin: color temperature, steady white (or the white an effect uses)
            hue, saturation: color of an RGB light (0-360, 0-100)
            effect: name of a built-in effect, or "off" for steady light
        """
        previous = self._snapshot()
        self._is_on = True

        if brightness is not None:
            self._brightness = max(0, min(100, brightness))

        if color_temp_kelvin is not None:
            self._kelvin = self._snap_kelvin(color_temp_kelvin)
            self._hs_mode = False

        # For RGB lights with hue/saturation
        if self.supports_rgb and hue is not None:
            self._hue = max(0, min(360, hue))
            if saturation is not None:
                self._saturation = max(0, min(100, saturation))
            self._hs_mode = True
            self._effect = None

        if effect is not None:
            if effect == EFFECT_OFF:
                self._effect = None
            elif self.effect_list and effect in CCT_EFFECTS:
                self._effect = effect
                self._hs_mode = False
            else:
                _LOGGER.warning("%s has no effect %r", self._name, effect)

        return await self._commit(previous)

    async def turn_off(self) -> bool:
        """Turn off the light.

        Lights with "real_power" get the power command. The others get brightness 0,
        because the power command puts some lights into deep sleep with Bluetooth disabled.
        """
        previous = self._snapshot()
        self._is_on = False
        self._effect = None
        return await self._commit(previous)

    async def set_brightness(self, brightness: int) -> bool:
        """Set brightness (0-100)."""
        if brightness <= 0:
            return await self.turn_off()
        return await self.turn_on(brightness=brightness)

    async def set_color_temp(self, kelvin: int) -> bool:
        """Set color temperature in Kelvin."""
        if not self._is_on:
            self._kelvin = self._snap_kelvin(kelvin)
            return True
        return await self.turn_on(color_temp_kelvin=kelvin)

    async def set_rgb(self, hue: int, saturation: int, brightness: int | None = None) -> bool:
        """Set RGB color using HSI values."""
        if not self.supports_rgb:
            _LOGGER.warning("Device %s does not support RGB", self._name)
            return False
        return await self.turn_on(brightness=brightness, hue=hue, saturation=saturation)

    # ------------------------------------------------------------------ status queries

    def _notify_callback(self, sender: int, data: bytearray) -> None:
        """Handle notification data from the device.

        Per NeewerLite-Python, response format:
        - First byte (data[0]) is the response type
        - Type 1 (0x01): Channel/mode status - data[3] contains current channel
        - Type 2 (0x02): Power status - data[3]=1 ON, data[3]=2 STANDBY
        """
        _LOGGER.debug("Notification from %s: %s", self._name, [hex(b) for b in data])
        self._notify_data = bytes(data)
        self._notify_event.set()

    async def _send_command_with_response(
        self, command: list[int], timeout: float = 2.0
    ) -> bytes | None:
        """Send a command and wait for notification response.

        Args:
            command: The command bytes to send
            timeout: How long to wait for response

        Returns:
            The notification response data, or None if failed/timeout
        """
        async with self._command_lock:
            try:
                await self._ensure_connected()
                client = self._client
                if client is None:
                    return None

                # Clear any previous notification data
                self._notify_data = None
                self._notify_event.clear()

                await client.start_notify(
                    NEEWER_NOTIFY_CHARACTERISTIC_UUID, self._notify_callback
                )
                try:
                    _LOGGER.debug(
                        "Sending query to %s: %s", self._name, [hex(b) for b in command]
                    )
                    await client.write_gatt_char(
                        NEEWER_WRITE_CHARACTERISTIC_UUID,
                        bytes(command),
                        response=False,
                    )
                    try:
                        await asyncio.wait_for(self._notify_event.wait(), timeout=timeout)
                    except TimeoutError:
                        _LOGGER.debug("Timeout waiting for response from %s", self._name)
                        return None
                    return self._notify_data
                finally:
                    try:
                        await client.stop_notify(NEEWER_NOTIFY_CHARACTERISTIC_UUID)
                    except (BleakError, OSError):
                        pass
                    await self._after_command()

            except (BleakError, TimeoutError, OSError) as err:
                _LOGGER.debug("Error querying %s: %s", self._name, err)
                self._cancel_disconnect_timer()
                await self._close()
                return None

    async def async_get_power_status(self) -> bool | None:
        """Query the device power status.

        Response format: [0x78, type, len, data..., checksum]
        - Type 0x02 = power status
        - Data byte: 1=ON, 2=STANDBY

        Returns:
            True if ON, False if STANDBY/OFF, None if query failed
        """
        response = await self._send_command_with_response(CMD_GET_POWER_STATUS)
        if response is None or len(response) < 4:
            _LOGGER.debug("Failed to get power status from %s", self._name)
            return None

        # Response: [0x78, type, len, data, checksum]
        # response[1] is the type, response[3] is the power state
        if response[0] == 0x78 and response[1] == 0x02:  # Power status response
            power_state = response[3]
            is_on = power_state == 1
            _LOGGER.debug(
                "Power status for %s: %s (raw: %d)", self._name,
                "ON" if is_on else "STANDBY", power_state
            )
            return is_on

        _LOGGER.debug(
            "Unexpected response type from %s: %s", self._name, [hex(b) for b in response]
        )
        return None

    async def async_get_channel_status(self) -> dict | None:
        """Query the device channel/mode status.

        Response format: [0x78, type, len, data..., checksum]
        - Type 0x01 = channel/mode status

        Returns:
            Dict with channel info, or None if query failed
        """
        response = await self._send_command_with_response(CMD_GET_CHANNEL_STATUS)
        if response is None or len(response) < 4:
            _LOGGER.debug("Failed to get channel status from %s", self._name)
            return None

        # Response: [0x78, type, len, data..., checksum]
        if response[0] == 0x78 and response[1] == 0x01:
            channel = response[3] if len(response) > 3 else 0
            _LOGGER.debug("Channel status for %s: channel=%d", self._name, channel)
            return {"channel": channel, "raw": list(response)}

        _LOGGER.debug(
            "Unexpected response type from %s: %s", self._name, [hex(b) for b in response]
        )
        return None

    async def async_update(self) -> bool:
        """Poll the device for current state.

        Returns:
            True if update was successful, False otherwise
        """
        try:
            power_status = await self.async_get_power_status()
            if power_status is not None:
                self._is_on = power_status
                self._last_poll_success = True
                _LOGGER.debug(
                    "Updated state for %s: is_on=%s", self._name, self._is_on
                )
                return True
            self._last_poll_success = False
            return False
        except Exception as err:
            _LOGGER.debug("Error polling %s: %s", self._name, err)
            self._last_poll_success = False
            return False

    @property
    def last_poll_success(self) -> bool:
        """Return True if the last poll was successful."""
        return self._last_poll_success

    def set_defaults(
        self,
        brightness: int,
        color_temp_kelvin: int,
        disconnect_after: int | None = None,
    ) -> None:
        """Update default values (called when options change)."""
        self._default_brightness = brightness
        self._default_color_temp = color_temp_kelvin
        if disconnect_after is not None:
            self._disconnect_after = disconnect_after
        _LOGGER.debug(
            "Updated defaults for %s: brightness=%d, color_temp=%dK, disconnect_after=%ss",
            self._name,
            brightness,
            color_temp_kelvin,
            self._disconnect_after,
        )


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
