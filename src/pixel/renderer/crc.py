"""CRC-16/CCITT used by every PIXEL ``DDB`` block.

Poly ``0x1021``, init ``0x0000``, no input/output reflection, no final xor. It is
identical on the 8051 ``PIXEL-SIMS`` and the LPC1768 controllers and matches the
reference driver's ``get_crc16`` (``PythonPixelBydgoszcz/pixel.py``) and the 8051
firmware LUT.
"""
from __future__ import annotations


def crc16_ccitt(data: bytes) -> int:
    """Return the CRC-16/CCITT of *data* (0..0xFFFF)."""
    crc = 0x0000
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF
