# simulate_sensors.py — inject test sensor readings AND verify the coordinator reacts
# ─────────────────────────────────────────────────────────────────────────────
# Run this on the Pi to mimic what Z-Wave JS UI would publish, then watch what
# main_coordinator.py does in response. Unlike the old version, this one:
#   • RAMPS the cabin temperature over several messages, so the dashboard's
#     temperature card visibly rises instead of jumping once.
#   • Sends occupant (PIR) motion FIRST so a heat event becomes a full cooling
#     response rather than an alert-only one.
#   • LISTENS on sentinel/* after publishing and prints a verdict: did the
#     coordinator plan? did it drive the relays? — so if "nothing happens" you
#     immediately see whether the coordinator is even reacting.
#
# Usage:
#   python3 simulate_sensors.py --scenario heatstroke   # occupant + rising heat
#   python3 simulate_sensors.py --scenario hot_empty    # rising heat, no occupant
#   python3 simulate_sensors.py --scenario uv
#   python3 simulate_sensors.py --scenario damage
#   python3 simulate_sensors.py --scenario hot_damage  # occupant + heat + break-in
#   python3 simulate_sensors.py --scenario clear
#   python3 simulate_sensors.py --scenario disarm
#
# IMPORTANT: main_coordinator.py must be running and connected to the SAME broker
# (MQTT_HOST in sensor_config.py). If the verdict says "coordinator did NOT
# respond", that mismatch (or the coordinator not running) is your problem.
import json
import time
import argparse
from datetime import datetime

import paho.mqtt.client as mqtt

from sensor_config import (
    MQTT_HOST, MQTT_PORT,
    TOPIC_CAR_MOTION, TOPIC_CAR_TAMPER, TOPIC_CAR_TEMP, TOPIC_CAR_UV,
    TOPIC_DISARM, MOTION_ACTIVE, MOTION_CLEAR, TAMPER_ACTIVE, TAMPER_CLEAR,
    TEMP_HEATSTROKE_C, UV_HIGH,
)

# Temperature ramp that starts safe and crosses the heatstroke threshold, so the
# UI shows a genuine rise. Ends a few degrees above the threshold.
def _heat_ramp():
    start = TEMP_HEATSTROKE_C - 6
    return [round(start + i * 2, 1) for i in range(0, 6)]   # e.g. 29,31,33,35,37,39


def build_messages(scenario):
    motion_on  = (TOPIC_CAR_MOTION, {"value": MOTION_ACTIVE})
    if scenario == "heatstroke":
        msgs = [motion_on]                                   # occupant enters first
        for t in _heat_ramp():
            msgs.append((TOPIC_CAR_TEMP, {"value": t}))
        msgs.append(motion_on)                               # re-assert occupant
        return msgs
    if scenario == "hot_empty":
        return [(TOPIC_CAR_TEMP, {"value": t}) for t in _heat_ramp()]
    if scenario == "uv":
        return [motion_on,
                (TOPIC_CAR_UV, {"value": UV_HIGH - 2}),
                (TOPIC_CAR_UV, {"value": UV_HIGH + 2}),
                motion_on]
    if scenario == "damage":
        return [(TOPIC_CAR_TAMPER, {"value": TAMPER_ACTIVE})]
    if scenario == "hot_damage":
        # Occupant trapped in a heating cabin, THEN a physical impact/break-in on
        # top. The coordinator plans the heat response first, then the fresh damage
        # signal forces a re-plan with both conditions set — one compound plan that
        # both secures the vehicle AND cools/vents for the occupant.
        msgs = [motion_on]                                   # occupant enters first
        for t in _heat_ramp():
            msgs.append((TOPIC_CAR_TEMP, {"value": t}))
        msgs.append(motion_on)                               # re-assert occupant
        msgs.append((TOPIC_CAR_TAMPER, {"value": TAMPER_ACTIVE}))  # impact/break-in
        return msgs
    if scenario == "clear":
        return [(TOPIC_CAR_TEMP, {"value": 24.0}),
                (TOPIC_CAR_UV, {"value": 0}),
                (TOPIC_CAR_MOTION, {"value": MOTION_CLEAR}),
                (TOPIC_CAR_TAMPER, {"value": TAMPER_CLEAR})]
    if scenario == "disarm":
        return [(TOPIC_DISARM, {"command": "disarm"})]
    return []


SCENARIOS = {
    "heatstroke": "Occupant inside + cabin temperature rising past the threshold",
    "hot_empty":  "Cabin temperature rising, NO occupant → alert-only",
    "uv":         "Occupant inside + UV rising past the threshold",
    "damage":     "Physical damage / tamper on the cover sensor",
    "hot_damage":  "Occupant + rising heat AND a break-in → compound secure + cool plan",
    "clear":      "Reset all readings to safe values",
    "disarm":     "Force the system to disarm and return to IDLE",
}

# ── What the coordinator says back ──────────────────────────────
seen = {"fsm": [], "plan": None, "scenario": None, "steps": [],
        "alerts": [], "state_temps": []}


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
    except Exception:
        return
    t = msg.topic
    if t == "sentinel/fsm_state":
        s = data.get("state")
        if s and (not seen["fsm"] or seen["fsm"][-1] != s):
            seen["fsm"].append(s)
            print(f"   [coordinator] FSM → {s}")
    elif t == "sentinel/plan":
        seen["plan"] = data.get("plan")
        seen["scenario"] = data.get("scenario")
        print(f"   [coordinator] PLAN ({data.get('scenario')}): {data.get('plan')}")
    elif t == "sentinel/current_step":
        act = data.get("action")
        if act and (data.get("status") == "executing"):
            seen["steps"].append(act)
            print(f"   [coordinator] step {data.get('step')}/{data.get('total')}: {act}")
    elif t == "sentinel/alert":
        ev = data.get("event")
        seen["alerts"].append(ev)
        print(f"   [coordinator] ALERT: {ev}")
    elif t == "sentinel/state":
        tc = data.get("temperature_cabin")
        if tc is not None:
            seen["state_temps"].append(tc)


def verdict(scenario):
    print("\n" + "═" * 60)
    print("VERDICT")
    print("═" * 60)
    reacted = bool(seen["fsm"] or seen["plan"] or seen["steps"] or seen["alerts"])
    if not reacted:
        print("❌ The coordinator did NOT respond to any of these readings.")
        print("   (If the dashboard still shows an old plan/image, that's a retained/")
        print("    leftover message — this run produced no new response.)")
        print("   Check, in order:")
        print("   1. Is main_coordinator.py actually running?   python3 main_coordinator.py")
        print(f"   2. Same broker? simulate + coordinator both use MQTT_HOST={MQTT_HOST}:{MQTT_PORT}")
        print("      (a Mosquitto broker must be running there).")
        print("   3. Is pyperplan installed IN THIS VENV?   pip install pyperplan")
        print("      (planner_runner runs `python3 -m pyperplan`; if it's missing the")
        print("       plan is empty and nothing actuates.)")
        print("   4. Watch the coordinator's own console while this runs — its prints")
        print("      say exactly where it stops.")
        return
    print("✅ Coordinator reacted.")
    print(f"   FSM path      : {' → '.join(seen['fsm']) or '(none)'}")
    if seen["state_temps"]:
        print(f"   Temp reported : {seen['state_temps'][0]} → {seen['state_temps'][-1]} °C "
              f"(should be visible on the dashboard)")
    print(f"   Plan          : {seen['plan']}")
    print(f"   Steps run     : {seen['steps'] or '(none)'}")
    print(f"   Alerts        : {seen['alerts'] or '(none)'}")

    relay_acts = [a for a in seen["steps"] if "engage-cooling" in a or "roll-down-windows" in a
                  or "activate-damage-alarm" in a]
    if scenario in ("heatstroke",) and not relay_acts:
        print("\n⚠️  Expected cooling/windows relays but none ran. Usually the occupant")
        print("    wasn't registered before the heat crossed the threshold. This build")
        print("    sends motion first AND escalates, so if you still see this, verify")
        print("    the coordinator on the Pi is the updated main_coordinator.py.")
    elif relay_acts:
        print(f"\n🔌 Relay-driving actions executed: {relay_acts}")
        print("   The board LEDs for those channels should be lit now.")


def run(scenario, wait, fresh=True):
    desc = SCENARIOS.get(scenario)
    if not desc:
        print(f"Unknown scenario. Choose: {list(SCENARIOS)}")
        return

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Simulator")
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.subscribe("sentinel/#")
    client.loop_start()

    # Some responses LATCH until disarm — damage in particular stays in RESPONDING
    # after the first trigger. Repeating the scenario without disarming is then
    # (correctly) ignored by the coordinator, which looks like "no response" even
    # though the dashboard still shows the earlier plan/image. Send a disarm first
    # so each run starts from a clean IDLE. Use --no-fresh to see the raw behavior.
    if fresh and scenario not in ("clear", "disarm"):
        client.publish(TOPIC_DISARM, json.dumps({"command": "disarm"}))
        print("[SIM] Sent disarm first for a clean start (use --no-fresh to skip).")
        time.sleep(2.0)

    # Drain any retained sentinel/* messages first so the verdict only reflects
    # this run's fresh responses.
    time.sleep(1.0)
    for k in seen:
        seen[k] = [] if isinstance(seen[k], list) else None

    print(f"\n[SIM] Scenario: {desc}")
    print(f"[SIM] Publishing to {MQTT_HOST}:{MQTT_PORT} — watch coordinator responses below\n")

    for topic, payload in build_messages(scenario):
        payload["time"] = int(datetime.now().timestamp() * 1000)
        payload.setdefault("nodeName", "car")
        client.publish(topic, json.dumps(payload), retain=False)
        short = topic.split("/")[-1]
        print(f"[SIM] → {short}: {payload.get('value', payload.get('command'))}")
        time.sleep(0.8)   # visible gap so the ramp shows on the UI

    print(f"\n[SIM] Waiting {wait}s for the coordinator to finish its plan…")
    time.sleep(wait)

    client.loop_stop()
    client.disconnect()

    if scenario not in ("clear", "disarm"):
        verdict(scenario)
    print("\n[SIM] Done.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True, choices=list(SCENARIOS))
    parser.add_argument("--wait", type=float, default=10.0,
                        help="seconds to listen for the coordinator's response")
    parser.add_argument("--no-fresh", dest="fresh", action="store_false",
                        help="do NOT auto-disarm before triggering (show raw latched behavior)")
    parser.set_defaults(fresh=True)
    args = parser.parse_args()
    run(args.scenario, args.wait, args.fresh)
