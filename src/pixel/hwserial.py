"""RS-485 serial transport for PIXEL controllers.

Wraps :mod:`pyserial` with pluggable direction control for RS-485 half-duplex:

* **None** (default) — auto-direction adapters (most USB-to-RS485 dongles)
* **RTS toggle** (``rts_toggle=True``) — adapter where the RTS pin drives DE/RE
* **Kernel RS-485** (``rs485=True``) — Linux kernel / driver managed RS-485 mode
* **GPIO pin** (``de_pin=N``) — bare transceiver on Raspberry Pi, using gpiozero

PIXEL panel serial defaults are 8E1; the 8051 flip-dot bus runs at 4800 baud, while
LPC1768 controllers are usually faster (e.g. 57600 / 115200) — set ``baud`` to match.

Feed an instance to :class:`pixel.pixel.Pixel`::

    from pixel.hwserial import HwSerial
    from pixel.pixel import Pixel

    conn = HwSerial("COM3", baud=4800)          # auto-direction USB adapter
    conn = HwSerial("/dev/ttyUSB0", de_pin=17)  # Raspberry Pi + GPIO
    conn.open()
    px = Pixel(conn)
"""
from __future__ import annotations

import serial

from pixel.serialbase import SerialConnector


class HwSerial(SerialConnector):
    """Unified RS-485 serial transport with pluggable direction control."""

    def __init__(
        self,
        port: str,
        *,
        de_pin: int | None = None,
        baud: int = 4800,
        bytesize: int = 8,
        parity: str = "E",
        stopbits: float = 1,
        timeout: float = 3.0,
        rts_toggle: bool = False,
        rs485: bool = False,
    ) -> None:
        self.port = port
        self.baud = baud
        self.bytesize = {5: serial.FIVEBITS, 6: serial.SIXBITS,
                         7: serial.SEVENBITS, 8: serial.EIGHTBITS}[bytesize]
        self.parity = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN,
                       "O": serial.PARITY_ODD, "M": serial.PARITY_MARK,
                       "S": serial.PARITY_SPACE}[parity.upper()]
        self.stopbits = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE,
                         2: serial.STOPBITS_TWO}[stopbits]
        self.timeout = timeout
        self.rts_toggle = rts_toggle
        self.rs485 = rs485
        self._driving = False
        self._serial: serial.Serial | None = None

        # GPIO direction control (Raspberry Pi)
        self._gpio_pin = None
        if de_pin is not None:
            try:
                from gpiozero import DigitalOutputDevice  # type: ignore
                from gpiozero.pins.native import NativeFactory  # type: ignore
            except ImportError:
                raise ImportError(
                    "gpiozero is required for GPIO direction control "
                    "(pip install gpiozero)")
            self._gpio_pin = DigitalOutputDevice(de_pin, pin_factory=NativeFactory())

    def open(self) -> bool:
        s = serial.Serial(
            port=self.port, baudrate=self.baud, bytesize=self.bytesize,
            parity=self.parity, stopbits=self.stopbits, timeout=self.timeout,
        )
        if self.rs485:
            try:
                import serial.rs485 as rs485mod
                s.rs485_mode = rs485mod.RS485Settings(
                    rts_level_for_tx=True, rts_level_for_rx=False)
            except Exception:
                pass  # driver may not support it; fall through to rts_toggle / auto
        if self.rts_toggle:
            s.rts = False
        self._serial = s
        return self._serial.is_open

    # -- direction helpers --------------------------------------------------

    def _assert_tx(self) -> None:
        """Drive the bus (DE high) before transmitting."""
        if self._gpio_pin is not None:
            self._gpio_pin.on()
        elif self.rts_toggle:
            self._serial.rts = True

    def _release_tx(self) -> None:
        """Release the bus after transmitting."""
        if self._gpio_pin is not None:
            self._gpio_pin.off()
        elif self.rts_toggle:
            self._serial.rts = False

    # -- SerialConnector interface ------------------------------------------

    def write(self, data: bytes) -> None:
        if not self._driving:
            self._assert_tx()
            self._driving = True
        self._serial.write(data)

    def flush(self) -> None:
        self._serial.flush()
        if self._driving:
            self._release_tx()
            self._driving = False

    def read_until(self, expected: bytes) -> bytes:
        return self._serial.read_until(expected)

    def close(self) -> None:
        if self._serial is not None and self._serial.is_open:
            self._serial.close()

    def set_timeout(self, timeout: float) -> None:
        self.timeout = timeout
        if self._serial is not None:
            self._serial.timeout = timeout

    def get_timeout(self) -> float:
        return self._serial.timeout if self._serial is not None else self.timeout
