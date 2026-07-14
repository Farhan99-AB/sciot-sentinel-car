# actuator_controller.py — v7
#   • Actuators driven via a Seeed Raspberry Pi relay shield (cooling/buzzer/windows)
#   • Bluetooth-speaker fallback for the buzzer when no hardware buzzer is present
#   • Notifications: console / email-to-SMS / Twilio (unchanged)
import os
import sys
import json
import base64
import shutil
import smtplib
import subprocess
from email.message import EmailMessage
from datetime import datetime
from camera_capture import capture_photo

# ══════════════════════════════════════════════════════════════
# NOTIFICATION BACKEND
# ──────────────────────────────────────────────────────────────
# Pick how alerts are delivered. All secrets are read from environment
# variables so nothing sensitive is committed to git.
#
#   "console" : just print the alert (no account needed — default demo mode)
#   "email"   : send via SMTP. If the recipient is a carrier email-to-SMS
#               gateway address, it arrives as a REAL text message — this is
#               the recommended way to prove SMS without any hardware.
#   "twilio"  : send a real SMS through the Twilio API (needs a trial account)
#   "ntfy"    : FREE push notification via ntfy.sh — no account. Just pick a
#               topic name and install the ntfy app on your phone. (easiest)
#   "telegram": FREE push via a Telegram bot — real phone notification, works on
#               any carrier/country. Needs a bot token + your chat id.
#
# Set with:  export SENTINEL_NOTIFY=ntfy   (Linux/Pi)
# ══════════════════════════════════════════════════════════════
NOTIFY_METHOD = os.getenv("SENTINEL_NOTIFY", "console").lower()

# --- Email / email-to-SMS settings (used when NOTIFY_METHOD == "email") ---
# For Gmail: enable 2FA, then create an "App Password" and use it as SMTP_PASS.
# To deliver as an actual SMS, set SENTINEL_ALERT_TO to a carrier gateway, e.g.
#   AT&T:      <10-digit-number>@txt.att.net
#   T-Mobile:  <10-digit-number>@tmomail.net
#   Verizon:   <10-digit-number>@vtext.com
#   (India) Jio/Airtel: use "email" mode to your inbox, or use Twilio for SMS.
SMTP_HOST = os.getenv("SENTINEL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SENTINEL_SMTP_PORT", "587"))
SMTP_USER = os.getenv("SENTINEL_SMTP_USER", "")     # your gmail address
SMTP_PASS = os.getenv("SENTINEL_SMTP_PASS", "")     # 16-char app password
ALERT_TO  = os.getenv("SENTINEL_ALERT_TO",  "")     # inbox OR carrier SMS gateway

# --- Twilio settings (used when NOTIFY_METHOD == "twilio") ---
TWILIO_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM  = os.getenv("TWILIO_FROM", "")         # your Twilio number
TWILIO_TO    = os.getenv("TWILIO_TO", "")           # verified destination number

# --- ntfy.sh settings (used when NOTIFY_METHOD == "ntfy") — FREE, no account ---
# 1) pick a hard-to-guess topic, e.g. "sentinel-car-9f3k"
# 2) install the ntfy app, subscribe to that topic
# 3) export NTFY_TOPIC=sentinel-car-9f3k
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")
NTFY_TOPIC  = os.getenv("NTFY_TOPIC", "")

# --- Telegram settings (used when NOTIFY_METHOD == "telegram") — FREE ---
# 1) message @BotFather → /newbot → copy the token
# 2) message your new bot once, then visit
#    https://api.telegram.org/bot<token>/getUpdates to read your chat id
# 3) export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ══════════════════════════════════════════════════════════════
# ACTUATORS — Seeed Studio Relay Board v1.0 for Raspberry Pi (I2C)
# ──────────────────────────────────────────────────────────────
# The board driver lives in seeed_relay.py (shared with relay_test.py, so the
# exact code you verify with the tester is what runs here). Each function maps to
# a physical relay port (1-4), overridable via env vars:
#   cooling : fan / AC        (heatstroke response)
#   buzzer  : siren / buzzer  (damage alarm; Bluetooth fallback if absent)
#   windows : window motor    (roll the windows down to vent a hot cabin)
from seeed_relay import SeeedRelay

RELAY_CHANNELS = {
    "cooling": int(os.getenv("SENTINEL_RELAY_COOLING", "1")),   # relay port 1
    "buzzer":  int(os.getenv("SENTINEL_RELAY_BUZZER",  "2")),   # relay port 2
    "windows": int(os.getenv("SENTINEL_RELAY_WINDOWS", "3")),   # relay port 3
}

# How the damage buzzer sounds:
#   "relay"     (default) → energise the buzzer relay channel (port 2)
#   "bluetooth"           → play the alarm tone over a paired BT speaker/phone
# Switch at runtime with:  export SENTINEL_BUZZER=bluetooth
BUZZER_BACKEND = os.getenv("SENTINEL_BUZZER", "relay").lower()

# Set SENTINEL_RELAY_DEBUG=1 to see every I2C register write from the main app.
_relay = SeeedRelay(debug=os.getenv("SENTINEL_RELAY_DEBUG", "0") == "1")
RELAY_AVAILABLE = _relay.available
GPIO_AVAILABLE  = RELAY_AVAILABLE   # backwards-compatible alias

if RELAY_AVAILABLE:
    print(f"[Relay] Seeed relay board online, channels={RELAY_CHANNELS}")
else:
    print(f"[Relay] Not available ({_relay.last_error}) — running in SIM mode. "
          f"Run 'python3 relay_test.py' to diagnose.")


def execute_action(action: str, mqtt_client, sensor_state: dict):
    print(f"\n[Actuator] ▶ Executing: {action}")
    action = action.lower()

    if "activate-damage-alarm" in action: _trigger_buzzer_local()
    elif "capture-damage-evidence" in action: _capture_evidence(mqtt_client, sensor_state)
    elif "roll-down-windows" in action: _roll_down_windows()
    elif "engage-cooling" in action:
        # Heatstroke response: engage the cooling relay AND notify (SMS + dashboard).
        _trigger_cooling_local()
        _send_alert(mqtt_client, sensor_state)
    elif ("send-damage-alert" in action or "send-uv-warning" in action
          or "send-cabin-heat-alert" in action):
        # send-cabin-heat-alert fires when the cabin is hot with NO occupant:
        # no cooling, just a high-cabin-temperature alert.
        _send_alert(mqtt_client, sensor_state)


def _relay_on(name: str) -> bool:
    """Energise a named relay channel. Returns False if no board is present."""
    port = RELAY_CHANNELS.get(name)
    if RELAY_AVAILABLE and port is not None:
        return _relay.on(port)
    return False


def _relay_off(name: str):
    port = RELAY_CHANNELS.get(name)
    if RELAY_AVAILABLE and port is not None:
        _relay.off(port)


def _trigger_buzzer_local():
    # Latch the buzzer ON until disarm/reset or the alarm clears.
    # Backend is selectable via SENTINEL_BUZZER (relay [default] | bluetooth).
    if BUZZER_BACKEND == "bluetooth":
        print("  🔔 Buzzer backend = bluetooth")
        _buzzer_bluetooth_backup()
        return
    # Default: relay ONLY. We do NOT auto-switch to Bluetooth here — Bluetooth is
    # used only when explicitly selected with SENTINEL_BUZZER=bluetooth.
    if _relay_on("buzzer"):
        print("  🔔 Buzzer relay ON (latched until disarm)")
    else:
        print("  ⚠️  Buzzer relay NOT available and SENTINEL_BUZZER=relay — no alarm "
              "sounded. Fix the relay board, or set SENTINEL_BUZZER=bluetooth.")


def _trigger_cooling_local():
    # Latch the cooling relay ON — stays on until the cabin cools or disarm.
    if _relay_on("cooling"):
        print("  🌀 Cooling relay ON (latched until cooled)")
    else:
        print("  🌀 [SIM] Cooling relay ON (latched until cooled)")


def _roll_down_windows():
    # Pulse/latch the windows relay ON to drive the window-down motor.
    if _relay_on("windows"):
        print("  🪟 Windows relay ON — rolling windows down to vent the cabin")
    else:
        print("  🪟 [SIM] Windows relay ON — rolling windows down to vent the cabin")


def engage_manual_cooling(mqtt_client, sensor_state: dict):
    """Operator-initiated cooling from the dashboard's comfort button. Engages the
    cooling relay ONLY — deliberately never the windows (we don't open a car the
    driver isn't in yet) — and posts an informational note to the dashboard. This
    is a comfort action, so it is LOW severity, not an alarm, and it stays on until
    the operator turns it off again (or the system is disarmed)."""
    _trigger_cooling_local()
    mqtt_client.publish("sentinel/alert", json.dumps({
        "timestamp": str(datetime.now()),
        "event": "manual_cooling_engaged",
        "message": "Cooling system started remotely",
        "sensor_state": sensor_state,
        "severity": "LOW",
    }))
    print("  🌀 Manual cooling engaged by operator (windows stay up)")


def disengage_cooling():
    """Turn the cooling relay OFF without disturbing buzzer/windows. Used when the
    operator stops comfort cooling from the dashboard (a full disarm still uses
    all_actuators_off)."""
    _relay_off("cooling")
    print("  🌀 Cooling relay OFF (operator stopped comfort cooling)")


def all_actuators_off():
    """Turn every actuator off. Called on disarm/reset and when an alarm clears."""
    if RELAY_AVAILABLE:
        for name in RELAY_CHANNELS:
            _relay_off(name)
        print("  🔕 All relays OFF (buzzer · cooling · windows)")
    else:
        print("  🔕 [SIM] All relays OFF (buzzer · cooling · windows)")
    _stop_bluetooth_backup()

# ══════════════════════════════════════════════════════════════
# BLUETOOTH BUZZER BACKUP
# ──────────────────────────────────────────────────────────────
# Worst-case fallback for when no physical buzzer/relay is available: play an
# alarm tone through the system's DEFAULT audio output. On a Pi with a paired
# Bluetooth speaker (or phone) set as the default sink, the sound comes out of
# that Bluetooth device — a "software buzzer". The tone loops until stopped by
# all_actuators_off() (i.e. on disarm or auto-clear), mirroring the relay latch.
BT_ALARM_SOUND = os.getenv("SENTINEL_BT_SOUND", "alarm.wav")
_bt_proc = None   # subprocess.Popen | "winsound" | None


def _buzzer_bluetooth_backup():
    global _bt_proc
    if _bt_proc is not None and _bt_proc != "winsound" and _bt_proc.poll() is None:
        return  # already sounding

    if not os.path.exists(BT_ALARM_SOUND):
        print(f"  🔊 [BT backup] Sound file '{BT_ALARM_SOUND}' not found — "
              f"set SENTINEL_BT_SOUND to a .wav. (SIM: pretending to sound the alarm)")
        return

    # Prefer PulseAudio (paplay) so it routes to the default BT sink on the Pi.
    player = next((p for p in ("paplay", "aplay", "ffplay", "afplay") if shutil.which(p)), None)
    try:
        if player == "ffplay":
            _bt_proc = subprocess.Popen(
                [player, "-nodisp", "-autoexit", "-loop", "0", BT_ALARM_SOUND],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif player:
            # Loop the clip in a shell so it behaves like a latched buzzer.
            _bt_proc = subprocess.Popen(
                f'while true; do {player} "{BT_ALARM_SOUND}"; done',
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(BT_ALARM_SOUND, winsound.SND_ASYNC | winsound.SND_LOOP)
            _bt_proc = "winsound"
        else:
            print("  🔊 [BT backup] No audio player found (install pulseaudio/alsa-utils)")
            return
        print(f"  🔊 Bluetooth buzzer sounding via '{player or 'winsound'}' "
              f"→ default audio sink (pair a BT speaker to route it there)")
    except Exception as e:
        print(f"  🔊 [BT backup error] {e}")
        _bt_proc = None


def _stop_bluetooth_backup():
    global _bt_proc
    if _bt_proc is None:
        return
    try:
        if _bt_proc == "winsound":
            import winsound
            winsound.PlaySound(None, 0)
        elif _bt_proc.poll() is None:
            _bt_proc.terminate()
        print("  🔇 Bluetooth buzzer backup stopped")
    except Exception as e:
        print(f"  🔇 [BT backup stop error] {e}")
    finally:
        _bt_proc = None


def _encode_image(filepath: str) -> str | None:
    try:
        with open(filepath, "rb") as f: return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e: return None

def _capture_evidence(client, state: dict):
    reason = "damage" if state.get("damage_signal") else "motion"
    photo_path = capture_photo(reason=reason)
    if photo_path:
        b64_image = _encode_image(photo_path)
        client.publish("sentinel/evidence", json.dumps({
            "timestamp": str(datetime.now()), "filename": photo_path.split("/")[-1],
            "image_base64": b64_image, "event": "damage_evidence_captured"
        }))
        print(f"  📸 Evidence captured & encoded")
    else:
        client.publish("sentinel/evidence", json.dumps({"timestamp": str(datetime.now()), "image_base64": None}))

def _send_sms_alert(message: str):
    """Deliver the alert via the configured backend (console / email / twilio /
    ntfy / telegram). `message` is the already-phrased human alert text."""
    body = f"SENTINEL CAR ALERT: {message}"
    if NOTIFY_METHOD == "email":
        _notify_email(body)
    elif NOTIFY_METHOD == "twilio":
        _notify_twilio(body)
    elif NOTIFY_METHOD == "ntfy":
        _notify_ntfy(body)
    elif NOTIFY_METHOD == "telegram":
        _notify_telegram(body)
    else:
        print(f"  📱 [SIM] SMS: {body}   "
              f"(set SENTINEL_NOTIFY=ntfy|telegram|email|twilio for real delivery)")


def _notify_email(body: str):
    """Send the alert over SMTP. If ALERT_TO is a carrier email-to-SMS gateway,
    it is delivered to the phone as a real text message."""
    if not (SMTP_USER and SMTP_PASS and ALERT_TO):
        print("  📧 [SKIP] Email not configured (set SENTINEL_SMTP_USER/PASS/ALERT_TO)")
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = "Sentinel Car Alert"
        msg["From"]    = SMTP_USER
        msg["To"]      = ALERT_TO
        msg.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"  📱 SMS/email delivered to {ALERT_TO}")
    except Exception as e:
        print(f"  📧 [ERROR] Email send failed: {e}")

def _notify_ntfy(body: str):
    """FREE push via ntfy.sh — POST the message to a topic. No account needed;
    just install the ntfy app and subscribe to the same topic."""
    if not NTFY_TOPIC:
        print("  📱 [SKIP] ntfy not configured (set NTFY_TOPIC)")
        return
    import urllib.request
    url = f"{NTFY_SERVER.rstrip('/')}/{NTFY_TOPIC}"
    try:
        req = urllib.request.Request(
            url, data=body.encode("utf-8"),
            headers={"Title": "Sentinel Car Alert", "Priority": "high", "Tags": "car,warning"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        print(f"  📱 ntfy alert pushed to {url}")
    except Exception as e:
        print(f"  📱 [ERROR] ntfy send failed: {e}")


def _notify_telegram(body: str):
    """FREE push via a Telegram bot — real phone notification, any carrier."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("  📱 [SKIP] Telegram not configured (set TELEGRAM_BOT_TOKEN/CHAT_ID)")
        return
    import urllib.request, urllib.parse
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": body}).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            resp.read()
        print("  📱 Telegram alert sent")
    except Exception as e:
        print(f"  📱 [ERROR] Telegram send failed: {e}")


def _notify_twilio(body: str):
    """Send a real SMS through the Twilio API (requires the `twilio` package)."""
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM and TWILIO_TO):
        print("  📱 [SKIP] Twilio not configured (set TWILIO_* env vars)")
        return
    try:
        from twilio.rest import Client
        Client(TWILIO_SID, TWILIO_TOKEN).messages.create(
            body=body, from_=TWILIO_FROM, to=TWILIO_TO)
        print(f"  📱 Twilio SMS sent to {TWILIO_TO}")
    except Exception as e:
        print(f"  📱 [ERROR] Twilio send failed: {e}")

def _send_alert(client, state: dict):
    occupant = state.get("occupant_detected")
    if state.get("cabin_too_hot"):
        # Two distinct temperature alerts: with an occupant it's a life-safety
        # emergency, so make that unmistakable.
        if occupant:
            event   = "high_cabin_temperature_occupant_inside"
            message = "High cabin temp and OCCUPANT INSIDE!"
        else:
            event   = "high_cabin_temperature"
            message = "High cabin temp"
    elif state.get("cabin_uv_high"):
        event   = "high_uv_exposure"
        message = "High UV exposure" + (" and OCCUPANT INSIDE!" if occupant else "")
    else:
        event   = "damage_or_intrusion"
        message = "Damage / intrusion detected!"

    # Occupant-at-risk and damage are both HIGH severity.
    severity = "HIGH" if (state.get("damage_signal") or occupant) else "MEDIUM"
    alert = {"timestamp": str(datetime.now()), "event": event, "message": message,
             "sensor_state": state, "severity": severity}

    client.publish("sentinel/alert", json.dumps(alert))
    _send_sms_alert(message)
    print(f"  📧 Alert sent ({event}): {message}")

def trigger_failsafe_alarm(client):
    """OPTIONAL: escalates to the buzzer if cooling didn't bring the temp
    down in time. Called by main_coordinator's cooling watchdog."""
    print("  🚨 [FAILSAFE] Cooling ineffective — escalating to alarm")
    _trigger_buzzer_local()
    client.publish("sentinel/alert", json.dumps({
        "timestamp": str(datetime.now()),
        "event": "cooling_failsafe_alarm",
        "severity": "HIGH"
    }))