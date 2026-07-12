# # test_queue_persistence.py
# import streamlit as st
# import queue
# import time

# @st.cache_resource
# def get_queue():
#     q = queue.Queue()
#     q.put("initial_item")  # seed it once
#     return q

# q = get_queue()

# st.write(f"Queue size right now: {q.qsize()}")

# if st.button("Add item"):
#     q.put(f"item_at_{time.time()}")

# if st.button("Drain one item"):
#     if not q.empty():
#         st.write(f"Drained: {q.get()}")
#     else:
#         st.write("Queue empty")

# st.write(f"Queue size after action: {q.qsize()}")

# dashboard.py — debug version, manual refresh only
import streamlit as st
import paho.mqtt.client as mqtt
import json
import threading
import queue

st.set_page_config(page_title="Sentinel Car Dashboard — DEBUG", layout="wide")

DASHBOARD_MQTT_HOST = "100.74.16.98"

@st.cache_resource
def get_queue():
    return queue.Queue()

@st.cache_resource
def get_all_messages_log():
    """Keeps a permanent log of every message ever received, for debugging."""
    return []

def on_connect(client, userdata, flags, rc, props):
    print(f"[MQTT] Connected: {rc}")
    client.subscribe("zwave/#")
    client.subscribe("sentinel/#")

def on_message(client, userdata, message):
    q = get_queue()
    log = get_all_messages_log()
    entry = f"{message.topic} = {message.payload.decode()[:100]}"
    log.append(entry)
    q.put((message.topic, message.payload.decode()))
    print(f"[MQTT] #{len(log)}: {entry}")

@st.cache_resource
def start_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "DebugDashboard")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(DASHBOARD_MQTT_HOST, 1883, 60)
    threading.Thread(target=client.loop_forever, daemon=True).start()
    return client

start_mqtt()
q = get_queue()
log = get_all_messages_log()

st.title("🔧 MQTT Debug View")
st.write(f"**Total messages ever received (this session): {len(log)}**")
st.write(f"**Items currently in queue (undrained): {q.qsize()}**")

if st.button("🔄 Manual refresh"):
    st.rerun()

st.divider()
st.subheader("Full message log (most recent first)")
for entry in reversed(log[-50:]):   # last 50
    st.text(entry)