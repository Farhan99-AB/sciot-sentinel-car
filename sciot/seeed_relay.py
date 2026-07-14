# seeed_relay.py — driver for the Seeed Studio Relay Board v1.0 for Raspberry Pi
# ─────────────────────────────────────────────────────────────────────────────
# https://paradisetronic.com/products/seeed-studio-relay-board-v1-0-raspberry-pi
# Protocol adapted from github.com/johnwargo/raspberry-pi-relay-controller-seeed
#
# The board is I2C (NOT plain GPIO). All four relays share ONE 8-bit data
# register (0x06) at I2C address 0x20:
#     bit CLEARED (0) → relay ON        bit SET (1) → relay OFF   (active-low)
# We keep a shadow copy of that register and read-modify-write it per change.
#
# This module is the single source of truth for talking to the board. Both the
# standalone tester (relay_test.py) and the production code
# (actuator_controller.py) import THIS class, so whatever you verify with the
# tester is exactly what runs in the main app.
import os

# Defaults are overridable by environment so you don't have to edit code:
#   SENTINEL_RELAY_BUS   (default 1)      → I2C bus number
#   SENTINEL_RELAY_ADDR  (default 0x20)   → board I2C address
#   SENTINEL_RELAY_DEBUG (default 0)      → 1 to print every register write
I2C_BUS   = int(os.getenv("SENTINEL_RELAY_BUS", "1"))
I2C_ADDR  = int(os.getenv("SENTINEL_RELAY_ADDR", "0x20"), 0)
DATA_REG  = 0x06        # the board's relay-data register
NUM_PORTS = 4


class SeeedRelay:
    """Thin, debuggable driver for the Seeed 4-channel Pi relay board."""

    def __init__(self, bus=I2C_BUS, addr=I2C_ADDR, debug=False):
        self.addr = addr
        self.bus_num = bus
        self.debug = debug
        self._reg = 0xFF          # shadow register; 0xFF = every relay OFF
        self._bus = None
        self.available = False
        self.last_error = None

        try:
            # smbus2 (pip) or smbus (apt: python3-smbus) — either works.
            try:
                from smbus2 import SMBus
            except ImportError:
                from smbus import SMBus
            self._bus = SMBus(bus)
            self._write(self._reg)            # initialise: all relays OFF
            self.available = True
            self._log(f"connected on I2C bus {bus} @ {hex(addr)} — all relays OFF")
        except Exception as e:
            self.last_error = e
            self._log(f"NOT available: {e!r}")

    # ── internal helpers ────────────────────────────────────────
    def _log(self, msg):
        if self.debug:
            print(f"[SeeedRelay] {msg}")

    def _write(self, value):
        value &= 0xFF
        self._bus.write_byte_data(self.addr, DATA_REG, value)
        self._log(f"I2C write  reg={hex(DATA_REG)} value={format(value, '08b')} ({hex(value)})")

    def _valid(self, port):
        if isinstance(port, int) and 1 <= port <= NUM_PORTS:
            return True
        self._log(f"invalid relay port {port!r} (must be 1..{NUM_PORTS})")
        return False

    def _apply(self, description):
        if not self.available:
            self._log(f"[SIM] {description} (no board present)")
            return False
        self._write(self._reg)
        self._log(description)
        return True

    # ── public API ──────────────────────────────────────────────
    def on(self, port):
        """Energise a relay (1..4). Clears its bit in the shadow register."""
        if not self._valid(port):
            return False
        self._reg &= ~(0x1 << (port - 1))
        return self._apply(f"relay {port} ON")

    def off(self, port):
        """De-energise a relay (1..4). Sets its bit in the shadow register."""
        if not self._valid(port):
            return False
        self._reg |= (0x1 << (port - 1))
        return self._apply(f"relay {port} OFF")

    def all_on(self):
        self._reg &= ~0x0F
        return self._apply("ALL relays ON")

    def all_off(self):
        self._reg |= 0x0F
        return self._apply("ALL relays OFF")

    def is_on(self, port):
        """Return True if the given port is currently ON (per our shadow reg)."""
        if not self._valid(port):
            return False
        return not bool(self._reg & (0x1 << (port - 1)))

    def read_register(self):
        """Read the data register back from the board (diagnostic)."""
        if not self.available:
            return None
        val = self._bus.read_byte_data(self.addr, DATA_REG)
        self._log(f"I2C read   reg={hex(DATA_REG)} value={format(val, '08b')} ({hex(val)})")
        return val

    def scan(self):
        """i2cdetect-style probe: return the list of responding I2C addresses."""
        if self._bus is None:
            return []
        found = []
        for a in range(0x03, 0x78):
            try:
                self._bus.read_byte(a)
                found.append(a)
            except Exception:
                pass
        return found
