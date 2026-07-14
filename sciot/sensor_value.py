# sensor_value.py
import paho.mqtt.client as mqtt
import json
from sensor_config import *

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("✅ Connected to MQTT broker")
        client.subscribe("zwave/#")
        print("👂 Subscribed to zwave/#")
    else:
        print(f"❌ Connection failed: {reason_code}")

def on_disconnect(client, userdata, flags, reason_code, properties):
    print("⚠️  Disconnected — will auto-reconnect")

def on_message(client, userdata, message):
    topic = message.topic
    payload_str = message.payload.decode("utf-8")

    # Skip config/version/manufacturer noise — we don't need these
    skip_keywords = ["configuration", "version", "manufacturer", "wake_up",
                     "lastActive", "status", "battery"]
    if any(k in topic for k in skip_keywords):
        return

    try:
        data = json.loads(payload_str)
        value = data.get("value")
        if value is None:
            return
    except json.JSONDecodeError:
        return

    # ── DAMAGE DETECTION (car node) ─────────────────────────
    if topic == TOPIC_VIBRATION:
        if value == VIBRATION_TRIGGER_VALUE:
            print(f"🚨 [CAR] IMPACT/TAMPER DETECTED — Cover_status={value}")
        else:
            print(f"✅ [CAR] No tamper — Cover_status={value}")

    elif topic == TOPIC_BINARY_ANY:
        print(f"📡 [CAR] Binary trigger: {value}")

    elif topic == TOPIC_CAR_TEMP:
        print(f"🌡️  [CAR-EXT] Temperature: {value}°C")

    elif topic == TOPIC_CAR_HUMID:
        print(f"💧 [CAR-EXT] Humidity: {value}%")

    # ── CABIN MONITORING (carCabinSensor node) ───────────────
    elif topic == TOPIC_MOTION:
        if value == MOTION_ACTIVE_VALUE:
            print(f"🚶 [CABIN] MOTION DETECTED — value={value}")
        else:
            print(f"🏠 [CABIN] Motion clear — value={value}")

    elif topic == TOPIC_CABIN_TEMP:
        flag = " ⚠️  HEATSTROKE RISK" if value >= TEMP_HEATSTROKE_C else ""
        print(f"🌡️  [CABIN] Temperature: {value}°C{flag}")

    elif topic == TOPIC_CABIN_HUMID:
        print(f"💧 [CABIN] Humidity: {value}%")

    elif topic == TOPIC_CABIN_UV:
        flag = " ⚠️  HIGH UV" if value >= UV_HEATSTROKE_THRESHOLD else ""
        print(f"☀️  [CABIN] UV Index: {value}{flag}")

    elif topic == TOPIC_CABIN_LIGHT:
        print(f"💡 [CABIN] Illuminance: {value} lux")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "SentinelCar_Monitor")
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

print("Connecting to MQTT broker...")
client.connect(MQTT_HOST, MQTT_PORT, 60)
client.loop_forever()