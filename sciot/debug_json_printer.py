import paho.mqtt.client as mqtt
import json
from datetime import datetime

LOG_FILE = "sensor_log.jsonl"

def on_message(client, userdata, message):
    try:
        topic = message.topic
        payload_str = message.payload.decode("utf-8")

        # Filter for Node 2 
        # (Note: If you switch to "Named Topics", change this to match your new name, e.g., "CarSensor")
        if "car" in topic:
            
            # 1. Parse the incoming payload string into a Python dictionary
            try:
                payload_data = json.loads(payload_str)
            except json.JSONDecodeError:
                # Handle cases where payload isn't JSON (like simple "true" status messages)
                payload_data = {"raw_value": payload_str}

            # 2. Create a NEW dictionary that combines everything
            # This makes it much easier to debug because everything is in one object
            combined_data = {
                "timestamp": str(datetime.now()),
                "topic": topic,
                "data": payload_data
            }

            # 3. Convert the combined dictionary to a Pretty JSON string
            pretty_json = json.dumps(combined_data, indent=4)
            
            # 4. Print to Console
            print(f"\n--- New Message ---")
            print(pretty_json)
            
            # 5. Save to File
            with open(LOG_FILE, "a") as f:
                f.write(pretty_json + "\n")
                
            print(f"--- Saved to {LOG_FILE} ---")

    except Exception as e:
        print(f"Error: {e}")

# Setup Client
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "JSON_Logger")
client.on_message = on_message

print("Connecting to MQTT...")
client.connect("127.0.0.1", 1883, 60)

# Subscribe to Z-Wave topics
client.subscribe("zwave/#")

print(f"Logging data to {LOG_FILE}...")
client.loop_forever()