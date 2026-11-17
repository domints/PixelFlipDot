"""Serialisers for a PIXEL ``DDB`` block (block header + sub-images + CRC).

Layout is the reverse-engineered one from ``findings/ddb-format.md`` (8051, fully
confirmed) and ``findings/lpc1768.md`` (LPC1768 extended header). The output of
:meth:`DDBBlock.to_hex` is the ASCII-hex string you pass straight to the reference
driver's ``display_data_block(displayNo, block)``.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Optional

from .crc import crc16_ccitt
from .encodings import Encoding
from .errors import GeometryError, PixelRenderError


@dataclass
class BlockHeader:
    """The 7-byte block header (shared by 8051 and LPC1768).

    The total length and the ``show_now`` bit live in bytes ``[0..1]`` and are
    filled in by :meth:`DDBBlock.to_bytes`.
    """

    page: int = 0
    dwell: int = 3
    timebase: int = 1          # 0 = ~10 ms ticks, 1 = ~seconds, 2 = ~minutes
    show_now: bool = True      # display this page immediately
    background: int = 0        # background fill colour (flags bit3)
    hide: bool = False         # store but do not display (flags bit4)

    def to_bytes(self, image_count: int) -> bytes:
        if not 0 <= self.page <= 0xFF:
            raise GeometryError(f"page must be 0..255, got {self.page}")
        if self.timebase not in (0, 1, 2):
            raise GeometryError("timebase must be 0 (ticks), 1 (~s) or 2 (~min)")
        if not 0 <= self.dwell <= 0xFF:
            raise GeometryError(f"dwell must be 0..255, got {self.dwell}")
        if not 1 <= image_count <= 0x1F:
            raise GeometryError(f"a page holds 1..31 sub-images, got {image_count}")
        b = bytearray(7)
        # [0..1] length + show_now filled later by DDBBlock
        b[2] = self.page
        b[3] = ((self.timebase & 0x03)
                | ((self.background & 1) << 3)
                | ((1 if self.hide else 0) << 4))
        b[4] = self.dwell & 0xFF
        b[5] = 0
        b[6] = image_count & 0x1F
        return bytes(b)


@dataclass
class SubImage:
    """One sub-image: header + already-encoded pixel data.

    ``extended`` selects the LPC1768 15-byte header (16-bit geometry, colour) via
    length-word bit 15; otherwise the 8051-compatible 6-byte classic header is used.
    """

    left: int
    bottom: int
    width: int
    height: int
    encoding: Encoding
    data: bytes
    start_color: int = 1
    invert: bool = False
    extended: bool = False
    window_width: Optional[int] = None   # extended only; defaults to width
    scroll: bool = False                 # extended: hardware scroll (data_w > window)
    scroll_vertical: bool = False        # extended: vertical scroll (byte12 bit7)
    scroll_direction: str = "rtl"        # horizontal only: "rtl" (bit6=0) | "ltr" (bit6=1)
    scroll_rate: int = 40                # extended byte13: 0 = static, >=1 scrolls
                                         # (higher = slightly slower, saturates ~40)

    def to_bytes(self) -> bytes:
        return self._extended_bytes() if self.extended else self._classic_bytes()

    # ------------------------------------------------------------------ classic
    def _classic_bytes(self) -> bytes:
        if not 0 <= self.height <= 0x1F:
            raise GeometryError(
                f"classic header rows(height) must be 0..31, got {self.height}; "
                "use the LPC extended header for taller images")
        if not 0 <= self.width <= 0xFF:
            raise GeometryError(f"classic header width must be 0..255, got {self.width}")
        if not 0 <= self.left <= 0xFF:
            raise GeometryError(f"classic header left must be 0..255, got {self.left}")
        if not 0 <= self.bottom <= 0x7F:
            # firmware reads byte3 & 0x7f as the bottom offset (bit7 = invert)
            raise GeometryError(f"classic header bottom must be 0..127, got {self.bottom}")
        setup = ((self.height & 0x1F)
                 | ((self.start_color & 1) << 5)
                 | ((self.encoding.classic_encoding_bit & 1) << 6))
        part_len = 6 + len(self.data)
        hdr = bytearray(6)
        hdr[0] = part_len & 0xFF
        hdr[1] = (part_len >> 8) & 0x7F              # bit15 = 0 -> classic
        hdr[2] = self.left & 0xFF
        hdr[3] = (self.bottom & 0x7F) | ((1 if self.invert else 0) << 7)
        hdr[4] = setup
        hdr[5] = self.width & 0xFF
        return bytes(hdr) + self.data

    # ----------------------------------------------------------------- extended
    def _extended_bytes(self) -> bytes:
        """LPC1768 15-byte extended header + one segment.

        Verified against the firmware sub-image parser ``0x8EC8`` (Unicorn trace)
        and confirmed live (``DDB E00``). The payload after the 15-byte header is a
        single segment::

            [6B seg descriptor]  blockIdx=0, flags=0, X(u16)=0, Y(u16)=0
            [2B length prefix]   len of the control block that follows (u16 LE)
            [6B control header]  0x80|type, width(u16), height(u16), color(u8)=0
            [pixel bits]

        ``width`` is the *data* width (may exceed the panel); ``window_width`` is the
        on-screen width. Motion happens when ``window_width < width`` (horizontal) /
        ``window_width < height`` (vertical) **and** ``scroll_rate >= 1`` (byte13).
        Flag byte12 bit6 selects the horizontal **direction** (0 = RTL, 1 = LTR);
        bit7 switches to vertical scrolling (see the CORRECTION in
        ``findings/lpc1768.md``).
        """
        type_nibble = self.encoding.extended_flag
        if type_nibble is None:
            raise PixelRenderError(
                f"encoding {self.encoding.name!r} has no extended type selector; "
                "it cannot be sent in the LPC extended header")
        for label, v in (("left", self.left), ("bottom", self.bottom),
                         ("width", self.width), ("height", self.height)):
            if not 0 <= v <= 0xFFFF:
                raise GeometryError(f"extended {label} must be 0..65535, got {v}")
        window = self.window_width if self.window_width is not None else self.width

        # one segment: descriptor + length-prefixed typed control block + bits
        seg_desc = bytes([0, 0]) + struct.pack("<HH", 0, 0)   # idx, flags, X, Y
        control = (bytes([0x80 | (type_nibble & 0x0F)])
                   + struct.pack("<HH", self.width & 0xFFFF, self.height & 0xFFFF)
                   + bytes([0]))                               # color/reserved = 0
        block = control + self.data
        segment = seg_desc + struct.pack("<H", len(block)) + block

        flags = type_nibble & 0x0F
        if self.scroll:
            if self.scroll_vertical:
                flags |= 0x80                                 # bit7 = vertical scroll
            elif self.scroll_direction == "ltr":
                flags |= 0x40                                 # bit6 = horizontal LTR
            # horizontal RTL = bit6 clear (the default)

        part_len = 15 + len(segment)
        hdr = bytearray(15)
        struct.pack_into("<H", hdr, 0, (part_len & 0x7FFF) | 0x8000)  # bit15 -> extended
        struct.pack_into("<H", hdr, 2, self.left & 0xFFFF)
        struct.pack_into("<H", hdr, 4, self.bottom & 0xFFFF)
        struct.pack_into("<H", hdr, 6, self.width & 0xFFFF)          # data width
        struct.pack_into("<H", hdr, 8, self.height & 0xFFFF)
        struct.pack_into("<H", hdr, 10, window & 0xFFFF)            # on-screen window
        hdr[12] = flags & 0xFF
        # byte13 = scroll rate: 0 = static, >=1 scrolls (higher = slightly slower,
        # saturates ~40). Only meaningful when the scroll bit is set.
        hdr[13] = (self.scroll_rate & 0xFF) if self.scroll else 0
        hdr[14] = 1                                                 # segment count
        return bytes(hdr) + segment


class DDBBlock:
    """A complete ``DDB`` block = one page: header + N sub-images + trailing CRC."""

    def __init__(self, header: BlockHeader, images: List[SubImage], *,
                 max_block: int = 8191) -> None:
        self.header = header
        self.images = list(images)
        self.max_block = max_block

    def to_bytes(self) -> bytes:
        if not self.images:
            raise PixelRenderError("a DDB block needs at least one sub-image")
        body = bytearray(self.header.to_bytes(len(self.images)))
        for image in self.images:
            body += image.to_bytes()
        total = len(body) + 2  # + 2 CRC bytes
        if total > self.max_block:
            raise GeometryError(
                f"block is {total} bytes but the controller limit is {self.max_block}. "
                "Reduce the image size / frame count or split across pages.")
        body[0] = total & 0xFF
        body[1] = ((total >> 8) & 0x1F) | ((1 << 7) if self.header.show_now else 0)
        crc = crc16_ccitt(bytes(body))
        return bytes(body) + struct.pack("<H", crc)

    def to_hex(self) -> str:
        """ASCII-hex block, ready for ``display_data_block(displayNo, block)``."""
        return self.to_bytes().hex().upper()

    def __len__(self) -> int:
        return len(self.to_bytes())

    def __repr__(self) -> str:
        return (f"<DDBBlock page={self.header.page} "
                f"images={len(self.images)} bytes={len(self)}>")


def blocks_to_hex(blocks: List[DDBBlock]) -> List[str]:
    """Convenience: hex-encode a list of blocks (e.g. from a scroll/animation)."""
    return [b.to_hex() for b in blocks]
