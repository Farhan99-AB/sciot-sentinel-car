# # simulate_sensors.py
# # Run this on the Pi to inject test sensor readings into the pipeline
# # Usage: python3 simulate_sensors.py --scenario heatstroke
# #        python3 simulate_sensors.py --scenario uv
# #        python3 simulate_sensors.py --scenario damage
# #        python3 simulate_sensors.py --scenario clear

# import paho.mqtt.client as mqtt
# import json
# import argparse
# import time
# from datetime import datetime

# MQTT_HOST = "127.0.0.1"
# MQTT_PORT = 1883

# # These match exactly what Z-Wave JS UI would publish
# SCENARIOS = {
#     "heatstroke": {
#         "description": "High cabin temperature with occupant inside",
#         "messages": [
#             # Simulate cabin temp above threshold (35°C)
#             ("zwave/car/sensor_multilevel/endpoint_0/Air_temperature",
#              {"time": 0, "value": 38.5, "nodeName": "car"}),
#             # Simulate occupant motion in cabin
#             ("zwave/car/notification/endpoint_0/Home_Security/Motion_sensor_status",
#              {"time": 0, "value": 8, "nodeName": "car"}),
#         ]
#     },
#     "uv": {
#         "description": "High UV index with occupant inside",
#         "messages": [
#             ("zwave/car/sensor_multilevel/endpoint_0/Ultraviolet",
#              {"time": 0, "value": 8, "nodeName": "car"}),
#             ("zwave/car/notification/endpoint_0/Home_Security/Motion_sensor_status",
#              {"time": 0, "value": 8, "nodeName": "car"}),
#         ]
#     },
#     "damage": {
#         "description": "Physical damage / tamper on car sensor",
#         "messages": [
#             ("zwave/car/sensor_binary/endpoint_0/Any",
#              {"time": 0, "value": True}),
#             ("zwave/car/notification/endpoint_0/Home_Security/Motion_sensor_status",
#              {"time": 0, "value": 8}),
#         ]
#     },
#     "clear": {
#         "description": "Reset all values to safe/idle",
#         "messages": [
#             ("zwave/car/sensor_multilevel/endpoint_0/Air_temperature",
#              {"time": 0, "value": 24.0, "nodeName": "car"}),
#             ("zwave/car/sensor_multilevel/endpoint_0/Ultraviolet",
#              {"time": 0, "value": 0, "nodeName": "car"}),
#             ("zwave/car/notification/endpoint_0/Home_Security/Motion_sensor_status",
#              {"time": 0, "value": 0, "nodeName": "car"}),
#             ("zwave/car/notification/endpoint_0/Home_Security/Motion_sensor_status",
#              {"time": 0, "value": 0}),
#             ("zwave/car/sensor_binary/endpoint_0/Any",
#              {"time": 0, "value": False}),
#         ]
#     }
# }

# def run_scenario(scenario_name: str):
#     scenario = SCENARIOS.get(scenario_name)
#     if not scenario:
#         print(f"Unknown scenario. Choose: {list(SCENARIOS.keys())}")
#         return

#     client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Simulator")
#     client.connect(MQTT_HOST, MQTT_PORT, 60)
#     client.loop_start()

#     print(f"\n[SIM] Scenario: {scenario['description']}")

#     for topic, payload in scenario["messages"]:
#         payload["time"] = int(datetime.now().timestamp() * 1000)
#         msg = json.dumps(payload)
#         client.publish(topic, msg, retain=False)
#         print(f"[SIM] Published → {topic}: {msg}")
#         time.sleep(0.2)  # small gap between messages

#     client.loop_stop()
#     client.disconnect()
#     print(f"[SIM] Done — coordinator should have reacted\n")

# if __name__ == "__main__":
#     parser = argparse.ArgumentParser()
#     parser.add_argument("--scenario", required=True, choices=list(SCENARIOS.keys()))
#     args = parser.parse_args()
#     run_scenario(args.scenario)



# simulate_sensors.py
# Run this on the Pi to inject test sensor readings into the pipeline
# Usage: python3 simulate_sensors.py --scenario heatstroke
#        python3 simulate_sensors.py --scenario uv
#        python3 simulate_sensors.py --scenario damage
#        python3 simulate_sensors.py --scenario clear

import paho.mqtt.client as mqtt
import json
import argparse
import time
from datetime import datetime

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883

# These match exactly what Z-Wave JS UI would publish
SCENARIOS = {
    "heatstroke": {
        "description": "High cabin temperature with occupant inside",
        "messages": [
            # Simulate cabin temp above threshold (35°C)
            ("zwave/car/sensor_multilevel/endpoint_0/Air_temperature",
             {"time": 0, "value": 38.5, "nodeName": "car"}),
            # Simulate occupant motion in cabin
            ("zwave/car/notification/endpoint_0/Home_Security/Motion_sensor_status",
             {"time": 0, "value": 8, "nodeName": "car"}),
        ]
    },
    "uv": {
        "description": "High UV index with occupant inside",
        "messages": [
            ("zwave/car/sensor_multilevel/endpoint_0/Ultraviolet",
             {"time": 0, "value": 8, "nodeName": "car"}),
            ("zwave/car/notification/endpoint_0/Home_Security/Motion_sensor_status",
             {"time": 0, "value": 8, "nodeName": "car"}),
        ]
    },
    "damage": {
        "description": "Physical damage / tamper on car cover sensor",
        "messages": [
            # Damage is driven ONLY by Cover_status (value 3 = tamper/impact).
            # This is the topic main_coordinator actually reacts to.
            ("zwave/car/notification/endpoint_0/Home_Security/Cover_status",
             {"time": 0, "value": 3, "nodeName": "car"}),
        ]
    },
    "clear": {
        "description": "Reset all values to safe/idle",
        "messages": [
            ("zwave/car/sensor_multilevel/endpoint_0/Air_temperature",
             {"time": 0, "value": 24.0, "nodeName": "car"}),
            ("zwave/car/sensor_multilevel/endpoint_0/Ultraviolet",
             {"time": 0, "value": 0, "nodeName": "car"}),
            ("zwave/car/notification/endpoint_0/Home_Security/Motion_sensor_status",
             {"time": 0, "value": 0, "nodeName": "car"}),
            ("zwave/car/notification/endpoint_0/Home_Security/Cover_status",
             {"time": 0, "value": 0, "nodeName": "car"}),
        ]
    },
    "disarm": {
        "description": "Force the system to disarm and return to IDLE",
        "messages": [
            ("sentinel/command/disarm", 
             {"time": 0, "command": "disarm"}),
        ]
    }
}

def run_scenario(scenario_name: str):
    scenario = SCENARIOS.get(scenario_name)
    if not scenario:
        print(f"Unknown scenario. Choose: {list(SCENARIOS.keys())}")
        return

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Simulator")
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()

    print(f"\n[SIM] Scenario: {scenario['description']}")

    for topic, payload in scenario["messages"]:
        payload["time"] = int(datetime.now().timestamp() * 1000)
        msg = json.dumps(payload)
        client.publish(topic, msg, retain=False)
        print(f"[SIM] Published → {topic}: {msg}")
        time.sleep(0.2)  # small gap between messages

    client.loop_stop()
    client.disconnect()
    print(f"[SIM] Done — coordinator should have reacted\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True, choices=list(SCENARIOS.keys()))
    args = parser.parse_args()
    run_scenario(args.scenario)