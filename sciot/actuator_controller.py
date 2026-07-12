# # actuator_controller.py — v5 (Twilio SMS added)

# WORKIGN code fall back here 



# import json
# import base64
# from datetime import datetime
# from camera_capture import capture_photo

# # --- TWILIO SMS SETUP ---
# # To enable real SMS, uncomment these 3 lines and put your Twilio credentials:
# # from twilio.rest import Client
# # TWILIO_ACCOUNT_SID = 'your_account_sid_here'
# # TWILIO_AUTH_TOKEN = 'your_auth_token_here'
# # TWILIO_PHONE_NUMBER = '+1234567890'
# # ALERT_DESTINATION_NUMBER = '+0987654321'
# # -----------------------

# try:
#     from gpiozero import Buzzer, OutputDevice
#     buzzer = Buzzer(17); fan = OutputDevice(27); GPIO_AVAILABLE = True
# except Exception as e:
#     print(f"[GPIO] Not available: {e}"); GPIO_AVAILABLE = False

# def execute_action(action: str, mqtt_client, sensor_state: dict):
#     print(f"\n[Actuator] ▶ Executing: {action}")
#     action = action.lower()

#     if "activate-damage-alarm" in action: _trigger_buzzer_local()
#     elif "capture-damage-evidence" in action: _capture_evidence(mqtt_client, sensor_state)
#     elif "send-damage-alert" in action or "send-uv-warning" in action: _send_alert(mqtt_client, sensor_state)
#     elif "engage-cooling" in action: _trigger_cooling_local()

# def _trigger_buzzer_local():
#     if GPIO_AVAILABLE:
#         buzzer.on(); print("  🔔 Buzzer ON")
#         import threading; threading.Timer(5.0, buzzer.off).start()
#     else: print("  🔔 [SIM] Buzzer ON")

# def _trigger_cooling_local():
#     if GPIO_AVAILABLE: fan.on(); print("  🌀 Fan ON")
#     else: print("  🌀 [SIM] Fan ON")

# def _encode_image(filepath: str) -> str | None:
#     try:
#         with open(filepath, "rb") as f: return base64.b64encode(f.read()).decode('utf-8')
#     except Exception as e: return None

# def _capture_evidence(client, state: dict):
#     reason = "damage" if state.get("damage_signal") else "motion"
#     photo_path = capture_photo(reason=reason)
#     if photo_path:
#         b64_image = _encode_image(photo_path)
#         client.publish("sentinel/evidence", json.dumps({
#             "timestamp": str(datetime.now()), "filename": photo_path.split("/")[-1],
#             "image_base64": b64_image, "event": "damage_evidence_captured"
#         }))
#         print(f"  📸 Evidence captured & encoded")
#     else:
#         client.publish("sentinel/evidence", json.dumps({"timestamp": str(datetime.now()), "image_base64": None}))

# def _send_sms_alert(scenario: str):
#     """Sends a real SMS if Twilio is configured, otherwise simulates."""
#     try:
#         # twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
#         # twilio_client.messages.create(
#         #     body=f"SENTINEL CAR ALERT: {scenario} detected!",
#         #     from_=TWILIO_PHONE_NUMBER, to=ALERT_DESTINATION_NUMBER
#         # )
#         print(f"  📱 [SIM] SMS Sent: {scenario} detected!") # Leave this line for simulation
#     except NameError:
#         print(f"  📱 [SIM] SMS Sent: {scenario} detected! (Configure Twilio for real SMS)")

# def _send_alert(client, state: dict):
#     if state.get("cabin_too_hot"): event = "high_cabin_temperature"
#     elif state.get("cabin_uv_high"): event = "high_uv_exposure"
#     else: event = "damage_or_intrusion"
        
#     alert = {"timestamp": str(datetime.now()), "event": event, "sensor_state": state, "severity": "HIGH" if state.get("damage_signal") else "MEDIUM"}
    
#     client.publish("sentinel/alert", json.dumps(alert))
#     _send_sms_alert(event.replace("_", " ").title())
#     print(f"  📧 Alert sent ({event})")



# actuator_controller.py — v6 (configurable notifications: console / email-to-SMS / Twilio)
import os
import json
import base64
import smtplib
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
#
# Set with:  export SENTINEL_NOTIFY=email   (Linux/Pi)
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

try:
    from gpiozero import Buzzer, OutputDevice
    buzzer = Buzzer(17); fan = OutputDevice(27); GPIO_AVAILABLE = True
except Exception as e:
    print(f"[GPIO] Not available: {e}"); GPIO_AVAILABLE = False

def execute_action(action: str, mqtt_client, sensor_state: dict):
    print(f"\n[Actuator] ▶ Executing: {action}")
    action = action.lower()

    if "activate-damage-alarm" in action: _trigger_buzzer_local()
    elif "capture-damage-evidence" in action: _capture_evidence(mqtt_client, sensor_state)
    elif "send-damage-alert" in action or "send-uv-warning" in action: _send_alert(mqtt_client, sensor_state)
    elif "engage-cooling" in action:
        # Heatstroke response: engage the relay/AC AND notify (SMS + dashboard alert)
        _trigger_cooling_local()
        _send_alert(mqtt_client, sensor_state)

def _trigger_buzzer_local():
    # Latch the buzzer ON — it stays on until disarm/reset or the alarm clears.
    if GPIO_AVAILABLE:
        buzzer.on(); print("  🔔 Buzzer ON (latched until disarm)")
    else: print("  🔔 [SIM] Buzzer ON (latched until disarm)")

def _trigger_cooling_local():
    # Latch the relay/fan ON — it stays on until the cabin cools or disarm.
    if GPIO_AVAILABLE: fan.on(); print("  🌀 Relay/fan ON (latched until cooled)")
    else: print("  🌀 [SIM] Relay/fan ON (latched until cooled)")

def all_actuators_off():
    """Turn every actuator off. Called on disarm/reset and when an alarm clears."""
    if GPIO_AVAILABLE:
        buzzer.off(); fan.off()
        print("  🔕 Buzzer OFF · 🌀 Relay/fan OFF")
    else:
        print("  🔕 [SIM] Buzzer OFF · Relay/fan OFF")

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

def _send_sms_alert(scenario: str):
    """Deliver the alert via the configured backend (console / email / twilio)."""
    body = f"SENTINEL CAR ALERT: {scenario} detected!"
    if NOTIFY_METHOD == "email":
        _notify_email(body)
    elif NOTIFY_METHOD == "twilio":
        _notify_twilio(body)
    else:
        print(f"  📱 [SIM] SMS: {body}   (set SENTINEL_NOTIFY=email|twilio for real delivery)")


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
    if state.get("cabin_too_hot"): event = "high_cabin_temperature"
    elif state.get("cabin_uv_high"): event = "high_uv_exposure"
    else: event = "damage_or_intrusion"
        
    alert = {"timestamp": str(datetime.now()), "event": event, "sensor_state": state, "severity": "HIGH" if state.get("damage_signal") else "MEDIUM"}
    
    client.publish("sentinel/alert", json.dumps(alert))
    _send_sms_alert(event.replace("_", " ").title())
    print(f"  📧 Alert sent ({event})")

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