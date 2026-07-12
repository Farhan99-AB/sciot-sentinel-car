# sensor_config.py — v3 (Added Disarm Command Topic)
NODE_CAR    = "car"
NODE_CABIN  = "carCabinSensor"

# ── Z-Wave Topics ──────────────────────────────────────────
TOPIC_CAR_MOTION    = f"zwave/{NODE_CAR}/notification/endpoint_0/Home_Security/Motion_sensor_status"
TOPIC_CAR_TAMPER    = f"zwave/{NODE_CAR}/notification/endpoint_0/Home_Security/Cover_status"
TOPIC_BINARY_ANY    = f"zwave/{NODE_CAR}/sensor_binary/endpoint_0/Any"
TOPIC_CAR_TEMP      = f"zwave/{NODE_CAR}/sensor_multilevel/endpoint_0/Air_temperature"
TOPIC_CAR_HUMID     = f"zwave/{NODE_CAR}/sensor_multilevel/endpoint_0/Humidity"
TOPIC_CAR_LIGHT     = f"zwave/{NODE_CAR}/sensor_multilevel/endpoint_0/Illuminance"
TOPIC_CAR_UV        = f"zwave/{NODE_CAR}/sensor_multilevel/endpoint_0/Ultraviolet"

# TOPIC_CABIN_MOTION  = f"zwave/{NODE_CABIN}/notification/endpoint_0/Home_Security/Motion_sensor_status"
# TOPIC_CABIN_TAMPER  = f"zwave/{NODE_CABIN}/notification/endpoint_0/Home_Security/Cover_status"
# TOPIC_CABIN_TEMP    = f"zwave/{NODE_CABIN}/sensor_multilevel/endpoint_0/Air_temperature"
# TOPIC_CABIN_HUMID   = f"zwave/{NODE_CABIN}/sensor_multilevel/endpoint_0/Humidity"
# TOPIC_CABIN_UV      = f"zwave/{NODE_CABIN}/sensor_multilevel/endpoint_0/Ultraviolet"
# TOPIC_CABIN_LIGHT   = f"zwave/{NODE_CABIN}/sensor_multilevel/endpoint_0/Illuminance"

# ── System Topics ──────────────────────────────────────────
TOPIC_DISARM        = "sentinel/command/disarm"

# ── Trigger values ─────────────────────────────────────────
MOTION_ACTIVE       = 8
MOTION_CLEAR        = 0
TAMPER_ACTIVE       = 3
TAMPER_CLEAR        = 0

# ── Safety thresholds ──────────────────────────────────────
TEMP_HEATSTROKE_C   = 35
UV_HIGH             = 6
ILLUMINANCE_OCCUPIED = 50

# ── MQTT ───────────────────────────────────────────────────
MQTT_HOST = "127.0.0.1" # Keep local for Pi scripts
MQTT_PORT = 1883

# ── Optional: pull fresh readings after a disarm/reset ──────
# zwave-js-ui can be asked over MQTT to re-read a node's values. Fill these in
# to actively refresh after a reset; leave as None to simply wait for the
# sensor's next periodic report.
ZWAVE_GATEWAY_NAME = None   # your zwave-js-ui gateway name, e.g. "zwave-js-ui"
CAR_NODE_ID        = None   # the Aeon sensor's Z-Wave node id, e.g. 2