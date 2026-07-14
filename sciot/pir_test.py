import paho.mqtt.client as mqtt

# Point this to the topic you identified earlier
TOPIC = "zwave/car/notification/endpoint_0/Home_Security/Motion_sensor_status"

def on_message(client, userdata, msg):
    print(f"[{msg.topic}] Message received: {msg.payload.decode()}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_message = on_message
client.connect("127.0.0.1", 1883)
client.subscribe(TOPIC)
client.loop_forever()