import os
import smtplib
from email.message import EmailMessage

NOTIFY_METHOD = os.getenv("SENTINEL_NOTIFY", "telegram").lower()
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
    # Common mistake: putting the email address into SENTINEL_SMTP_HOST.
    if "@" in host:
        print(f"✗ SENTINEL_SMTP_HOST looks like an email address ('{host}').")
        print("  It must be the mail SERVER, e.g.  export SENTINEL_SMTP_HOST=smtp.gmail.com")
        print("  Put your address in SENTINEL_SMTP_USER instead.")
        return
    msg = EmailMessage()
    msg["Subject"] = "Sentinel Car Alert (TEST)"
    msg["From"] = user
    msg["To"] = to
    msg.set_content(MESSAGE)
    print(f"→ Sending via {host}:{port} (user {user}) to {to} ...")
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(user, pw)
            server.send_message(msg)
        print(f"✓ Sent! Check {to}")
    except smtplib.SMTPAuthenticationError:
        print("✗ Login rejected. For Gmail you must use a 16-char *App Password*")
        print("  (Account → Security → 2-Step Verification → App passwords), not your")
        print("  normal password. Set it as SENTINEL_SMTP_PASS (no spaces).")
    except OSError as e:
        print(f"✗ Could not reach {host}:{port} ({e}).")
        print("  Check the hostname is correct and the Pi has internet/DNS.")


def send_twilio():
    sid   = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    frm   = os.getenv("TWILIO_FROM", "")
    to    = os.getenv("TWILIO_TO", "")
    if not (sid and token and frm and to):
        print("✗ Missing TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM / TWILIO_TO")
        return
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException
    print(f"→ Sending Twilio SMS from {frm} to {to} ...")
    try:
        Client(sid, token).messages.create(body=MESSAGE, from_=frm, to=to)
        print(f"✓ Sent! Check {to}")
    except TwilioRestException as e:
        print(f"✗ Twilio rejected the message (code {e.code}): {e.msg}")
        if e.code == 21659 or "is not a Twilio phone number" in str(e.msg):
            print("  → TWILIO_FROM must be YOUR Twilio number, not a personal number.")
            print("     Find it in Console → Phone Numbers → Manage → Active numbers,")
            print("     then:  export TWILIO_FROM='+1XXXXXXXXXX'")
        elif e.code == 21608:
            print("  → On a TRIAL account you can only send to VERIFIED numbers.")
            print("     Verify TWILIO_TO in Console → Phone Numbers → Verified Caller IDs.")


def send_ntfy():
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    topic  = os.getenv("NTFY_TOPIC", "sentinel_car_alert")
    if not topic:
        print("✗ Missing NTFY_TOPIC (pick any topic, subscribe to it in the ntfy app)")
        return
    import urllib.request
    url = f"{server}/{topic}"
    print(f"→ Pushing to {url} ...")
    try:
        req = urllib.request.Request(url, data=MESSAGE.encode(),
              headers={"Title": "Sentinel Car Alert (TEST)", "Priority": "high"})
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        print(f"✓ Sent! Check the ntfy app subscribed to '{topic}'.")
    except Exception as e:
        print(f"✗ ntfy push failed: {e}")


def send_telegram():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat  = os.getenv("TELEGRAM_CHAT_ID", "")
    if not (token and chat):
        print("✗ Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        print("  Make a bot with @BotFather, message it once, then read your chat id at")
        print("  https://api.telegram.org/bot<token>/getUpdates")
        return
    import urllib.request, urllib.parse
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": MESSAGE}).encode()
    print(f"→ Sending Telegram message to chat {chat} ...")
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as r:
            r.read()
        print("✓ Sent! Check Telegram.")
    except Exception as e:
        print(f"✗ Telegram send failed: {e}")


if __name__ == "__main__":
    print(f"Notification method: {NOTIFY_METHOD}\n")
    if NOTIFY_METHOD == "email":
        send_email()
    elif NOTIFY_METHOD == "twilio":
        send_twilio()
    elif NOTIFY_METHOD == "ntfy":
        send_ntfy()
    elif NOTIFY_METHOD == "telegram":
        send_telegram()
    else:
        print(f"[CONSOLE] {MESSAGE}")
        print("\n(No real delivery. Set SENTINEL_NOTIFY=ntfy|telegram|email|twilio to send for real.)")
