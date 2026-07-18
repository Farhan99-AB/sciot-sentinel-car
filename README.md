# Sentinel Car — Smart Parking Damage & Heatstroke Detection (IoT)

An autonomous IoT safety system for a parked vehicle. A single Z-Wave sensor kit
watches the car; a Raspberry Pi runs the "brain" that senses conditions, **plans a
response with an AI planner**, drives the physical actuators (buzzer, cooling relay,
camera, SMS), and streams everything to a live web dashboard.

It solves two problems:

1. **Heatstroke prevention** — detects a dangerous cabin temperature *while an
   occupant is inside* and engages cooling + sends an alert.
2. **Damage / intrusion detection** — detects a physical impact/tamper on the car,
   sounds an alarm, captures a photo as evidence, and sends an alert.

---

## 1. How it works (the pipeline)

```
  ┌──────────────┐   Z-Wave    ┌───────────────┐   MQTT    ┌────────────────────┐
  │ Aeotec Multi │ ──────────► │  zwave-js-ui  │ ────────► │  main_coordinator  │
  │  Sensor 6    │  (radio)    │  (MQTT bridge)│  zwave/#  │   (the "brain")    │
  └──────────────┘             └───────────────┘           └─────────┬──────────┘
                                                                     │
                          ┌──────────────────────────────────────────┼───────────────┐
                          │                     │                     │               │
                     generate PDDL          run planner          execute actions   publish
                   (pddl_generator)       (planner_runner)     (actuator_controller)  sentinel/*
                          │                     │                     │               │
                          ▼                     ▼                     ▼               ▼
                   problem_sentinel.pddl   pyperplan → plan   buzzer / relay /   ┌─────────────┐
                   + domain_sentinel.pddl                     camera / SMS       │  dashboard  │
                                                                                 │ (Streamlit) │
                                                                                 └─────────────┘
```

**In plain words:** the sensor reports readings → the Pi decides if there's a threat
→ if so it asks an AI planner for the correct sequence of steps → it performs those
steps on real hardware → and it publishes the whole story (sensor state, system
state, plan progress, evidence, alerts) over MQTT so the dashboard can show it live.

---

## 2. Why an AI planner (PDDL)?

Instead of hard-coding `if damage: sound_alarm(); take_photo(); send_sms()`, the
system describes the **world** (facts) and the **available actions** (with
preconditions and effects), and lets a planner compute the correct ordered plan to
reach a goal. This is the academically interesting part:

- It separates *what is true* from *what to do*, so new scenarios only need new
  facts/goals, not new procedural code.
- It guarantees ordering constraints are respected (e.g. you cannot
  `capture-damage-evidence` before `activate-damage-alarm` because the planner's
  preconditions forbid it).

We use **STRIPS** planning via **pyperplan**.

---

## 3. Hardware

| Component | Role | Relay port (configurable) |
|---|---|---|
| Aeotec MultiSensor 6 (Z-Wave, node name `car`) | Motion (PIR), temperature, UV, tamper/cover | via Z-Wave USB stick |
| Raspberry Pi | Runs coordinator + zwave-js-ui + MQTT broker | — |
| **Seeed Relay Board v1.0 — buzzer channel** | Damage alarm | port 2 (`SENTINEL_RELAY_BUZZER`) |
| **Seeed Relay Board v1.0 — cooling channel** | Cooling / fan (heatstroke) | port 1 (`SENTINEL_RELAY_COOLING`) |
| **Seeed Relay Board v1.0 — windows channel** | Window-down motor (vent hot cabin) | port 3 (`SENTINEL_RELAY_WINDOWS`) |
| IP webcam / USB / Pi camera | Evidence photo | network / USB / CSI |

All three actuators are channels on the [**Seeed Studio Relay Board v1.0 for
Raspberry Pi**](https://paradisetronic.com/products/seeed-studio-relay-board-v1-0-raspberry-pi).
This board is **I2C-controlled** (not plain GPIO): all four relays share one 8-bit
data register (`0x06`) at I2C address `0x20`, where a *cleared* bit turns a relay
**on** and a *set* bit turns it **off**. The driver in `actuator_controller.py`
keeps a shadow of that register and does a read-modify-write per change (logic
adapted from [johnwargo/raspberry-pi-relay-controller-seeed](https://github.com/johnwargo/raspberry-pi-relay-controller-seeed)).
Enable I2C first (`sudo raspi-config` → Interface → I2C, or `dtparam=i2c_arm=on`),
install `python3-smbus` (or `pip3 install smbus2`), and confirm the board shows at
`0x20` via `i2cdetect -y 1`. Map each function to a relay port (1-4) with the env
vars above; override the bus or address with `SENTINEL_RELAY_BUS` / `SENTINEL_RELAY_ADDR`.

> **Verify the board on its own first.** The driver lives in `seeed_relay.py`; run
> the standalone tester to prove the relays click/light before touching the rest:
> ```
> python3 relay_test.py            # guided test of all 4 relays (LEDs + clicks)
> python3 relay_test.py --scan     # just list I2C addresses (like i2cdetect)
> python3 relay_test.py --channel cooling   # cycle only the 'cooling' relay
> ```
> If it reports "NOT detected" it prints the exact fix (I2C off, wrong address,
> missing `smbus`). The main app imports the **same** `seeed_relay.SeeedRelay`, so
> once the tester works, the pipeline works. Set `SENTINEL_RELAY_DEBUG=1` to see
> every I2C write from the main app too.

> **No buzzer? → Bluetooth backup.** If the buzzer relay isn't wired up, the
> damage alarm falls back to playing a looping alarm tone through the Pi's
> **default audio sink**. Pair a Bluetooth speaker (or phone) as the default
> output and the "buzzer" comes out of it. Point `SENTINEL_BT_SOUND` at a `.wav`.

> **Single sensor kit.** There is only ONE Aeotec sensor (the `car` node). It
> provides *all four* signals. There is no separate "cabin" sensor.

---

## 4. The sensor → logic mapping (core design decision)

Each physical signal drives exactly one responsibility. This separation is
deliberate and was the main correctness requirement:

| Aeotec signal (Z-Wave) | MQTT topic suffix | Drives | Meaning |
|---|---|---|---|
| **Cover / tamper** | `Home_Security/Cover_status` | `damage_signal` | Physical impact/tamper → **damage only** |
| **Motion (PIR)** | `Home_Security/Motion_sensor_status` | `occupant_detected` | Motion → **occupant inside only** |
| **Air temperature** | `sensor_multilevel/Air_temperature` | `cabin_too_hot` | Heatstroke risk (needs occupant present) |
| **Ultraviolet** | `sensor_multilevel/Ultraviolet` | `cabin_uv_high` | High UV risk (needs occupant present) |

**Trigger rules:**
- Damage fires on the **cover sensor alone**.
- Heatstroke (full response — cooling + windows down) fires when **temperature is
  high AND an occupant is present**.
- A **hot cabin with NO occupant** now fires an **alert-only** plan (high cabin
  temperature warning). Previously this case had no goal to satisfy and left the
  planner spinning on "generating a plan"; the domain now has an explicit
  `send-cabin-heat-alert` action for it.
- **Escalation:** if the temperature report happens to arrive *before* the occupant
  is detected, the alert-only plan runs first; the moment the occupant appears the
  coordinator escalates (re-plans, bypassing the cooldown) to the full cooling +
  windows response. So the order sensor reports arrive in can't strand an occupant
  with just an alert.
- High-UV fires only when **UV is high AND an occupant is present**.

---

## 5. System states (the FSM) and "latching"

The coordinator is a small finite-state machine:

```
   IDLE  ──(threat detected)──►  TRIGGERED  ──(plan runs)──►  RESPONDING
    ▲                                                              │
    └──────────── (disarm, or condition clears) ◄─────────────────┘
```

- **IDLE** — everything normal, just monitoring.
- **TRIGGERED** — a threat was just detected (shown briefly).
- **RESPONDING** — the plan has executed and the actuators are **latched ON**.

**Latching** is important: when damage is detected, the buzzer stays on and the
system *stays* in RESPONDING until the user presses **Disarm** (a physical impact
has no natural "all clear"). For heatstroke, the cooling relay stays on until the
cabin actually **cools below the threshold**, at which point the system stands down
by itself. This is why the alarm doesn't just blink and vanish.

---

## 6. File-by-file explanation

### `main_coordinator.py` — the brain
The central program that runs on the Pi. It:
- Subscribes to all `zwave/#` sensor topics and `sentinel/command/#` control topics.
- Keeps a single `sensor_state` dictionary (the one source of truth).
- Runs the FSM (`transition()`), decides when a threat needs a response
  (`trigger_planning()`), and latches/clears the response.
- Handles **Disarm/reset** (`reset_to_idle()` — turns actuators off, clears alarm
  flags, keeps the last measurements, and requests a fresh reading).
- **Key safeguard:** it only reacts to a whitelist of exact sensor topics
  (`HANDLED_TOPICS`). *Why:* an earlier version filtered topics by the substring
  `"status"`, which accidentally matched both `Cover_status` and
  `Motion_sensor_status` and silently dropped the two most important sensors.

### `sensor_config.py` — the settings
All topics, trigger values, and safety thresholds in one place
(`TEMP_HEATSTROKE_C`, `UV_HIGH`, `MOTION_ACTIVE`, `TAMPER_ACTIVE`, MQTT host/port,
and the optional zwave-js-ui refresh settings). Editing behavior means editing here,
not the logic files.

### `pddl_generator.py` — writes the problem
Turns the current `sensor_state` into a PDDL **problem file**
(`problem_sentinel.pddl`): which facts are true right now and which goal to reach
(`vehicle-secure`, `occupant-safe`, or `cabin-secure` for an unattended hot cabin).
It only writes the facts/goal — it does **not** hand-write the plan; the planner
derives that.

### `domain_sentinel.pddl` — the rules of the world
The PDDL **domain**: every possible action, its preconditions, and effects
(e.g. `activate-damage-alarm` requires `damage-signal`; `capture-damage-evidence`
requires the alarm to already be active). This is the "physics" the planner reasons
over. Split into clean STRIPS actions so a simple planner can solve it.

### `planner_runner.py` — runs the planner
Calls **pyperplan** on the domain+problem, parses the resulting plan into an ordered
list of action names, and returns it. Deletes the stale `.soln` file first so a
fresh plan is always generated, and prints planner errors instead of hiding them.

### `actuator_controller.py` — does the physical actions
Executes each planned action on the **Seeed relay shield**:
- `activate-damage-alarm` → buzzer relay ON (latched); **Bluetooth speaker backup**
  if no buzzer relay is present.
- `capture-damage-evidence` → take a photo, base64-encode it, publish on
  `sentinel/evidence`.
- `send-damage-alert` / `send-uv-warning` / `send-cabin-heat-alert` → publish a
  `sentinel/alert` **and** send an SMS/email notification.
- `engage-cooling` → cooling relay ON (latched) + notify.
- `roll-down-windows` → windows relay ON to drive the window-down motor and vent
  the cabin (part of the occupant heatstroke plan).
- `all_actuators_off()` → all relays OFF + stops the Bluetooth tone; used on
  disarm and when an alarm clears.
- Notifications are pluggable: **console / email-to-SMS / Twilio** (see §10).
- Falls back to simulation prints automatically if no GPIO is present, so it runs
  on a laptop too.

### `camera_capture.py` — the evidence camera
A source-agnostic photo grabber. One line (`CAMERA_SOURCE`) switches between an IP
Webcam URL, a USB webcam (OpenCV), the Pi Camera (picamera2), or `libcamera`. It
tries the chosen source first, then falls back through the others, and verifies the
saved file isn't empty.

### `incident_logger.py` — the audit log
Appends every incident (scenario, temperature, occupant, plan) to
`incidents_log.json` on the Pi, capped at the last 100, so there's a permanent
record independent of the dashboard.

### `dashboard.py` — the live UI (Streamlit)
The operator screen (runs on your laptop, connects to the Pi's MQTT over Tailscale).
It is **display + control only** — it makes no safety decisions. It shows:
- **Current execution state:** the FSM stepper (IDLE → TRIGGERED → RESPONDING) and
  live plan progress with evidence.
- **Current environment:** four cards — Cover/Damage, Occupant (PIR), Cabin
  temperature, UV — colour-coded and always visible.
- A status **banner** that stays red/yellow for the whole alert and only turns green
  when truly safe.
- **Alert log** and **detection history**.
- Controls: **Disarm/reset**, **Sync sensors**, **Clear logs**. (No simulate
  buttons — you inject test data separately, see §9.)

### `simulate_sensors.py` — hardware-free testing
Publishes fake Z-Wave sensor messages to the broker so you can test the entire
pipeline without touching the car. Scenarios: `damage`, `heatstroke`, `uv`, `clear`,
`disarm`.

### `test_sms.py` — prove the SMS path
A self-contained script (no GPIO/camera/MQTT) to verify the notification pipeline on
any machine. See §10.

---

## 7. MQTT topic reference

**Coordinator → dashboard (status):**

| Topic | Payload | Meaning |
|---|---|---|
| `sentinel/state` | full `sensor_state` | current environment |
| `sentinel/fsm_state` | `{"state": ...}` | current execution state |
| `sentinel/plan` | `{plan, scenario, timestamp}` | the AI plan just generated |
| `sentinel/current_step` | `{step, total, action, status}` | live plan progress |
| `sentinel/evidence` | `{image_base64, ...}` | captured photo |
| `sentinel/alert` | `{event, severity, timestamp}` | an alert was raised |

**Dashboard → coordinator (control):**

| Topic | Meaning |
|---|---|
| `sentinel/command/disarm` | force IDLE, actuators off, reset flags |
| `sentinel/command/poll` | re-send state + request a fresh sensor reading |

**Sensors → coordinator:** `zwave/car/...` (see §4).

---

## 8. Configuration reference (`sensor_config.py`)

| Setting | Default | Meaning |
|---|---|---|
| `TEMP_HEATSTROKE_C` | 35 | °C at/above which the cabin is "too hot" |
| `UV_HIGH` | 6 | UV index at/above which UV is "high" |
| `MOTION_ACTIVE` | 8 | PIR value that means "motion" |
| `TAMPER_ACTIVE` | 3 | Cover value that means "tamper/impact" |
| `MQTT_HOST` / `MQTT_PORT` | 127.0.0.1 : 1883 | broker (Pi-local for coordinator) |
| `ZWAVE_GATEWAY_NAME`, `CAR_NODE_ID` | `None` | optional: enables active value-refresh on Sync/Disarm |

> The dashboard has its own `MQTT_HOST = 100.74.16.98` (the Pi's Tailscale IP)
> because it runs on a different machine.

---

## 9. Running it

**On the Raspberry Pi** (broker + zwave-js-ui already running):
```bash
python3 main_coordinator.py      # start the brain
```

**On your laptop:**
```bash
streamlit run dashboard.py       # open the live dashboard
```

**Testing without the car** (run on the Pi, in another terminal):
```bash
python3 simulate_sensors.py --scenario damage      # impact → alarm + photo, latches
python3 simulate_sensors.py --scenario heatstroke  # occupant + heat → cooling relay
python3 simulate_sensors.py --scenario uv          # occupant + high UV → warning
python3 simulate_sensors.py --scenario clear       # temp/UV back to normal
python3 simulate_sensors.py --scenario disarm      # force reset to IDLE
```

**Demo flow to show a professor:**
1. `--scenario damage` → dashboard shows TRIGGERED → RESPONDING, banner red, buzzer
   latched, photo captured. It **stays** in RESPONDING.
2. Press **Disarm / reset** → buzzer off, banner green, state reset.
3. `--scenario heatstroke` → cooling relay on, banner yellow, stays RESPONDING.
4. `--scenario clear` (sends 24 °C) → relay off, auto-returns to IDLE.

---

## 10. SMS alerts without hardware

The alarm needs a buzzer, but **SMS needs no hardware** — just an account. The
notification backend is selected with the `SENTINEL_NOTIFY` environment variable and
all secrets come from env vars (nothing is committed to git).

### Option A — Email-to-SMS gateway (free, recommended)
Gmail can send an email that a mobile carrier delivers **as a real text message**.

1. Gmail → enable 2-Step Verification → create an **App Password** (16 chars).
2. Set environment variables:
   ```bash
   export SENTINEL_NOTIFY=email
   export SENTINEL_SMTP_USER="youraddress@gmail.com"
   export SENTINEL_SMTP_PASS="the16charapppassword"
   export SENTINEL_ALERT_TO="5551234567@txt.att.net"   # carrier SMS gateway
   ```
   Common gateways: AT&T `@txt.att.net`, T-Mobile `@tmomail.net`,
   Verizon `@vtext.com`. (If your carrier has no gateway, just send to your own
   inbox — `SENTINEL_ALERT_TO="youraddress@gmail.com"` — to prove delivery.)
3. Verify it independently:
   ```bash
   python test_sms.py
   ```
   You should receive the test message. From then on, every real alert is delivered
   automatically.

### Option B — Twilio (real SMS via API, free trial)
1. Create a free Twilio trial, get a trial number, verify your phone.
2. `pip install twilio`, then:
   ```bash
   export SENTINEL_NOTIFY=twilio
   export TWILIO_ACCOUNT_SID=... TWILIO_AUTH_TOKEN=...
   export TWILIO_FROM=+1xxxxxxxxxx   TWILIO_TO=+1yyyyyyyyyy
   python test_sms.py
   ```

### Option C — Console (default)
No account. The alert is printed to the coordinator console and still appears in the
dashboard alert log — enough to demonstrate the logic even with zero setup.

> On Windows PowerShell, set variables with `$env:SENTINEL_NOTIFY="email"` instead of
> `export`.

---

## 11. Design notes / lessons

- **Topic whitelist, not blacklist.** Filtering incoming topics by substring is
  fragile — `"status"` matched `Cover_status`/`Motion_sensor_status`. The fix was an
  explicit `HANDLED_TOPICS` set.
- **Publish on value change, not only on flag change.** Temperature must be
  republished whenever the number moves, or the dashboard shows a stale reading.
- **Latching vs. momentary.** Safety alarms should persist (latch) until resolved,
  not flash for a second. Damage latches until disarm; heat latches until cooled.
- **Separation of concerns.** The dashboard never decides anything — all logic lives
  in the coordinator, so the UI can crash/restart without affecting safety.
- **Secrets via environment variables.** Credentials are never written into source.
