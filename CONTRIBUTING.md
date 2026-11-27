# Contributing

This integration is a community effort and a work in progress. Neewer does not publish its
Bluetooth protocol, so every model here is set up from the reverse-engineering work in
[NeewerLite](https://github.com/keefo/NeewerLite) and
[NeewerLite-Python](https://github.com/taburineagle/NeewerLite-Python), and only a few have been
tried on real hardware. The README's table says which.

There are three ways to help, in order of how much they are needed.

## 1. Test your light and report it

Even "everything works" is worth sending: it moves a model from untested to tested.

1. Install the integration and add your light.
2. Try on, off, brightness, color temperature, and color or effects if your light has them. Check
   the light itself, not only what Home Assistant shows.
3. Open a [light test report](https://github.com/darinlarimore/neewer-ble-homeassistant/issues/new?template=light_report.yml).

### Finding the Bluetooth name

The name a light advertises carries its model code, and model detection depends on it. Find it
under **Settings > Devices & services > Bluetooth > Configure > Advertisement monitor**, or in any
BLE scanner app (nRF Connect, LightBlue). It looks like `NW-20220014&0A1B2C` or `NEEWER-RGB660`.

### Debug logging

Add this to `configuration.yaml` and restart, or use **Enable debug logging** on the integration's
page:

```yaml
logger:
  logs:
    custom_components.neewer_ble: debug
```

The lines starting `Sending to` show the exact bytes sent to the light. Those are what make a
report actionable.

### Trying a pre-release

New work ships as a pre-release first. HACS only offers those when you ask for them: on HACS 2,
turn on the **Pre-release** switch on the integration's device page (Settings > Devices &
services > HACS); on older HACS, choose **Redownload** and turn on **Show beta versions**.

## 2. Add a light

A model is one entry in `SUPPORTED_MODELS` in `custom_components/neewer_ble/const.py`:

```python
"20220014": {"name": "CB60B", "rgb": False, "cct_range": (2700, 6500),
             "cct_only": False, "light_type": 0},
```

| Key | Meaning |
|---|---|
| the dictionary key | The model code or name as it appears in the Bluetooth name (`20220014` for `NW-20220014&...`). |
| `name` | The model, as printed on the light. |
| `rgb` | `True` if the light has RGB color. |
| `cct_range` | Lowest and highest color temperature, in Kelvin. |
| `cct_only` | `True` for older bi-color lights that take brightness and temperature as two separate commands. |
| `light_type` | `0` standard commands, `1` Infinity (commands carry the light's MAC address), `2` Infinity-hybrid. |
| `effects` | Optional. `True` if the light has the built-in scene effects. |
| `real_power` | Optional. `True` only if the light keeps advertising and accepts connections after a power-off command. Others are turned "off" with brightness 0, because the power command puts some lights into a sleep that Bluetooth cannot wake. |

The NeewerLite-Python source lists most models with these values. If you take them from there,
say so in a comment; if you measured them yourself, say that instead.

To try a change, copy `custom_components/neewer_ble/` into your Home Assistant
`config/custom_components/` folder and restart.

## 3. Fix or improve the code

- Keep a pull request to one thing where you can. Connection handling and command bytes reach
  every model, so a small change is much easier to try on other people's lights.
- Say what you tested on. Changes nobody could try on hardware are still welcome; they go out as
  a pre-release first.
- The **Validate** workflow runs the HACS and hassfest checks on every pull request. `hassfest`
  wants the keys in `manifest.json` in order: `domain`, `name`, then alphabetical.
- Update the README's light table when a light's status changes.
- `tests/` holds protocol tests that run without Home Assistant or a light: they check the bytes a
  command sends. Run them with `pip install bleak bleak-retry-connector` and
  `python -m unittest discover -s tests`. A test for the packets your light needs is very welcome.

## Layout

```
custom_components/neewer_ble/
  const.py          models, Bluetooth UUIDs, effects, option names
  neewer_device.py  the Bluetooth connection and the command bytes
  light.py          the Home Assistant light entity
  config_flow.py    discovery, manual setup, options
  brand/            icon and logo
```

## Not affiliated with Neewer

This project is unofficial. Please do not contact Neewer support about it.
