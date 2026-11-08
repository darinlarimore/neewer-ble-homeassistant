"""RGB1 protocol regressions, without starting Home Assistant."""

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


class RGB1Tests(unittest.IsolatedAsyncioTestCase):
    def make_device(self, name="NW-20200015&FFFFFFFF"):
        device = NeewerLightDevice(BLEDevice("12:34:56:78:9A:BC", name, {}))
        client = SimpleNamespace(
            is_connected=True,
            disconnect=AsyncMock(),
            write_gatt_char=AsyncMock(),
        )
        device._client = client
        device._connected = True
        return device, client

    def test_advertised_name_selects_rgb_and_infinity(self):
        device, _ = self.make_device()
        self.assertEqual(device.model_name, "RGB1")
        self.assertTrue(device.supports_rgb)
        self.assertTrue(device.uses_infinity_protocol)

    async def test_off_sends_power_off_without_erasing_brightness(self):
        device, client = self.make_device()
        self.assertTrue(await device.turn_off())
        data = client.write_gatt_char.call_args.args[1]
        self.assertEqual(data, bytes.fromhex("78 8d 08 12 34 56 78 9a bc 81 02 fa"))
        self.assertEqual(device.brightness, 100)
        self.assertFalse(device.is_on)
        client.disconnect.assert_not_awaited()

    async def test_colour_and_white_commands_wake_the_rgb1(self):
        for colour in [False, True]:
            with self.subTest(colour=colour):
                device, client = self.make_device()
                if colour:
                    self.assertTrue(await device.set_rgb(240, 100, 30))
                else:
                    self.assertTrue(await device.turn_on(brightness=30, color_temp_kelvin=4500))
                writes = client.write_gatt_char.call_args_list
                self.assertEqual(len(writes), 2)
                self.assertEqual(writes[0].args[1], bytes.fromhex("78 8d 08 12 34 56 78 9a bc 81 01 f9"))
                self.assertEqual(writes[1].args[1][1], 0x8F if colour else 0x90)
                self.assertEqual(writes[1].args[1][3:9], bytes.fromhex("12 34 56 78 9a bc"))
                self.assertTrue(device.is_on)

    async def test_rgb1_reuses_connection_across_adjustments_and_standby(self):
        device, client = self.make_device()
        device._client = None
        device._connected = False
        with patch.object(protocol, "establish_connection", AsyncMock(return_value=client)) as connect:
            self.assertTrue(await device.set_rgb(120, 100, 30))
            self.assertTrue(await device.set_rgb(240, 100, 40))
            connect.assert_awaited_once()
            client.disconnect.assert_not_awaited()
            self.assertTrue(await device.turn_off())
            client.disconnect.assert_not_awaited()
            self.assertTrue(await device.turn_on(brightness=30))
            connect.assert_awaited_once()
            await device.disconnect()
            client.disconnect.assert_awaited_once()
            self.assertTrue(await device.turn_on(brightness=30))
            self.assertEqual(connect.await_count, 2)
            await device.disconnect()

    async def test_simultaneous_commands_share_the_initial_connection(self):
        device, client = self.make_device()
        device._client = None
        device._connected = False

        async def establish(*args, **kwargs):
            await asyncio.sleep(0)
            return client

        with patch.object(protocol, "establish_connection", AsyncMock(side_effect=establish)) as connect:
            self.assertEqual(await asyncio.gather(device.connect(), device.connect()), [True, True])
            connect.assert_awaited_once()
        await device.disconnect()

    async def test_write_failure_releases_the_connection(self):
        device, client = self.make_device()
        client.write_gatt_char.side_effect = protocol.BleakError("Connection lost")
        self.assertFalse(await device.set_rgb(120, 100, 30))
        client.disconnect.assert_awaited_once()
        self.assertFalse(device.is_connected)

    async def test_existing_models_keep_brightness_zero_off(self):
        device, client = self.make_device("NEEWER-RGB660")
        self.assertTrue(await device.turn_off())
        data = client.write_gatt_char.call_args.args[1]
        self.assertEqual(data[1:4], bytes([0x87, 2, 0]))
        client.write_gatt_char.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
