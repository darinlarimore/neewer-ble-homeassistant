"""Protocol tests: the bytes a command sends and how the connection is used.

They load the device module on its own, so they need neither Home Assistant nor a light.
The RGB1 cases come from the hardware checks in pull request #11.
"""

import asyncio
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from bleak.backends.device import BLEDevice

# Load the protocol module without running the Home Assistant integration setup.
package = ModuleType("neewer_protocol_tests")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components" / "neewer_ble")]
sys.modules[package.__name__] = package
protocol = importlib.import_module(f"{package.__name__}.neewer_device")
NeewerLightDevice = protocol.NeewerLightDevice

ADDRESS = "12:34:56:78:9A:BC"
RGB1 = "NW-20200015&FFFFFFFF"
POWER_ON = bytes.fromhex("78 8d 08 12 34 56 78 9a bc 81 01 f9")
POWER_OFF = bytes.fromhex("78 8d 08 12 34 56 78 9a bc 81 02 fa")


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # On macOS the Infinity commands look the light's MAC up with system_profiler;
        # everywhere else, and here, the Bluetooth address is the MAC.
        system = patch.object(protocol.platform, "system", return_value="Linux")
        system.start()
        self.addCleanup(system.stop)

    def make_device(self, name=RGB1, connected=True):
        device = NeewerLightDevice(BLEDevice(ADDRESS, name, {}))
        client = SimpleNamespace(
            is_connected=True,
            disconnect=AsyncMock(),
            write_gatt_char=AsyncMock(),
        )
        if connected:
            device._client = client
        # Closes the connection and stops the idle timer a command leaves behind.
        self.addAsyncCleanup(device.disconnect)
        return device, client

    @staticmethod
    def written(client):
        return [call.args[1] for call in client.write_gatt_char.call_args_list]

    def test_rgb1_is_recognised_by_its_code_as_an_infinity_rgb_light(self):
        device, _ = self.make_device()
        self.assertEqual(device.model_name, "RGB1")
        self.assertTrue(device.supports_rgb)
        self.assertTrue(device.uses_infinity_protocol)
        self.assertTrue(device.uses_real_power)

    async def test_rgb1_off_is_the_power_command_and_keeps_the_brightness(self):
        device, client = self.make_device()
        self.assertTrue(await device.turn_off())
        self.assertEqual(self.written(client), [POWER_OFF])
        self.assertEqual(device.brightness, 100)
        self.assertFalse(device.is_on)
        client.disconnect.assert_not_awaited()

    async def test_rgb1_is_woken_before_its_first_colour_or_white_command(self):
        for colour in [False, True]:
            with self.subTest(colour=colour):
                device, client = self.make_device()
                if colour:
                    self.assertTrue(await device.set_rgb(240, 100, 30))
                else:
                    self.assertTrue(await device.turn_on(brightness=30, color_temp_kelvin=4500))
                first, second = self.written(client)
                self.assertEqual(first, POWER_ON)
                self.assertEqual(second[1], 0x8F if colour else 0x90)
                self.assertEqual(second[3:9], bytes.fromhex("12 34 56 78 9a bc"))
                self.assertTrue(device.is_on)

    async def test_power_is_sent_once_then_again_after_off_or_a_lost_connection(self):
        device, client = self.make_device()
        await device.set_rgb(240, 100, 30)
        await device.set_rgb(120, 100, 40)
        self.assertEqual(self.written(client).count(POWER_ON), 1)
        await device.turn_off()
        await device.turn_on(brightness=30)
        self.assertEqual(self.written(client).count(POWER_ON), 2)
        # The light lost power and came back: it may be in standby again.
        device._handle_disconnect(client)
        with patch.object(protocol, "establish_connection", AsyncMock(return_value=client)):
            await device.turn_on(brightness=50)
        self.assertEqual(self.written(client).count(POWER_ON), 3)

    async def test_brightness_alone_keeps_an_rgb_light_in_colour(self):
        device, client = self.make_device("NEEWER-RGB660")
        await device.set_rgb(240, 100, 30)
        await device.turn_on(brightness=60)
        last = self.written(client)[-1]
        self.assertEqual(last[1], 0x86, "still the HSI command, not CCT")
        self.assertEqual(last[3] | (last[4] << 8), 240)
        self.assertEqual(last[6], 60)

    def test_colour_temperature_is_sent_as_kelvin_over_a_hundred(self):
        device, _ = self.make_device("NW-20220014&0A1B2C")
        self.assertEqual(device.model_name, "CB60B")
        for kelvin, byte in [(2700, 27), (4400, 44), (6500, 65), (9000, 65), (1000, 27)]:
            device._kelvin = device._snap_kelvin(kelvin)
            self.assertEqual(device._build_cct_command(50, device._temp_byte())[4], byte, kelvin)

    async def test_the_connection_is_reused_until_it_is_closed(self):
        device, client = self.make_device(connected=False)
        with patch.object(protocol, "establish_connection", AsyncMock(return_value=client)) as connect:
            self.assertTrue(await device.set_rgb(120, 100, 30))
            self.assertTrue(await device.set_rgb(240, 100, 40))
            self.assertTrue(await device.turn_off())
            self.assertTrue(await device.turn_on(brightness=30))
            connect.assert_awaited_once()
            client.disconnect.assert_not_awaited()
            await device.disconnect()
            client.disconnect.assert_awaited_once()
            self.assertTrue(await device.turn_on(brightness=30))
            self.assertEqual(connect.await_count, 2)

    async def test_with_no_time_to_keep_it_the_connection_closes_after_each_command(self):
        device, client = self.make_device(connected=False)
        device.set_defaults(100, 3200, disconnect_after=0)
        with patch.object(protocol, "establish_connection", AsyncMock(return_value=client)) as connect:
            await device.turn_on(brightness=30)
            await device.turn_on(brightness=40)
        self.assertEqual(connect.await_count, 2)
        self.assertEqual(client.disconnect.await_count, 2)

    async def test_simultaneous_connects_share_one_connection(self):
        device, client = self.make_device(connected=False)

        async def establish(*args, **kwargs):
            await asyncio.sleep(0)
            return client

        with patch.object(protocol, "establish_connection", AsyncMock(side_effect=establish)) as connect:
            self.assertEqual(await asyncio.gather(device.connect(), device.connect()), [True, True])
            connect.assert_awaited_once()

    async def test_a_light_that_stops_answering_fails_and_keeps_its_old_state(self):
        device, client = self.make_device()
        client.write_gatt_char.side_effect = protocol.BleakError("Connection lost")
        unreachable = AsyncMock(side_effect=protocol.BleakError("not found"))
        with patch.object(protocol, "establish_connection", unreachable):
            self.assertFalse(await device.set_rgb(120, 100, 30))
        self.assertFalse(device.is_connected)
        self.assertFalse(device.is_on)
        self.assertEqual(device.brightness, 100)

    async def test_a_stale_connection_is_opened_again_once(self):
        device, stale = self.make_device()
        stale.write_gatt_char.side_effect = protocol.BleakError("Connection lost")
        fresh = SimpleNamespace(is_connected=True, disconnect=AsyncMock(), write_gatt_char=AsyncMock())
        with patch.object(protocol, "establish_connection", AsyncMock(return_value=fresh)) as connect:
            self.assertTrue(await device.turn_on(brightness=30))
        connect.assert_awaited_once()
        self.assertEqual(self.written(fresh)[0], POWER_ON)

    async def test_other_lights_are_turned_off_with_brightness_zero(self):
        device, client = self.make_device("NEEWER-RGB660")
        self.assertTrue(await device.turn_off())
        (data,) = self.written(client)
        self.assertEqual(data[1:4], bytes([0x87, 2, 0]))


if __name__ == "__main__":
    unittest.main()
