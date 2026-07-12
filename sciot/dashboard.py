# dashboard.py — Sentinel Car live dashboard (v12, redesigned UI)
#
# Two things this screen must always answer clearly:
#   1) CURRENT EXECUTION STATE  -> what the system is doing right now
#                                  (FSM state + the AI response plan in progress)
#   2) CURRENT ENVIRONMENT STATE -> what the sensors are reporting right now
#                                  (temperature / UV / occupant / cover-damage)
#
# Sensor -> logic mapping (single Aeon MultiSensor 6, node "car"):
#   Cover_status (tamper/impact) -> DAMAGE   (damage_signal)
#   Motion_sensor (PIR)          -> OCCUPANT (occupant_detected)  ->  "Occupant inside"
#   Air_temperature              -> heatstroke risk (needs occupant)
#   Ultraviolet                  -> high UV risk    (needs occupant)
#
# This file is DISPLAY ONLY. All decisions live in main_coordinator.py on the Pi.
# There are NO simulate buttons here on purpose — inject test data separately with
# `python3 simulate_sensors.py --scenario <name>` on the Pi.
#
# Streamlit gotcha: the script runs top-to-bottom on every refresh. st.rerun() must
# be the VERY LAST line so nothing gets skipped. Never call it inside a `with` block.

import streamlit as st
import paho.mqtt.client as mqtt
import json
import base64
import pandas as pd
from datetime import datetime
import threading
import queue
import time
import os

# ══════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════
st.set_page_config(page_title="Sentinel Car", page_icon="🚗", layout="wide")

MQTT_HOST = "100.74.16.98"          # Pi's Tailscale IP (dashboard runs on the laptop)
MQTT_PORT = 1883
LOCAL_LOG_FILE = "dashboard_incidents.json"
EVIDENCE_DIR   = "dashboard_evidence"          # saved damage photos, linked into history
os.makedirs(EVIDENCE_DIR, exist_ok=True)

# Display-only copies of the thresholds in sensor_config.py — used purely to
# label the environment cards ("≥ 35°C" etc). They do NOT drive any logic.
TEMP_HEATSTROKE_C = 35
UV_HIGH           = 6

# ══════════════════════════════════════════════════════════════
# Styling — small, self-contained CSS for the cards + FSM stepper
# ══════════════════════════════════════════════════════════════
st.markdown(
    """
    <style>
      .env-card {
        border-radius: 14px; padding: 16px 18px; height: 100%;
        border: 1px solid rgba(255,255,255,0.08);
        background: rgba(255,255,255,0.03);
      }
      .env-card .ec-label { font-size: 13px; letter-spacing:.04em;
        text-transform: uppercase; opacity: .70; margin-bottom: 6px; }
      .env-card .ec-value { font-size: 30px; font-weight: 700; line-height: 1.1; }
      .env-card .ec-sub   { font-size: 13px; opacity: .70; margin-top: 6px; }
      .env-card.ok     { border-left: 5px solid #22c55e; }
      .env-card.info   { border-left: 5px solid #3b82f6; }
      .env-card.warn   { border-left: 5px solid #f59e0b; }
      .env-card.danger { border-left: 5px solid #ef4444;
        background: rgba(239,68,68,0.10); }

      .fsm-row { display:flex; gap:10px; align-items:stretch; margin: 4px 0 2px; }
      .fsm-step { flex:1; text-align:center; padding:12px 6px; border-radius:12px;
        font-weight:600; font-size:14px; opacity:.35;
        border:1px solid rgba(255,255,255,0.10); background: rgba(255,255,255,0.03); }
      .fsm-step .fsm-ico { font-size:20px; display:block; margin-bottom:4px; }
      .fsm-step.active { opacity:1; transform: scale(1.02); }
      .fsm-step.active.s-idle    { border-color:#22c55e; background:rgba(34,197,94,.15); }
      .fsm-step.active.s-trig    { border-color:#eab308; background:rgba(234,179,8,.15); }
      .fsm-step.active.s-resp    { border-color:#ef4444; background:rgba(239,68,68,.15); }
      .fsm-step.active.s-cool    { border-color:#f59e0b; background:rgba(245,158,11,.15); }
      .fsm-arrow { align-self:center; opacity:.35; font-size:18px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ══════════════════════════════════════════════════════════════
# MQTT — persistent connection + queue (must survive every st.rerun())
# ══════════════════════════════════════════════════════════════
@st.cache_resource
def get_queue():
    return queue.Queue()

def on_connect(client, userdata, flags, rc, props):
    for topic in ("sentinel/state", "sentinel/fsm_state", "sentinel/plan",
                  "sentinel/current_step", "sentinel/evidence", "sentinel/alert"):
        client.subscribe(topic)
    print(f"[Dashboard MQTT] connected rc={rc}, subscribed to sentinel/#")

def on_message(client, userdata, msg):
    try:
        get_queue().put((msg.topic, json.loads(msg.payload.decode())))
    except Exception as e:
        print(f"[Dashboard MQTT] parse error on {msg.topic}: {e}")

@st.cache_resource
def start_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Sentinel_Dashboard")
    client.on_connect = on_connect
    client.on_message = on_message
    print(f"[Dashboard MQTT] connecting to {MQTT_HOST}:{MQTT_PORT} ...")
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    threading.Thread(target=client.loop_forever, daemon=True).start()
    return client

mqtt_client = start_mqtt()
q = get_queue()

# ══════════════════════════════════════════════════════════════
# Session state
# ══════════════════════════════════════════════════════════════
defaults = {
    "state": {"temperature_cabin": None, "uv_index": None, "cabin_too_hot": False,
              "cabin_uv_high": False, "occupant_detected": False, "damage_signal": False},
    "fsm": "IDLE",
    "plan": [],
    "scenario": "",
    "step": {},
    "evidence": None,
    "alerts": [],
    "last_update": None,
    "incident_history": [],
    "history_loaded": False,
}
for k, v in defaults.items():
    st.session_state.setdefault(k, v)

# Ask the coordinator to re-send its current state once per session, so a freshly
# opened dashboard isn't blank until the next sensor event.
if "has_polled" not in st.session_state:
    mqtt_client.publish("sentinel/command/poll", json.dumps({"command": "request_state"}))
    st.session_state.has_polled = True
    print("[Dashboard] Sent one-time state poll to coordinator")

# Load local incident history (file may be missing or empty — both are fine)
if not st.session_state.history_loaded:
    try:
        if os.path.exists(LOCAL_LOG_FILE):
            raw = open(LOCAL_LOG_FILE).read().strip()
            st.session_state.incident_history = json.loads(raw) if raw else []
        print(f"[Dashboard] Loaded {len(st.session_state.incident_history)} past incidents")
    except Exception as e:
        print(f"[Dashboard] Could not read {LOCAL_LOG_FILE}, starting fresh: {e}")
        st.session_state.incident_history = []
    st.session_state.history_loaded = True

# ══════════════════════════════════════════════════════════════
# Drain the MQTT queue into session state
# ══════════════════════════════════════════════════════════════
while not q.empty():
    topic, data = q.get()
    st.session_state.last_update = datetime.now()

    if topic == "sentinel/state":
        st.session_state.state = data
        print(f"[Dashboard] state <- {data}")

    elif topic == "sentinel/fsm_state":
        new_fsm = data.get("state", "IDLE")
        st.session_state.fsm = new_fsm
        print(f"[Dashboard] fsm_state <- {new_fsm}")
        # Returning to IDLE means the last response finished — clear stale plan/evidence
        if new_fsm == "IDLE":
            st.session_state.plan = []
            st.session_state.step = {}
            st.session_state.evidence = None
            st.session_state.scenario = ""

    elif topic == "sentinel/plan":
        st.session_state.plan = data.get("plan", [])
        st.session_state.scenario = data.get("scenario", "")
        st.session_state.step = {}
        print(f"[Dashboard] plan <- {st.session_state.scenario}: {st.session_state.plan}")
        entry = {
            "time": data.get("timestamp", str(datetime.now())),
            "scenario": data.get("scenario", "unknown"),
            "temp": st.session_state.state.get("temperature_cabin", 0),
            "steps": len(data.get("plan", [])),
        }
        st.session_state.incident_history.append(entry)
        st.session_state.incident_history = st.session_state.incident_history[-50:]
        try:
            with open(LOCAL_LOG_FILE, "w") as f:
                json.dump(st.session_state.incident_history, f, indent=2)
        except Exception as e:
            print(f"[Dashboard] Could not write {LOCAL_LOG_FILE}: {e}")

    elif topic == "sentinel/current_step":
        st.session_state.step = data
        print(f"[Dashboard] step <- {data.get('step')}/{data.get('total')} {data.get('status')}")

    elif topic == "sentinel/evidence":
        b64 = data.get("image_base64")
        st.session_state.evidence = b64
        if b64:
            # Save the photo to disk and attach it to the most recent damage
            # incident so the detection history can show a thumbnail later.
            try:
                fpath = os.path.join(
                    EVIDENCE_DIR, f"evi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
                with open(fpath, "wb") as f:
                    f.write(base64.b64decode(b64))
                for entry in reversed(st.session_state.incident_history):
                    sc = str(entry.get("scenario", ""))
                    if ("damage" in sc or "intrusion" in sc) and not entry.get("image"):
                        entry["image"] = fpath
                        break
                with open(LOCAL_LOG_FILE, "w") as fh:
                    json.dump(st.session_state.incident_history, fh, indent=2)
                print(f"[Dashboard] evidence <- saved {fpath} and linked to history")
            except Exception as e:
                print(f"[Dashboard] evidence save failed (non-fatal): {e}")
        else:
            print("[Dashboard] evidence <- (no image)")

    elif topic == "sentinel/alert":
        st.session_state.alerts.insert(0, data)
        st.session_state.alerts = st.session_state.alerts[:20]
        print(f"[Dashboard] alert <- {data.get('event')}")

# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════
def last_seen() -> str:
    if not st.session_state.last_update:
        return "waiting for data…"
    delta = (datetime.now() - st.session_state.last_update).total_seconds()
    return f"{int(delta)}s ago" if delta < 60 else f"{int(delta // 60)}m ago"

def clean_action(action: str) -> str:
    """Turn 'send-damage-alert car1' into 'Send damage alert' for display."""
    return action.replace("-", " ").replace("car1", "").strip().capitalize()

def env_card(label: str, value: str, sub: str, tone: str) -> str:
    """Build one environment card. tone ∈ {ok, info, warn, danger}."""
    return (
        f"<div class='env-card {tone}'>"
        f"<div class='ec-label'>{label}</div>"
        f"<div class='ec-value'>{value}</div>"
        f"<div class='ec-sub'>{sub}</div>"
        f"</div>"
    )

# FSM stepper metadata: order, icon, and CSS class per state
FSM_STEPS = [
    ("IDLE",         "🟢", "s-idle"),
    ("TRIGGERED",    "🟡", "s-trig"),
    ("RESPONDING",   "🔴", "s-resp"),
]

def render_fsm_stepper(current: str):
    """Horizontal IDLE → TRIGGERED → RESPONDING strip, with the current state lit."""
    cells = []
    for i, (name, ico, cls) in enumerate(FSM_STEPS):
        active = "active" if name == current else ""
        cells.append(
            f"<div class='fsm-step {active} {cls}'>"
            f"<span class='fsm-ico'>{ico}</span>{name.replace('_', ' ').title()}</div>"
        )
        if i < len(FSM_STEPS) - 1:
            cells.append("<div class='fsm-arrow'>→</div>")
    st.markdown(f"<div class='fsm-row'>{''.join(cells)}</div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# Read current snapshot
# ══════════════════════════════════════════════════════════════
state    = st.session_state.state
scenario = st.session_state.scenario
fsm      = st.session_state.fsm

damage   = bool(state.get("damage_signal"))
too_hot  = bool(state.get("cabin_too_hot"))
uv_high  = bool(state.get("cabin_uv_high"))
occupant = bool(state.get("occupant_detected"))
alert_active = damage or too_hot or uv_high

# ══════════════════════════════════════════════════════════════
# SIDEBAR — live status summary + the one operator control (Disarm)
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🚗 Sentinel Car")
    st.caption(f"Broker: {MQTT_HOST}")
    st.caption(f"Last update: {last_seen()}")
    st.divider()

    st.markdown("**System state**")
    for name, ico, _ in FSM_STEPS:
        is_now = (name == fsm)
        style = "font-weight:700; opacity:1;" if is_now else "opacity:0.35;"
        st.markdown(
            f"<div style='{style} font-size:14px; padding:2px 0;'>"
            f"{ico} {name.replace('_', ' ').title()}</div>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("**Environment**")
    st.markdown(f"- Cover / damage: {'🔴 Detected' if damage else '🟢 Secure'}")
    st.markdown(f"- Occupant (PIR): {'🔵 Inside' if occupant else '⚪ None'}")
    st.markdown(f"- Cabin temp: {'🔴 Hot' if too_hot else '🟢 Normal'}")
    st.markdown(f"- UV level: {'🟠 High' if uv_high else '🟢 Normal'}")

    st.divider()
    if st.button("🔒 Disarm / reset", use_container_width=True):
        mqtt_client.publish("sentinel/command/disarm", json.dumps({"command": "disarm"}))
        st.toast("Disarm signal sent to coordinator")
        print("[Dashboard] Disarm command published")

    if st.button("🔄 Sync sensors", use_container_width=True):
        # Ask the coordinator to re-send state and request fresh sensor readings
        mqtt_client.publish("sentinel/command/poll", json.dumps({"command": "request_state"}))
        st.toast("Sync requested — fetching latest readings")
        print("[Dashboard] Sync/poll command published")

    if st.button("🧹 Clear alert & history logs", use_container_width=True):
        st.session_state.alerts = []
        st.session_state.incident_history = []
        try:
            if os.path.exists(LOCAL_LOG_FILE):
                os.remove(LOCAL_LOG_FILE)
            # Remove saved evidence thumbnails so nothing is orphaned
            for f in os.listdir(EVIDENCE_DIR):
                os.remove(os.path.join(EVIDENCE_DIR, f))
            print("[Dashboard] Cleared alert log, detection history and evidence files")
        except Exception as e:
            print(f"[Dashboard] Clear logs error (non-fatal): {e}")
        st.toast("Logs cleared")

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
st.title("🚗 Sentinel Car Dashboard")

# ── Overall status banner ──────────────────────────────────────
# Stays RED/YELLOW for the whole duration of an alert (while any alarm flag is
# set OR the system is actively triggered/responding). Only turns GREEN once the
# system is back at IDLE with every condition clear.
in_alert = alert_active or fsm in ("TRIGGERED", "RESPONDING")

if not in_alert:
    st.success("🟢 **All systems normal** — vehicle secure, environment safe.")
elif damage or "damage" in scenario:
    st.error("🚨 **Damage detected** — alarm active. Press **Disarm / reset** to stand down.")
elif too_hot or "heatstroke" in scenario:
    st.warning("🌡️ **Heatstroke risk** — occupant inside, cooling relay engaged until cabin cools.")
elif uv_high or "uv" in scenario:
    st.warning("☀️ **High UV exposure** — occupant inside, warning issued.")
else:
    st.error(f"🚨 **Alert active** — system is {fsm.replace('_', ' ').title()}.")

# ══════════════════════════════════════════════════════════════
# 1) CURRENT EXECUTION STATE
# ══════════════════════════════════════════════════════════════
st.subheader("⚙️ Current execution state")
render_fsm_stepper(fsm)

if not in_alert and not st.session_state.plan:
    st.info("No active response plan — the system is monitoring sensors.")
elif st.session_state.plan:
    # Show the evidence photo alongside the plan only for damage scenarios
    show_evidence = damage or ("damage" in scenario)
    if show_evidence:
        plan_col, ev_col = st.columns([2, 1])
    else:
        plan_col, ev_col = st.container(), None

    with plan_col:
        label = {
            "damage_or_intrusion": "🚨 Damage response",
            "heatstroke_risk":     "🌡️ Heatstroke response",
            "uv_risk":             "☀️ UV response",
        }.get(scenario, "Response")
        st.markdown(f"**{label} — plan progress**")

        current_i = st.session_state.step.get("step", 0)
        status    = st.session_state.step.get("status", "")

        for i, action in enumerate(st.session_state.plan, 1):
            display = clean_action(action)
            done = i < current_i or (i == current_i and status == "complete")
            running = (i == current_i and status == "executing")
            if done:
                st.success(f"✅ Step {i}: {display}")
            elif running:
                st.info(f"⚙️ Step {i}: {display} — running now")
            else:
                st.write(f"⏳ Step {i}: {display}")

        if status == "complete":
            # The plan has run but the response stays LATCHED (actuators on).
            if "heatstroke" in scenario:
                st.warning("🌡️ Cooling relay engaged & alert sent — holding until the cabin cools down.")
            elif "uv" in scenario:
                st.warning("☀️ UV warning sent — holding until UV drops.")
            else:
                st.error("🔔 Alarm active — evidence captured & alert sent. "
                         "Press **Disarm / reset** to silence.")

    if show_evidence and ev_col is not None:
        with ev_col:
            st.markdown("**📸 Evidence**")
            b64 = st.session_state.evidence
            if b64:
                try:
                    st.image(base64.b64decode(b64), use_container_width=True)
                except Exception:
                    st.warning("Could not decode evidence image")
            else:
                st.markdown(
                    "<div style='border:1px dashed #888; border-radius:10px; padding:2rem; "
                    "text-align:center; color:gray;'>📷<br>Waiting for capture…</div>",
                    unsafe_allow_html=True,
                )
else:
    st.info("Threat detected — generating AI response plan…")

st.divider()

# ══════════════════════════════════════════════════════════════
# 2) CURRENT ENVIRONMENT STATE
# ══════════════════════════════════════════════════════════════
st.subheader("📊 Current environment")

temp = state.get("temperature_cabin")
uv   = state.get("uv_index")

# Cover / damage (Cover_status sensor)
c_damage = env_card(
    "Cover / Damage",
    "Damage" if damage else "Secure",
    "Impact on cover sensor" if damage else "No impact detected",
    "danger" if damage else "ok",
)
# Occupant (PIR motion) — motion means someone is inside
c_occ = env_card(
    "Occupant (PIR)",
    "Inside" if occupant else "None",
    "Motion detected in cabin" if occupant else "No motion",
    "info" if occupant else "ok",
)
# Cabin temperature
temp_txt = f"{temp}°C" if temp is not None else "Syncing…"
c_temp = env_card(
    "Cabin temperature",
    temp_txt,
    f"Heatstroke risk (≥ {TEMP_HEATSTROKE_C}°C)" if too_hot
    else f"Normal (< {TEMP_HEATSTROKE_C}°C)" if temp is not None
    else "Waiting for sensor report",
    "danger" if too_hot else "ok",
)
# UV
uv_val = "High" if uv_high else (f"{uv}" if uv is not None else "Normal")
c_uv = env_card(
    "UV level",
    uv_val,
    f"High exposure (index ≥ {UV_HIGH})" if uv_high else f"Safe (index < {UV_HIGH})",
    "warn" if uv_high else "ok",
)

cols = st.columns(4)
for col, html in zip(cols, (c_damage, c_occ, c_temp, c_uv)):
    col.markdown(html, unsafe_allow_html=True)

st.divider()

# ══════════════════════════════════════════════════════════════
# Alert log + detection history
# ══════════════════════════════════════════════════════════════
col_alerts, col_history = st.columns(2)

with col_alerts:
    st.markdown("#### 🚨 Alert log")
    if st.session_state.alerts:
        for a in st.session_state.alerts[:8]:
            evt = a.get("event", "unknown").replace("_", " ").title()
            ts  = str(a.get("timestamp", ""))[:19]
            sev = a.get("severity", "MEDIUM")
            icon = "🔴" if sev == "HIGH" else "🟡"
            st.markdown(
                f"{icon} **{evt}** &nbsp;·&nbsp; "
                f"<span style='color:gray;font-size:12px;'>{ts}</span>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No alerts this session")

with col_history:
    st.markdown("#### 📋 Detection history")
    history = st.session_state.incident_history
    if history:
        for entry in reversed(history[-6:]):
            sc    = str(entry.get("scenario", "unknown"))
            label = sc.replace("_", " ").title()
            ts    = str(entry.get("time", ""))[:19]
            tmp   = entry.get("temp", 0)
            steps = entry.get("steps", 0)
            icon  = ("🚨" if "intrusion" in sc or "damage" in sc
                     else "🌡️" if "heatstroke" in sc
                     else "☀️" if "uv" in sc else "•")
            st.markdown(
                f"{icon} **{label}** &nbsp;·&nbsp; "
                f"<span style='color:gray;font-size:12px;'>{ts} · {tmp}°C · {steps}-step plan</span>",
                unsafe_allow_html=True,
            )
            # Note (no thumbnail) that a photo was saved for this damage incident
            if entry.get("image"):
                st.caption("📷 Evidence image saved")
        try:
            df = pd.DataFrame(history)
            counts = df["scenario"].value_counts()
            st.divider()
            m1, m2, m3 = st.columns(3)
            m1.metric("Damage events", int(counts.get("damage_or_intrusion", 0)))
            m2.metric("Heatstroke", int(counts.get("heatstroke_risk", 0)))
            m3.metric("UV alerts", int(counts.get("uv_risk", 0)))
        except Exception as e:
            print(f"[Dashboard] History summary error (non-fatal): {e}")
    else:
        st.caption("No incidents recorded yet")

# ══════════════════════════════════════════════════════════════
# Auto-refresh — MUST be the very last statement in the script.
# Nothing below this line; nothing above may call st.rerun().
# ══════════════════════════════════════════════════════════════
time.sleep(3)
st.rerun()
