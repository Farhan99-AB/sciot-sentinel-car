#!/usr/bin/env python3
# relay_test.py — standalone diagnostic for the Seeed Pi Relay Board v1.0
# ─────────────────────────────────────────────────────────────────────────────
# Run this ON THE PI to prove the relay board actually clicks / lights up before
# worrying about the rest of the pipeline. It uses the SAME driver
# (seeed_relay.SeeedRelay) that the main app uses, with debug prints on.
#
# Usage:
#   python3 relay_test.py                 # full guided test of all 4 relays
#   python3 relay_test.py --scan          # just list I2C devices (like i2cdetect)
#   python3 relay_test.py --relay 1       # cycle only relay 1
#   python3 relay_test.py --channel cooling   # cycle the mapped 'cooling' relay
#   python3 relay_test.py --on 2          # turn relay 2 ON and leave it on
#   python3 relay_test.py --off 2         # turn relay 2 OFF
#   python3 relay_test.py --all-off       # force every relay OFF
#
# Env overrides (see seeed_relay.py): SENTINEL_RELAY_BUS / _ADDR
import argparse
import sys
import time

from seeed_relay import SeeedRelay, NUM_PORTS, I2C_BUS, I2C_ADDR

# Which physical relay port drives each function in the main app. Keep this in
# sync with actuator_controller.RELAY_CHANNELS (both read the same env vars).
import os
CHANNELS = {
    "cooling": int(os.getenv("SENTINEL_RELAY_COOLING", "1")),
    "buzzer":  int(os.getenv("SENTINEL_RELAY_BUZZER",  "2")),
    "windows": int(os.getenv("SENTINEL_RELAY_WINDOWS", "3")),
}


def hr(title=""):
    print("\n" + "═" * 60)
    if title:
        print(title)
        print("═" * 60)


def troubleshoot(relay):
    hr("❌ Relay board NOT detected")
    print(f"Driver error: {relay.last_error!r}")
    print("\nWork through these on the Pi:")
    print("  1. Enable I2C:      sudo raspi-config  → Interface Options → I2C → Yes")
    print("                      (or add 'dtparam=i2c_arm=on' to /boot/config.txt, reboot)")
    print("  2. Install tooling: sudo apt install -y i2c-tools python3-smbus")
    print("                      (or: pip3 install smbus2)")
    print(f"  3. See the board:   i2cdetect -y {I2C_BUS}")
    print(f"     → expect a device at {hex(I2C_ADDR)}. If it shows at a DIFFERENT")
    print("       address, set it, e.g.:  export SENTINEL_RELAY_ADDR=0x11")
    print("  4. Check the board is seated on the 40-pin header and powered.")
    print("  5. Re-run this script.")


def probe_addresses(relay):
    hr(f"I2C scan on bus {I2C_BUS}")
    found = relay.scan()
    if not found:
        print("No I2C devices responded. I2C likely disabled or board unpowered.")
    else:
        print("Responding addresses:", ", ".join(hex(a) for a in found))
        if I2C_ADDR in found:
            print(f"✅ Board address {hex(I2C_ADDR)} is present.")
        else:
            print(f"⚠️  Expected {hex(I2C_ADDR)} not in the list — set SENTINEL_RELAY_ADDR "
                  f"to one of the above.")
    return found


def cycle_relay(relay, port, dwell):
    ch = next((name for name, p in CHANNELS.items() if p == port), None)
    label = f"relay {port}" + (f"  ({ch})" if ch else "")
    print(f"\n▶ Testing {label}")
    print(f"   turning ON  — watch for the board's LED{port} and a click …")
    relay.on(port)
    print(f"   register now: {format(relay._reg, '08b')}  | is_on={relay.is_on(port)}")
    time.sleep(dwell)
    print(f"   turning OFF …")
    relay.off(port)
    print(f"   register now: {format(relay._reg, '08b')}  | is_on={relay.is_on(port)}")
    time.sleep(0.4)


def main():
    ap = argparse.ArgumentParser(description="Seeed Pi relay board tester")
    ap.add_argument("--scan", action="store_true", help="list I2C devices and exit")
    ap.add_argument("--relay", type=int, metavar="N", help="cycle only relay N (1-4)")
    ap.add_argument("--channel", choices=list(CHANNELS), help="cycle the mapped channel")
    ap.add_argument("--on", type=int, metavar="N", help="turn relay N ON and exit")
    ap.add_argument("--off", type=int, metavar="N", help="turn relay N OFF and exit")
    ap.add_argument("--all-off", action="store_true", help="force all relays OFF and exit")
    ap.add_argument("--dwell", type=float, default=1.5, help="seconds to hold each relay ON")
    args = ap.parse_args()

    hr("Seeed Pi Relay Board — diagnostic")
    print(f"bus={I2C_BUS}  addr={hex(I2C_ADDR)}  ports={NUM_PORTS}")
    print(f"channel map: {CHANNELS}")

    relay = SeeedRelay(debug=True)

    probe_addresses(relay)

    if not relay.available:
        troubleshoot(relay)
        sys.exit(1)

    if args.scan:
        return

    # One-shot commands
    if args.all_off:
        relay.all_off(); print("\n✅ All relays OFF."); return
    if args.on is not None:
        relay.on(args.on); print(f"\n✅ Relay {args.on} left ON."); return
    if args.off is not None:
        relay.off(args.off); print(f"\n✅ Relay {args.off} left OFF."); return

    # Which relays to cycle
    if args.relay is not None:
        ports = [args.relay]
    elif args.channel is not None:
        ports = [CHANNELS[args.channel]]
    else:
        ports = list(range(1, NUM_PORTS + 1))

    hr("Cycling relays — you should SEE the board LEDs and HEAR clicks")
    try:
        for p in ports:
            cycle_relay(relay, p, args.dwell)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        relay.all_off()
        print("\n✅ Test complete — all relays returned to OFF.")
        print("   • If LEDs lit / relays clicked → the board works; wire your")
        print("     buzzer & motor to the relay's COM/NO terminals + their own supply.")
        print("   • If nothing happened but no error → check wiring/power to the load;")
        print("     the relay only switches, it doesn't power the load itself.")


if __name__ == "__main__":
    main()
