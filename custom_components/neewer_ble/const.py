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

    # CB Series - Infinity protocol
    "20220051": {"name": "CB100C", "rgb": True, "cct_range": (2700, 6500), "cct_only": False, "light_type": 1},
    "20220055": {"name": "CB300B", "rgb": False, "cct_range": (2700, 6500), "cct_only": False, "light_type": 1},

    # RGB512/RGB800 - Infinity-hybrid (type 2)
    "RGB512": {"name": "RGB512", "rgb": True, "cct_range": (2500, 10000), "cct_only": False, "light_type": 2},
    "RGB800": {"name": "RGB800", "rgb": True, "cct_range": (2500, 10000), "cct_only": False, "light_type": 2},

    # Light wands - Standard protocol
    "RGB1": {"name": "RGB1", "rgb": True, "cct_range": (3200, 5600), "cct_only": False, "light_type": 0},
    "TL60": {"name": "TL60 RGB", "rgb": True, "cct_range": (2700, 6500), "cct_only": False, "light_type": 0},
}

# Default values
DEFAULT_BRIGHTNESS = 100
DEFAULT_COLOR_TEMP = 3200

# Options flow config keys
CONF_DEFAULT_BRIGHTNESS = "default_brightness"
CONF_DEFAULT_COLOR_TEMP = "default_color_temp"

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
