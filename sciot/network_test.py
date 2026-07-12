# import paho.mqtt.client as mqtt

# def on_connect(client, userdata, flags, rc):
#     print(f"Connected with result code {rc}")

# client = mqtt.Client()
# client.on_connect = on_connect
# # Replace with your actual Pi IP
# client.connect("100.74.16.98", 1883, 60) 
# client.loop_forever()

import paho.mqtt.client as mqtt

# This is the callback function that triggers when a message is received
def on_message(client, userdata, message):
    print(f"Received message: {message.payload.decode('utf-8')} on topic {message.topic}")

# Setup the client
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_message = on_message

# Connect to your Raspberry Pi broker
client.connect("100.74.16.98", 1883, 60)

# Subscribe to the topic
client.subscribe("home/temperature")

# Keep listening for messages
client.loop_forever()
