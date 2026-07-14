########################## extra peiece of code no need now# extra peiece of code no need now###############################

# sensor_reader.py
# WebSocket for fast car-node events, MQTT for cabin sensor + outbound comms


import asyncio
import websockets
import json
import paho.mqtt.client as mqtt
import time
import threading
from sensor_config import *
# from pddl_generator import generate_problem
# from planner_runner import run_planner
from actuator_controller import execute_action

# ── Shared state ────────────────────────────────────────────────────────────
sensor_state = {
    "damage_signal":    False,
    "motion_outside":   False,
    "motion_inside":    False,
    "cabin_too_hot":    False,
    "temperature_cabin": 0.0,
    "cover_status":     0,
}
last_plan_time  = 0
PLAN_COOLDOWN   = 10          # seconds

mqtt_client = None            # set after MQTT connects


# ── Planning logic (shared between both readers) ─────────────────────────────
def trigger_planning():
    global last_plan_time
    if (time.time() - last_plan_time) < PLAN_COOLDOWN:
        return
    last_plan_time = time.time()

    print("\n" + "="*50)
    print("[Planner] 🧠 Planning cycle triggered")
    print(f"  State: {sensor_state}")

    generate_problem(
        damage_signal  = sensor_state["damage_signal"],
        motion_outside = sensor_state["motion_outside"],
        motion_inside  = sensor_state["motion_inside"],
        cabin_too_hot  = sensor_state["cabin_too_hot"],
    )

    plan = run_planner()
    print(f"[Planner] 📋 Plan: {plan}")

    for action in plan:
        execute_action(action, mqtt_client, sensor_state.copy())

    if mqtt_client:
        mqtt_client.publish("sentinel/state", json.dumps(sensor_state))
        mqtt_client.publish("sentinel/plan",  json.dumps({"plan": plan}))

    sensor_state["damage_signal"] = False   # reset after handling


# ── WebSocket reader — catches raw Z-Wave events instantly ──────────────────
async def websocket_reader():
    """
    Connects to Z-Wave JS UI WebSocket.
    This fires on EVERY value change event from the Z-Wave stick,
    before MQTT even processes it. Use this for the car (damage) sensor.
    """
    uri = "ws://localhost:3000"

    while True:
        try:
            print("[WS] Connecting to Z-Wave JS WebSocket...")
            async with websockets.connect(uri) as ws:
                print("[WS] ✅ Connected — listening for car sensor events")

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    # Z-Wave JS sends value update events like:
                    # {"type":"event","event":{"source":"node","event":"value updated",
                    #  "nodeId":4,"args":{"commandClassName":"...","property":"...","newValue":...}}}

                    if msg.get("type") != "event":
                        continue

                    event = msg.get("event", {})
                    if event.get("event") != "value updated":
                        continue

                    node_id = event.get("nodeId")
                    args    = event.get("args", {})
                    prop    = args.get("property", "")
                    new_val = args.get("newValue")

                    # Node 4 = your "car" external sensor
                    # Check your Z-Wave JS UI for the correct nodeId
                    if node_id != 4:
                        continue

                    print(f"[WS] Node {node_id} | {prop} = {new_val}")

                    changed = False

                    if prop == "Motion Sensor Status" or "motion" in prop.lower():
                        is_motion = (new_val == 8)
                        if is_motion != sensor_state["motion_outside"]:
                            sensor_state["motion_outside"] = is_motion
                            if is_motion:
                                print("🚨 [WS] MOTION on car sensor → damage signal!")
                                sensor_state["damage_signal"] = True
                                changed = True

                    elif prop == "Cover Status" or "cover" in prop.lower():
                        sensor_state["cover_status"] = new_val
                        if new_val == 3:
                            print("⚠️  [WS] TAMPER on car sensor → damage signal!")
                            sensor_state["damage_signal"] = True
                            changed = True
                        elif new_val == 0:
                            print("[WS] Cover status cleared")

                    elif prop == "Any" or "binary" in prop.lower():
                        if new_val is True:
                            print("📡 [WS] Binary trigger fired")
                            sensor_state["damage_signal"] = True
                            changed = True

                    if changed:
                        # Run planning in a thread so we don't block the WebSocket
                        threading.Thread(
                            target=trigger_planning, daemon=True
                        ).start()

        except Exception as e:
            print(f"[WS] Connection error: {e} — reconnecting in 5s")
            await asyncio.sleep(5)


# ── MQTT reader — cabin sensor + outbound comms ──────────────────────────────
def on_mqtt_connect(client, userdata, flags, rc, props):
    client.subscribe("zwave/carCabinSensor/#")   # cabin only via MQTT
    print("[MQTT] ✅ Connected — subscribed to cabin sensor")


def on_mqtt_message(client, userdata, message):
    topic = message.topic
    if any(k in topic for k in ["configuration", "version", "lastActive", "battery"]):
        return

    try:
        data  = json.loads(message.payload.decode("utf-8"))
        value = data.get("value")
        if value is None:
            return
    except Exception:
        return

    changed = False

    if "Motion_sensor_status" in topic:
        sensor_state["motion_inside"] = (value == MOTION_ACTIVE)
        if sensor_state["motion_inside"]:
            print(f"🚶 [MQTT/CABIN] Motion inside cabin")
            changed = True

    elif "Air_temperature" in topic:
        sensor_state["temperature_cabin"] = value
        new_hot = (value >= TEMP_HEATSTROKE_C)
        if new_hot != sensor_state["cabin_too_hot"]:
            sensor_state["cabin_too_hot"] = new_hot
            if new_hot:
                print(f"🌡️  [MQTT/CABIN] HEATSTROKE RISK: {value}°C")
                changed = True

    if changed:
        threading.Thread(target=trigger_planning, daemon=True).start()


def start_mqtt():
    global mqtt_client
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "SentinelReader")
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message
    mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
    mqtt_client.loop_forever()   # blocking — runs in its own thread


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🚗 Sentinel Car — starting up")
    print("   WebSocket → car sensor (instant damage detection)")
    print("   MQTT      → cabin sensor + outbound to laptop\n")

    # MQTT in background thread
    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()

    # WebSocket in main asyncio loop (fast path)
    asyncio.run(websocket_reader())