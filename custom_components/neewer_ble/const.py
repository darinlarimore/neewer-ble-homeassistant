"""Constants for the Neewer BLE integration."""

DOMAIN = "neewer_ble"

# BLE Service and Characteristic UUIDs
# Neewer uses a custom GATT service for light control
NEEWER_SERVICE_UUID = "69400001-b5a3-f393-e0a9-e50e24dcca99"
NEEWER_WRITE_CHARACTERISTIC_UUID = "69400002-b5a3-f393-e0a9-e50e24dcca99"
NEEWER_NOTIFY_CHARACTERISTIC_UUID = "69400003-b5a3-f393-e0a9-e50e24dcca99"

# Status query commands (per NeewerLite-Python)
CMD_GET_POWER_STATUS = [0x78, 0x85, 0x00, 0xFD]  # Response type 2: [3]=1 ON, [3]=2 STANDBY
CMD_GET_CHANNEL_STATUS = [0x78, 0x84, 0x00, 0xFC]  # Response type 1: current channel/mode

# Supported light models with their specifications
# Format based on NeewerLite-Python:
#   "model_code": {
#       "name": str,
#       "rgb": bool,                    # Supports HSI/RGB mode
#       "cct_range": (min_k, max_k),    # Color temperature range
#       "cct_only": bool,               # True = use separate 0x82/0x83 commands (old CCT-only lights)
#       "light_type": int,              # 0=standard, 1=infinity, 2=infinity-hybrid
#       "effects": bool,                # Optional: built-in scene effects via the short 0x8B command
#       "real_power": bool,             # Optional: "off" sends the power command instead of brightness 0
#                                       #   (only for lights that stay reachable over Bluetooth in standby)
#   }
#
# Light types per NeewerLite-Python:
#   0 = Old-style: CCT uses [0x78, 0x87, 0x02, bri, temp] (5 bytes, no GM)
#   1 = Infinity: Full infinity protocol with MAC address embedded
#   2 = Infinity-hybrid: CCT uses [0x78, 0x87, 0x03, bri, temp, GM] (6 bytes with GM)

SUPPORTED_MODELS = {
    # MS Series (COB lights) - Infinity protocol
    "20220035": {"name": "MS150B", "rgb": False, "cct_range": (2700, 6500), "cct_only": False, "light_type": 1},
    "20230080": {"name": "MS60C", "rgb": True, "cct_range": (2700, 6500), "cct_only": False, "light_type": 1},

    # RGB Panel lights - Standard protocol (type 0)
    "RGB660PRO": {"name": "RGB660 PRO", "rgb": True, "cct_range": (3200, 5600), "cct_only": False, "light_type": 0},
    "RGB660": {"name": "RGB660", "rgb": True, "cct_range": (3200, 5600), "cct_only": False, "light_type": 0},
    "RGB480": {"name": "RGB480", "rgb": True, "cct_range": (3200, 5600), "cct_only": False, "light_type": 0},
    "RGB530": {"name": "RGB530", "rgb": True, "cct_range": (3200, 5600), "cct_only": False, "light_type": 0},
    "RGB530PRO": {"name": "RGB530 PRO", "rgb": True, "cct_range": (3200, 5600), "cct_only": False, "light_type": 0},
    "RGB176": {"name": "RGB176", "rgb": True, "cct_range": (3200, 5600), "cct_only": False, "light_type": 0},
    "RGB960": {"name": "RGB960", "rgb": True, "cct_range": (3200, 5600), "cct_only": False, "light_type": 0},

    # SL/SNL Series (Bi-color panels) - CCT-only lights use separate commands
    "SL80": {"name": "SL-80", "rgb": False, "cct_range": (3200, 8500), "cct_only": True, "light_type": 0},
    "SNL660": {"name": "SNL-660", "rgb": False, "cct_range": (3200, 5600), "cct_only": True, "light_type": 0},
    "SNL530": {"name": "SNL-530", "rgb": False, "cct_range": (3200, 5600), "cct_only": True, "light_type": 0},
    "SNL480": {"name": "SNL-480", "rgb": False, "cct_range": (3200, 5600), "cct_only": True, "light_type": 0},

    # GL Series (Key lights) - Infinity protocol
    "20220001": {"name": "GL1", "rgb": False, "cct_range": (2900, 7000), "cct_only": False, "light_type": 1},

    # CB60B (70 W bi-color COB) - advertises as "NW-20220014&..." but takes the standard commands.
    # Checked on two units: CCT 0x87 with temperature bytes 27-65, effects 0x8B, power 0x81 on/off,
    # and it keeps advertising and accepts connections while in standby.
    "20220014": {"name": "CB60B", "rgb": False, "cct_range": (2700, 6500), "cct_only": False, "light_type": 0,
                 "effects": True, "real_power": True},

    # CB Series - Infinity protocol
    "20220051": {"name": "CB100C", "rgb": True, "cct_range": (2700, 6500), "cct_only": False, "light_type": 1},
    "20220055": {"name": "CB300B", "rgb": False, "cct_range": (2700, 6500), "cct_only": False, "light_type": 1},

    # RGB512/RGB800 - Infinity-hybrid (type 2)
    "RGB512": {"name": "RGB512", "rgb": True, "cct_range": (2500, 10000), "cct_only": False, "light_type": 2},
    "RGB800": {"name": "RGB800", "rgb": True, "cct_range": (2500, 10000), "cct_only": False, "light_type": 2},

    # RGB1 light wand - advertises as "NW-20200015&..." and takes the Infinity commands; the standard
    # ones are ignored. Brightness 0 leaves its LEDs lit, so "off" is the power command, and it stays
    # reachable over Bluetooth in standby. Checked on one unit through an ESPHome Bluetooth proxy (#11).
    "20200015": {"name": "RGB1", "rgb": True, "cct_range": (3200, 5600), "cct_only": False, "light_type": 1,
                 "real_power": True},

    # Light wands - Standard protocol
    "TL60": {"name": "TL60 RGB", "rgb": True, "cct_range": (2700, 6500), "cct_only": False, "light_type": 0},
}

# Default values
DEFAULT_BRIGHTNESS = 100
DEFAULT_COLOR_TEMP = 3200

# Options flow config keys
CONF_DEFAULT_BRIGHTNESS = "default_brightness"
CONF_DEFAULT_COLOR_TEMP = "default_color_temp"
CONF_DISCONNECT_AFTER = "disconnect_after"

# Config entry data: the name the light advertises (it carries the model code)
CONF_LOCAL_NAME = "local_name"

# Seconds the Bluetooth connection stays open after the last command.
# Connecting takes about 3 s, a command on an open connection a few milliseconds.
# 0 disconnects after every command (the light is then free for the Neewer app at once).
DEFAULT_DISCONNECT_AFTER = 600
MAX_DISCONNECT_AFTER = 86400

# Built-in scene effects of bi-color lights (short 0x8B command, from NeewerLite-Python).
# Each entry: effect name -> (effect id, parameter layout). Layout items:
#   "bri" brightness, "dim" a fifth of the brightness, "cct" temperature byte,
#   "cct_min"/"cct_max" the light's temperature range, "gm" green-magenta (neutral),
#   "speed", "sparks", or a plain number.
EFFECT_OFF = "off"
CCT_EFFECTS: dict[str, tuple[int, tuple]] = {
    "Lightning": (0x01, ("bri", "cct", "speed")),
    "Paparazzi": (0x02, ("bri", "cct", "gm", "speed")),
    "Defective bulb": (0x03, ("bri", "cct", "gm", "speed")),
    "Explosion": (0x04, ("bri", "cct", "gm", "speed", "sparks")),
    "Welding": (0x05, ("dim", "bri", "cct", "gm", "speed")),
    "CCT flash": (0x06, ("bri", "cct", "gm", "speed")),
    "CCT pulse": (0x08, ("bri", "cct", "gm", "speed")),
    "Candlelight": (0x0B, ("dim", "bri", "cct", "gm", "speed", "sparks")),
    "CCT loop": (0x0D, ("bri", "cct_min", "cct_max", "speed")),
    "Brightness loop": (0x0E, (0, "dim", "bri", 0, 0, "cct", "speed")),
    "TV screen": (0x0F, ("dim", "bri", "cct", "gm", "speed")),
    "Fireworks": (0x10, ("bri", 0, "speed", "sparks")),
}
EFFECT_SPEED = 5
EFFECT_SPARKS = 5
EFFECT_GM = 50

# Color temperature conversion
# Neewer uses a 0-100 scale internally for color temp
# We need to map Kelvin to this scale
MIN_MIREDS = 153  # ~6500K
MAX_MIREDS = 370  # ~2700K

# Scan timeout
BLE_SCAN_TIMEOUT = 10

# Connection retry settings
MAX_CONNECTION_RETRIES = 3
CONNECTION_RETRY_DELAY = 1.0

# Platforms
PLATFORMS = ["light"]
