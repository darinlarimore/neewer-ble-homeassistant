"""Constants for the Neewer BLE integration."""

DOMAIN = "neewer_ble"

# BLE Service and Characteristic UUIDs
# Neewer uses a custom GATT service for light control
NEEWER_SERVICE_UUID = "69400001-b5a3-f393-e0a9-e50e24dcca9e"
NEEWER_WRITE_CHARACTERISTIC_UUID = "69400002-b5a3-f393-e0a9-e50e24dcca9e"
NEEWER_READ_CHARACTERISTIC_UUID = "69400003-b5a3-f393-e0a9-e50e24dcca9e"

# Command prefixes for different protocols
# Standard Neewer protocol
CMD_PREFIX_STANDARD = [0x78, 0x87]
# Newer "Infinity" protocol used by some models
CMD_PREFIX_INFINITY = [0x78, 0x8A]

# Command types
CMD_POWER_ON = 0x01
CMD_POWER_OFF = 0x02
CMD_SET_CCT = 0x02  # Brightness + Color Temperature
CMD_SET_HSI = 0x03  # Hue, Saturation, Intensity (for RGB models)
CMD_SET_SCENE = 0x04  # Scene/Effect mode

# Supported light models with their specifications
# Format: "model_code": {"name": str, "rgb": bool, "cct_range": (min_kelvin, max_kelvin), "infinity": bool}
SUPPORTED_MODELS = {
    # MS Series (COB lights)
    "20220035": {"name": "MS150B", "rgb": False, "cct_range": (2700, 6500), "infinity": True},
    "20230080": {"name": "MS60C", "rgb": True, "cct_range": (2700, 6500), "infinity": True},
    
    # RGB Panel lights
    "NEEWER-RGB660": {"name": "RGB660", "rgb": True, "cct_range": (3200, 5600), "infinity": False},
    "NEEWER-RGB660 PRO": {"name": "RGB660 PRO", "rgb": True, "cct_range": (3200, 5600), "infinity": False},
    "NEEWER-RGB480": {"name": "RGB480", "rgb": True, "cct_range": (3200, 5600), "infinity": False},
    "NEEWER-RGB530": {"name": "RGB530", "rgb": True, "cct_range": (3200, 5600), "infinity": False},
    "NEEWER-RGB530 PRO": {"name": "RGB530 PRO", "rgb": True, "cct_range": (3200, 5600), "infinity": False},
    
    # SL/SNL Series (Bi-color panels)
    "NEEWER-SL80": {"name": "SL-80", "rgb": False, "cct_range": (3200, 5600), "infinity": False},
    "NEEWER-SNL660": {"name": "SNL-660", "rgb": False, "cct_range": (3200, 5600), "infinity": False},
    
    # GL Series (Key lights)
    "20220001": {"name": "GL1", "rgb": False, "cct_range": (2900, 7000), "infinity": True},
    
    # CB Series
    "20220051": {"name": "CB100C", "rgb": True, "cct_range": (2700, 6500), "infinity": True},
    "20220055": {"name": "CB300B", "rgb": False, "cct_range": (2700, 6500), "infinity": True},
    
    # Light wands
    "NEEWER-RGB1": {"name": "RGB1", "rgb": True, "cct_range": (3200, 5600), "infinity": False},
    "NEEWER-TL60": {"name": "TL60 RGB", "rgb": True, "cct_range": (2700, 6500), "infinity": False},
}

# Default values
DEFAULT_BRIGHTNESS = 100
DEFAULT_COLOR_TEMP = 5600

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
