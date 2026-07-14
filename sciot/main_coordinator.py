# main_coordinator.py — v11
#
# SENSOR MAPPING (single Aeon MultiSensor 6, node name "car"):
#   Cover_status (tamper/impact)   -> DAMAGE detection ONLY
#   Motion_sensor_status (PIR)     -> OCCUPANT detection ONLY
#   Air_temperature                -> Heatstroke risk (needs occupant present)
#   Ultraviolet                    -> High UV risk    (needs occupant present)
#
# Pipeline: sensor -> MQTT -> this file -> PDDL planner -> actuators

import paho.mqtt.client as mqtt
import json
import time
from datetime import datetime
from sensor_config import *
from pddl_generator import generate_problem
from planner_runner import run_planner
from actuator_controller import execute_action, trigger_failsafe_alarm, all_actuators_off
from incident_logger import log_incident

# ── Finite State Machine ─────────────────────────────────────
# IDLE -> TRIGGERED -> RESPONDING -> back to IDLE
system_fsm = {"state": "IDLE", "entered_at": 0}


def transition(new_state: str, mqtt_client):
    """Move the FSM to a new state and tell the dashboard about it."""
    if system_fsm["state"] == new_state:
        return
    print(f"[FSM] {system_fsm['state']} -> {new_state}")
    system_fsm["state"] = new_state
    system_fsm["entered_at"] = time.time()
    mqtt_client.publish("sentinel/fsm_state", json.dumps({"state": new_state}))


# ── Live sensor state (single source of truth) ───────────────
sensor_state = {
    "damage_signal":     False,   # set ONLY by Cover_status
    "occupant_detected": False,   # set ONLY by PIR motion
    "cabin_too_hot":     False,   # set by Air_temperature
    "cabin_uv_high":     False,   # set by Ultraviolet
    "temperature_cabin": None,
    "uv_index":          None,
}

# The exact sensor topics this coordinator reacts to. Anything not in this set
# (battery, node status, humidity, illuminance, wake-up, config, …) is ignored.
HANDLED_TOPICS = {
    TOPIC_CAR_TAMPER,   # Cover_status  -> damage
    TOPIC_CAR_MOTION,   # PIR           -> occupant
    TOPIC_CAR_TEMP,     # Air_temperature
    TOPIC_CAR_UV,       # Ultraviolet
    TOPIC_BINARY_ANY,   # informational only (logged, never drives logic)
}

last_plan_time = 0
PLAN_COOLDOWN  = 15   # seconds between planning cycles, prevents alert spam


def any_alarm_active() -> bool:
    """True while any latching alarm condition holds. Damage latches until a
    disarm; heat/UV clear on their own once the sensor value normalises."""
    return (sensor_state["damage_signal"]
            or sensor_state["cabin_too_hot"]
            or sensor_state["cabin_uv_high"])


def request_sensor_refresh(client):
    """Ask zwave-js-ui to re-read the sensor's values (optional — only if the
    gateway name + node id are configured in sensor_config)."""
    if not ZWAVE_GATEWAY_NAME or CAR_NODE_ID is None:
        print("[Coordinator] Reset done — awaiting next periodic sensor report")
        return
    topic = f"zwave/_CLIENTS/ZWAVE_GATEWAY-{ZWAVE_GATEWAY_NAME}/api/refreshValues/set"
    client.publish(topic, json.dumps({"args": [CAR_NODE_ID]}))
    print(f"[Coordinator] Requested fresh readings for node {CAR_NODE_ID}")


def reset_to_idle(client, repoll: bool = True):
    """Force everything back to a clean IDLE: actuators off, sensor state wiped,
    FSM to IDLE, dashboard notified, and (optionally) a fresh-reading request."""
    all_actuators_off()
    cooling_watch["active"] = False
    # Clear the alarm / derived flags, but KEEP the last raw measurements
    # (temperature_cabin, uv_index) so the dashboard doesn't go blank. Fresh
    # values arrive on the next sensor report, or immediately via a sync/refresh.
    sensor_state.update({
        "damage_signal":     False,
        "occupant_detected": False,
        "cabin_too_hot":     False,
        "cabin_uv_high":     False,
    })
    transition("IDLE", client)
    client.publish("sentinel/state", json.dumps(sensor_state), retain=True)
    if repoll:
        request_sensor_refresh(client)

# ── OPTIONAL: cooling failsafe watchdog ──────────────────────
# If the relay/AC is engaged but the cabin hasn't cooled down within
# COOLING_FAILSAFE_SECONDS, escalate to the alarm as a backup safety net.
cooling_watch = {"active": False, "engaged_at": 0}
COOLING_FAILSAFE_SECONDS = 30


def trigger_planning(client, force: bool = False):
    """Runs one sense -> plan -> act cycle. Respects the cooldown window unless
    `force` is set (used when escalating an already-latched response)."""
    global last_plan_time
    if not force and (time.time() - last_plan_time) < PLAN_COOLDOWN:
        print("[Coordinator] Cooldown active, skipping re-plan")
        return
    last_plan_time = time.time()

    # Show TRIGGERED first (the detection moment), briefly, so the dashboard can
    # display it, then move into RESPONDING for the actual actuator plan.
    transition("TRIGGERED", client)
    time.sleep(1.5)
    transition("RESPONDING", client)

    generate_problem(
        damage_signal=sensor_state["damage_signal"],
        motion_outside=False,  # unused predicate in current domain, kept for compatibility
        occupant_detected=sensor_state["occupant_detected"],
        cabin_too_hot=sensor_state["cabin_too_hot"],
        cabin_uv_high=sensor_state["cabin_uv_high"],
    )

    plan = run_planner()
    if not plan:
        print("[Coordinator] No plan produced — standing down to IDLE")
        all_actuators_off()
        transition("IDLE", client)
        return

    if sensor_state["damage_signal"]:
        scenario = "damage_or_intrusion"
    elif sensor_state["cabin_too_hot"]:
        # Distinguish an at-risk occupant from an unattended hot cabin (alert-only).
        scenario = "heatstroke_risk" if sensor_state["occupant_detected"] else "high_cabin_temp_alert"
    elif sensor_state["cabin_uv_high"]:
        scenario = "uv_risk"
    else:
        scenario = "general_alert"

    print(f"[Coordinator] Scenario: {scenario} | Plan: {plan}")
    log_incident(scenario, sensor_state, plan)

    # Tell the dashboard the full plan up front
    client.publish("sentinel/plan", json.dumps({
        "plan": plan,
        "scenario": scenario,
        "timestamp": str(datetime.now())
    }))

    # Execute each step, publishing progress as we go so the dashboard
    # can show which step is currently running
    for i, action in enumerate(plan, 1):
        client.publish("sentinel/current_step", json.dumps({
            "step": i, "total": len(plan), "action": action,
            "scenario": scenario, "status": "executing"
        }))
        execute_action(action, client, sensor_state.copy())

        if "engage-cooling" in action:
            cooling_watch["active"] = True
            cooling_watch["engaged_at"] = time.time()
            print(f"[Coordinator] Cooling engaged — watching for {COOLING_FAILSAFE_SECONDS}s")

        time.sleep(1.5)   # small pause so each step is visible on the dashboard

    client.publish("sentinel/current_step", json.dumps({
        "step": len(plan), "total": len(plan), "action": plan[-1],
        "scenario": scenario, "status": "complete"
    }))

    # LATCH: the plan has run and the actuators (buzzer / relay) are engaged.
    # We deliberately STAY in RESPONDING and keep the alarm flags set. The system
    # only stands down when the operator disarms, or — for heat/UV — when the
    # sensor value itself normalises (handled at the end of on_message).
    client.publish("sentinel/state", json.dumps(sensor_state), retain=True)
    print("[Coordinator] Response latched in RESPONDING — awaiting disarm or auto-clear")


def check_cooling_failsafe(client):
    """OPTIONAL: escalates to the alarm if cooling isn't working fast enough."""
    if not cooling_watch["active"]:
        return
    if not sensor_state["cabin_too_hot"]:
        # Temperature recovered on its own — cancel the watchdog, no escalation needed
        cooling_watch["active"] = False
        return
    if (time.time() - cooling_watch["engaged_at"]) > COOLING_FAILSAFE_SECONDS:
        print("[Coordinator] Cooling failsafe triggered — temp still high after timeout")
        try:
            trigger_failsafe_alarm(client)
        except Exception as e:
            print(f"[Coordinator] Failsafe alarm error (non-fatal): {e}")
        cooling_watch["active"] = False   # only escalate once per cooling attempt


def on_message(client, userdata, message):
    global sensor_state
    topic = message.topic
    payload_str = message.payload.decode("utf-8")

    # ── System commands — always processed first, bypass everything else ──
    if topic == TOPIC_DISARM:
        print("[SYSTEM] Disarm/reset received — actuators off, clearing all state")
        reset_to_idle(client, repoll=True)
        return

    if topic == "sentinel/command/poll":
        print("[SYSTEM] Dashboard requested a state sync")
        client.publish("sentinel/state", json.dumps(sensor_state), retain=True)
        client.publish("sentinel/fsm_state", json.dumps({"state": system_fsm["state"]}))
        request_sensor_refresh(client)   # also ask the device for fresh readings
        return

    # ── Only our four sensor topics matter; ignore everything else ──
    # IMPORTANT: do NOT filter by the substring "status" here. Both of our most
    # important topics — Cover_status (damage) and Motion_sensor_status (PIR) —
    # contain "status", so a broad blacklist silently dropped damage + occupant
    # detection. Whitelisting the exact topics we handle is safe and explicit.
    if topic not in HANDLED_TOPICS:
        return

    try:
        data  = json.loads(payload_str)
        value = data.get("value")
        if value is None:
            return
    except Exception:
        return

    changed = False

    # ── 1. DAMAGE DETECTION — Cover/tamper sensor ONLY ──────────
    if topic == TOPIC_CAR_TAMPER:
        if value == TAMPER_ACTIVE and not sensor_state["damage_signal"]:
            print(f"[DAMAGE] Cover status tripped (value={value}) — physical impact")
            sensor_state["damage_signal"] = True
            transition("TRIGGERED", client)
            changed = True
        else:
            print(f"[DEBUG] Cover status = {value} (no change)")

    # ── 2. OCCUPANT DETECTION — PIR motion sensor ONLY ──────────
    elif topic == TOPIC_CAR_MOTION:
        occupant_now = (value == MOTION_ACTIVE)
        if occupant_now != sensor_state["occupant_detected"]:
            sensor_state["occupant_detected"] = occupant_now
            print(f"[OCCUPANT] {'Detected' if occupant_now else 'Left'} (PIR value={value})")
            changed = True

    # ── 3. TEMPERATURE — heatstroke risk ────────────────────────
    elif topic == TOPIC_CAR_TEMP:
        # Publish on ANY change of the reading, not only when the hot/cold flag
        # flips — otherwise the dashboard never sees the live temperature move.
        if value != sensor_state["temperature_cabin"]:
            changed = True
        sensor_state["temperature_cabin"] = value
        new_hot = (value >= TEMP_HEATSTROKE_C)
        if new_hot != sensor_state["cabin_too_hot"]:
            sensor_state["cabin_too_hot"] = new_hot
            print(f"[TEMP] {value}C - {'HEATSTROKE RISK' if new_hot else 'normalised'}")
            changed = True
        check_cooling_failsafe(client)
        # Only cancel a *pending* heat alert (TRIGGERED) when the cabin cools.
        # Don't interrupt RESPONDING — a plan in progress must finish cleanly.
        if not new_hot and not sensor_state["damage_signal"] and system_fsm["state"] == "TRIGGERED":
            transition("IDLE", client)

    # ── 4. UV — high exposure risk ──────────────────────────────
    elif topic == TOPIC_CAR_UV:
        if value != sensor_state["uv_index"]:
            changed = True
        sensor_state["uv_index"] = value
        new_uv = (value >= UV_HIGH)
        if new_uv != sensor_state["cabin_uv_high"]:
            sensor_state["cabin_uv_high"] = new_uv
            print(f"[UV] Index {value} - {'HIGH' if new_uv else 'normal'}")
            changed = True

    # ── Informational only — logged but never drives logic ──────
    elif topic == TOPIC_BINARY_ANY:
        print(f"[DEBUG] sensor_binary/Any = {value} (informational only)")
        return
    else:
        return   # topic we don't care about (humidity, illuminance, etc.)

    if changed:
        client.publish("sentinel/state", json.dumps(sensor_state), retain=True)
        # Only START a response from a resting state — never re-plan while a
        # response is already latched in RESPONDING.
        if system_fsm["state"] in ("IDLE", "TRIGGERED"):
            needs_plan = (
                sensor_state["damage_signal"] or
                sensor_state["cabin_too_hot"] or   # hot cabin alerts even with no occupant
                (sensor_state["cabin_uv_high"] and sensor_state["occupant_detected"])
            )
            if needs_plan:
                trigger_planning(client)

        # ── ESCALATION ───────────────────────────────────────────
        # A hot cabin can trigger an alert-only response BEFORE the occupant is
        # detected (the temperature report can arrive first). If an occupant then
        # appears while that alert is latched — and cooling isn't already running —
        # upgrade to the full cooling + windows plan. This closes the race that
        # otherwise leaves a trapped occupant with only an alert and no cooling.
        elif system_fsm["state"] == "RESPONDING":
            escalate = (
                sensor_state["cabin_too_hot"]
                and sensor_state["occupant_detected"]
                and not cooling_watch["active"]        # cooling not engaged yet
                and not sensor_state["damage_signal"]  # damage owns the response
            )
            if escalate:
                print("[Coordinator] Occupant appeared during hot-cabin alert — "
                      "escalating to cooling + windows")
                trigger_planning(client, force=True)

    # AUTO-CLEAR: if a latched response's conditions have all resolved on their
    # own (e.g. the cabin cooled down, UV dropped), shut the actuators off and
    # stand down to IDLE. Damage never clears here — it latches until disarm.
    if system_fsm["state"] == "RESPONDING" and not any_alarm_active():
        print("[Coordinator] Alarm conditions cleared — actuators off, back to IDLE")
        all_actuators_off()
        transition("IDLE", client)
        client.publish("sentinel/state", json.dumps(sensor_state), retain=True)


def on_connect(client, userdata, flags, rc, props):
    client.subscribe("zwave/#")
    client.subscribe("sentinel/command/#")
    print("[Coordinator] Armed and listening for sensor + command topics...")


if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "SentinelCoordinator")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_forever()