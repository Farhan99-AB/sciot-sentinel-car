# test_sms.py — prove the alert/SMS pipeline WITHOUT any hardware.
#
# This is self-contained (no GPIO, no camera, no MQTT) so it runs on any laptop.
# It uses the SAME environment variables as actuator_controller.py, so once this
# works, the real system's alerts work too.
#
# ── Quick start (email-to-SMS, the free/no-hardware route) ─────────────────
#   1. Gmail: turn on 2-Step Verification, then create an "App Password"
#      (Google Account → Security → App passwords). Copy the 16 characters.
#   2. Set env vars (Linux/Pi shown; on Windows PowerShell use $env:NAME="...")
#        export SENTINEL_NOTIFY=email
#        export SENTINEL_SMTP_USER="youraddress@gmail.com"
#        export SENTINEL_SMTP_PASS="the16charapppassword"
#        export SENTINEL_ALERT_TO="youraddress@gmail.com"   # or a carrier gateway
#   3. Run:  python test_sms.py
#
#   To land it as a REAL text on a phone, set SENTINEL_ALERT_TO to your carrier's
#   email-to-SMS gateway, e.g.  5551234567@txt.att.net  (AT&T),
#   5551234567@tmomail.net (T-Mobile), 5551234567@vtext.com (Verizon).
#
# ── Twilio route (real SMS via API, needs a free trial account) ────────────
#        export SENTINEL_NOTIFY=twilio
#        export TWILIO_ACCOUNT_SID=... TWILIO_AUTH_TOKEN=...
#        export TWILIO_FROM=+1xxx   TWILIO_TO=+1yyy   (verified number)
#        pip install twilio ; python test_sms.py

import os
import smtplib
from email.message import EmailMessage

NOTIFY_METHOD = os.getenv("SENTINEL_NOTIFY", "console").lower()
MESSAGE = "SENTINEL CAR ALERT: TEST message — if you can read this, SMS works!"


def send_email():
    host = os.getenv("SENTINEL_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SENTINEL_SMTP_PORT", "587"))
    user = os.getenv("SENTINEL_SMTP_USER", "")
    pw   = os.getenv("SENTINEL_SMTP_PASS", "")
    to   = os.getenv("SENTINEL_ALERT_TO", "")
    if not (user and pw and to):
        print("✗ Missing SENTINEL_SMTP_USER / SENTINEL_SMTP_PASS / SENTINEL_ALERT_TO")
        return
    msg = EmailMessage()
    msg["Subject"] = "Sentinel Car Alert (TEST)"
    msg["From"] = user
    msg["To"] = to
    msg.set_content(MESSAGE)
    print(f"→ Sending via {host}:{port} to {to} ...")
    with smtplib.SMTP(host, port, timeout=15) as server:
        server.starttls()
        server.login(user, pw)
        server.send_message(msg)
    print(f"✓ Sent! Check {to}")


def send_twilio():
    sid   = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    frm   = os.getenv("TWILIO_FROM", "")
    to    = os.getenv("TWILIO_TO", "")
    if not (sid and token and frm and to):
        print("✗ Missing TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM / TWILIO_TO")
        return
    from twilio.rest import Client
    print(f"→ Sending Twilio SMS to {to} ...")
    Client(sid, token).messages.create(body=MESSAGE, from_=frm, to=to)
    print(f"✓ Sent! Check {to}")


if __name__ == "__main__":
    print(f"Notification method: {NOTIFY_METHOD}\n")
    if NOTIFY_METHOD == "email":
        send_email()
    elif NOTIFY_METHOD == "twilio":
        send_twilio()
    else:
        print(f"[CONSOLE] {MESSAGE}")
        print("\n(No real delivery. Set SENTINEL_NOTIFY=email or =twilio to send for real.)")
