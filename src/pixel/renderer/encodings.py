"""Pixel encodings for PIXEL ``DDB`` sub-images.

Each :class:`Encoding` turns a :class:`~pixel_renderer.frame.Frame` into the packed
pixel bytes that go after a sub-image header, and describes how it is selected in
the header (the 8051/LPC *classic* 6-byte header ``SETUP.6`` bit, or the LPC
*extended* 15-byte header flag nibble).

Confidence
----------
``verified = True`` marks encodings whose byte layout is reverse-engineered and
confirmed from the firmware / reference driver:

* ``bitmap``     — 1 bpp, MSB-first (8051 legacy; LPC ``Prosta`` decoder ``0x8CCC``).
* ``nibble_rle`` — the 8051's preferred mono run-length encoding.

Everything colour/grey/stuffed is ``verified = False``: the geometry, framing and
CRC around them are confirmed, but the exact bit packing and the extended-header
flag-nibble values still need a bench check (see ``findings/ddb-build-guide.md`` §6).
Their ``extended_flag`` values below are placeholders — override them once known.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

from .frame import ColorMode, Frame

CTRL_8051 = "8051"
CTRL_LPC = "lpc1768"


@dataclass
class EncodedImage:
    """Result of :meth:`Encoding.encode`."""

    data: bytes
    start_color: int = 1  # -> classic SETUP.5 (mono polarity / RLE start colour)


class Encoding(ABC):
    """Base class for all pixel encodings."""

    name: str = ""
    color_mode: ColorMode = ColorMode.MONO
    controllers: frozenset = frozenset()
    classic_capable: bool = False       # fits the 6-byte classic header?
    classic_encoding_bit: int = 0       # SETUP.6 value when classic (0 bitmap, 1 nibble)
    extended_flag: Optional[int] = None  # bits4-7 of the extended flag byte [+0xC]
    verified: bool = False
    note: str = ""

    @abstractmethod
    def encode(self, frame: Frame, *, start_color: Optional[int] = None) -> EncodedImage:
        ...

    def __repr__(self) -> str:
        return (f"<Encoding {self.name!r} mode={self.color_mode.value} "
                f"verified={self.verified}>")


# --------------------------------------------------------------------- helpers
def _pack_bits(bits: List[int], msb_first: bool = True) -> bytes:
    out = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for j in range(8):
            if i + j < len(bits) and bits[i + j]:
                byte |= (0x80 >> j) if msb_first else (1 << j)
        out.append(byte)
    return bytes(out)


def _pack_nibbles(nibbles: List[int]) -> bytes:
    out = bytearray()
    for i in range(0, len(nibbles), 2):
        hi = nibbles[i] & 0xF
        lo = nibbles[i + 1] & 0xF if i + 1 < len(nibbles) else 0
        out.append((hi << 4) | lo)
    return bytes(out)


# ------------------------------------------------------------ mono (verified)
class BitmapEncoding(Encoding):
    """1 bpp packed bitmap, 8 px/byte.

    The firmware unpacks **MSB-first** (mask ``0x80`` -> ``0x01``). On the 8051 this
    is ``SETUP.6 = 0``; on the LPC1768 it is the ``Prosta`` (Simple) type, decoder
    ``0x8CCC`` (verified MSB-first).

    Note: the reference ``pixel.py`` packs LSB-first *and* applies a panel-specific
    16-row bank swap; that is a property of that one 84x16 panel, not the format.
    Prefer ``nibble_rle`` for the 8051 in practice.
    """

    color_mode = ColorMode.MONO
    controllers = frozenset({CTRL_8051, CTRL_LPC})
    classic_capable = True
    classic_encoding_bit = 0
    verified = True

    def __init__(self, *, msb_first: bool = True, name: str = "bitmap",
                 controllers: Optional[frozenset] = None,
                 extended_flag: Optional[int] = 0x1, verified: bool = True,
                 note: str = "") -> None:
        self.msb_first = msb_first
        self.name = name
        if controllers is not None:
            self.controllers = controllers
        self.extended_flag = extended_flag
        self.verified = verified
        self.note = note

    def encode(self, frame, *, start_color=None):
        bits = [1 if p else 0 for p in frame.stream()]
        sc = 1 if start_color is None else (start_color & 1)
        return EncodedImage(_pack_bits(bits, self.msb_first), sc)


class NibbleRleEncoding(Encoding):
    """Nibble run-length — the 8051's preferred mono encoding (``SETUP.6 = 1``).

    Each nibble is a run length (high nibble first): ``1..15`` draws that many dots
    of the current colour then toggles; ``0`` draws 15 dots and does **not** toggle
    (used to chain runs longer than 15). The start colour is reported so the caller
    can set ``SETUP.5``.
    """

    name = "nibble_rle"
    color_mode = ColorMode.MONO
    controllers = frozenset({CTRL_8051, CTRL_LPC})
    classic_capable = True
    classic_encoding_bit = 1
    extended_flag = 0x2       # verified: segment control 0x82 -> nibble decoder 0x8DC4
    verified = True

    def encode(self, frame, *, start_color=None):
        seq = [1 if p else 0 for p in frame.stream()]
        if start_color is None:
            start_color = seq[0] if seq else 1
        color = start_color & 1
        nibbles: List[int] = []
        run = 0

        def flush() -> None:
            nonlocal run
            if run == 0:
                return
            while run > 15:
                nibbles.append(0)   # 15 dots, no toggle
                run -= 15
            nibbles.append(run)     # 1..15 dots, then toggle
            run = 0

        for p in seq:
            if p == color:
                run += 1
            else:
                flush()
                color ^= 1
                run = 1
        flush()
        return EncodedImage(_pack_nibbles(nibbles), start_color & 1)


class ProstaRbitEncoding(BitmapEncoding):
    """``Prosta RBIT`` — bitmap with reversed (LSB-first) bit order (LPC only)."""

    def __init__(self) -> None:
        super().__init__(msb_first=False, name="prosta_rbit",
                         controllers=frozenset({CTRL_LPC}), extended_flag=0x2,
                         verified=False,
                         note="Bitmap with reversed bit order; bench-verify orientation.")


# --------------------------------------------------- colour / grey (unverified)
class HalfByteEncoding(Encoding):
    """4 bpp grey, 2 px/byte (high nibble = first pixel)."""

    name = "halfbyte"
    color_mode = ColorMode.GRAY4
    controllers = frozenset({CTRL_LPC})
    classic_capable = False
    extended_flag = 0x4
    verified = False
    note = "4 bpp grey, 2 px/byte; flag nibble + packing bench-verify."

    def encode(self, frame, *, start_color=None):
        vals = [int(v) & 0xF for v in frame.stream()]
        return EncodedImage(_pack_nibbles(vals), 1)


class ProstaRgbEncoding(Encoding):
    """``Prosta RGB`` — 3 bytes per pixel (R, G, B)."""

    name = "prosta_rgb"
    color_mode = ColorMode.RGB
    controllers = frozenset({CTRL_LPC})
    classic_capable = False
    extended_flag = 0x1
    verified = False
    note = "Simple RGB, 3 bytes/pixel; channel order bench-verify."

    def encode(self, frame, *, start_color=None):
        out = bytearray()
        for r, g, b in frame.stream():
            out += bytes((r & 0xFF, g & 0xFF, b & 0xFF))
        return EncodedImage(bytes(out), 1)


class HalfByteRgbEncoding(Encoding):
    """``HalfByte RGB`` — 4 bpp per channel (12-bit colour), nibbles packed 2/byte."""

    name = "halfbyte_rgb"
    color_mode = ColorMode.RGB
    controllers = frozenset({CTRL_LPC})
    classic_capable = False
    extended_flag = 0x5
    verified = False
    note = "12-bit RGB; nibble-per-channel packing bench-verify."

    def encode(self, frame, *, start_color=None):
        nibbles: List[int] = []
        for r, g, b in frame.stream():
            nibbles += [r >> 4, g >> 4, b >> 4]
        return EncodedImage(_pack_nibbles(nibbles), 1)


class StuffedByteEncoding(Encoding):
    """``StuffedByte_N`` — N pixels packed per byte (best-effort layout).

    Interpreted as ``N`` equal bit-slices per byte, first pixel in the high bits,
    grey input scaled to the slice width. The real packing is not yet mapped from
    the firmware, so treat output as a starting point and bench-verify.
    """

    color_mode = ColorMode.GRAY4
    controllers = frozenset({CTRL_LPC})
    classic_capable = False
    verified = False

    def __init__(self, pixels_per_byte: int, extended_flag: int, name: str) -> None:
        self.pixels_per_byte = pixels_per_byte
        self.bits = 8 // pixels_per_byte
        self.extended_flag = extended_flag
        self.name = name
        self.note = (f"{pixels_per_byte} px/byte ({self.bits} bpp); "
                     "packing is a best-effort guess, bench-verify.")

    def encode(self, frame, *, start_color=None):
        bits = self.bits
        maxv = (1 << bits) - 1
        ppb = self.pixels_per_byte
        vals = [(min(int(v), 15) * maxv) // 15 for v in frame.stream()]
        out = bytearray()
        for i in range(0, len(vals), ppb):
            byte = 0
            for j in range(ppb):
                v = vals[i + j] if i + j < len(vals) else 0
                byte |= (v & maxv) << (8 - bits * (j + 1))
            out.append(byte & 0xFF)
        return EncodedImage(bytes(out), 1)


class HalfByteStuffed2Encoding(HalfByteEncoding):
    """``HalfByte + StuffedByte_2`` — combined type (placeholder = HalfByte)."""

    def __init__(self) -> None:
        self.name = "halfbyte_stuffed_2"
        self.extended_flag = 0x9
        self.verified = False
        self.note = ("Placeholder = HalfByte; the real 'HalfByte + StuffedByte_2' "
                     "combination is unmapped. Bench-verify.")


class StuffedByte2RgbEncoding(HalfByteRgbEncoding):
    """``StuffedByte_2 RGB`` — packed RGB (placeholder = HalfByte RGB)."""

    def __init__(self) -> None:
        self.name = "stuffed_byte_2_rgb"
        self.extended_flag = 0xA
        self.verified = False
        self.note = ("Placeholder = HalfByte RGB; real StuffedByte_2 RGB packing "
                     "unmapped. Bench-verify.")


class RgbStatic4x4Encoding(Encoding):
    """``RGB statyczne 4x4`` — one (block-averaged) RGB colour per 4x4 tile."""

    name = "rgb_static_4x4"
    color_mode = ColorMode.RGB
    controllers = frozenset({CTRL_LPC})
    classic_capable = False
    extended_flag = 0xB
    verified = False
    note = "One RGB colour per 4x4 tile (averaged); tile order/packing bench-verify."

    def encode(self, frame, *, start_color=None):
        w, h = frame.width, frame.height
        tiles_x = (w + 3) // 4
        tiles_y = (h + 3) // 4
        out = bytearray()
        for tx in range(tiles_x):
            for ty in range(tiles_y - 1, -1, -1):  # bottom-to-top, column-major
                rs = gs = bs = n = 0
                for dx in range(4):
                    for dy in range(4):
                        x, y = tx * 4 + dx, ty * 4 + dy
                        if x < w and y < h:
                            r, g, b = frame.pixels[x][y]
                            rs += r; gs += g; bs += b; n += 1
                n = n or 1
                out += bytes((rs // n, gs // n, bs // n))
        return EncodedImage(bytes(out), 1)


# --------------------------------------------------------------------- registry
def _build_registry() -> Dict[str, Encoding]:
    encs = [
        BitmapEncoding(),                                   # 8051 + LPC, mono, verified
        NibbleRleEncoding(),                                # 8051 + LPC, mono, verified
        BitmapEncoding(name="prosta", controllers=frozenset({CTRL_LPC}),
                       extended_flag=0x1),                  # LPC alias of bitmap (type 1)
        ProstaRbitEncoding(),
        ProstaRgbEncoding(),
        HalfByteEncoding(),
        HalfByteRgbEncoding(),
        StuffedByteEncoding(2, 0x6, "stuffed_byte_2"),
        StuffedByteEncoding(3, 0x7, "stuffed_byte_3"),
        StuffedByteEncoding(4, 0x8, "stuffed_byte_4"),
        HalfByteStuffed2Encoding(),
        StuffedByte2RgbEncoding(),
        RgbStatic4x4Encoding(),
    ]
    return {e.name: e for e in encs}


ALL_ENCODINGS: Dict[str, Encoding] = _build_registry()


def get_encoding(name: Union[str, Encoding]) -> Encoding:
    """Resolve an encoding by name (or pass an :class:`Encoding` through)."""
    if isinstance(name, Encoding):
        return name
    try:
        return ALL_ENCODINGS[name]
    except KeyError:
        raise KeyError(f"unknown encoding {name!r}; "
                       f"available: {sorted(ALL_ENCODINGS)}") from None


def encodings_for(controller: str) -> Dict[str, Encoding]:
    """All registered encodings supported by *controller*."""
    return {n: e for n, e in ALL_ENCODINGS.items() if controller in e.controllers}
