"""Unit tests for pixel.renderer and the pixel.Pixel rendering shim.

Runnable directly (``python test/test_renderer.py``) or via pytest. No serial port or
hardware is required.
"""
from __future__ import annotations

import os
import struct
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pixel.pixel import ImagePartDefinition, Pixel, RenderType
from pixel.renderer import (ColorMode, Frame, Layer, Pixel8051Renderer,
                            PixelLPC1768Renderer, crc16_ccitt)
from pixel.renderer.errors import UnsupportedFeatureError
from pixel.serialbase import SerialConnector


def _blank(w, h):
    return Frame.blank(w, h, ColorMode.MONO)


# --------------------------------------------------------------- layered scroll API
def test_scroll_layer_is_extended_windowed():
    r = PixelLPC1768Renderer(96, 36, color_mode=ColorMode.MONO)
    block = r.render_composite([Layer(_blank(300, 12), bottom=0, scroll=True)],
                               encoding="nibble_rle")
    assert len(block.images) == 1
    sub = block.images[0]
    assert sub.extended and sub.scroll
    raw = sub.to_bytes()
    data_width = struct.unpack_from("<H", raw, 6)[0]
    window = struct.unpack_from("<H", raw, 10)[0]
    assert data_width == 300 and window == 96          # window < data => scrollable
    assert raw[13] >= 1                                  # byte13 rate must be >=1 to move


def test_scroll_direction_bit6():
    r = PixelLPC1768Renderer(96, 36, color_mode=ColorMode.MONO)
    rtl = r.render_scroll(_blank(300, 16), direction="rtl")[0].images[0].to_bytes()
    ltr = r.render_scroll(_blank(300, 16), direction="ltr")[0].images[0].to_bytes()
    assert rtl[12] & 0x40 == 0                           # RTL => bit6 clear
    assert ltr[12] & 0x40 == 0x40                        # LTR => bit6 set


def test_mixed_static_and_scroll_in_one_page():
    r = PixelLPC1768Renderer(96, 36, color_mode=ColorMode.MONO)
    block = r.render_composite([
        Layer(_blank(20, 10), left=0, bottom=0),                    # static
        Layer(_blank(300, 12), bottom=20, scroll=True),             # scrolling
    ], encoding="nibble_rle")
    assert len(block.images) == 2
    assert (not block.images[0].extended) and (not block.images[0].scroll)   # classic static
    assert block.images[1].extended and block.images[1].scroll               # extended scroll


def test_8051_rejects_scroll_layer():
    e = Pixel8051Renderer(112, 16)
    try:
        e.render_composite([Layer(_blank(300, 16), scroll=True)])
    except UnsupportedFeatureError:
        return
    raise AssertionError("8051 render_composite should reject a scrolling layer")


def test_render_image_and_scroll_are_wrappers():
    r = PixelLPC1768Renderer(96, 36, color_mode=ColorMode.MONO)
    # image that fits -> render_scroll emits a static page
    fits = r.render_scroll(_blank(40, 12))[0]
    assert not fits.images[0].scroll
    # render_image bands a tall image (36 > 31) into two composited classic sub-images
    banded = r.render_image(_blank(96, 36), encoding="nibble_rle")
    assert len(banded.images) == 2 and all(not s.extended for s in banded.images)


# ------------------------------------------------------------------- CRC / shim path
def test_crc_parity():
    data = bytes(range(40))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert Pixel(None).get_crc16(data) == crc16_ccitt(data)


def test_shim_get_image_block_roundtrips_crc():
    px = Pixel(None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        body = px.get_image_block(
            [ImagePartDefinition(_blank(20, 12), renderAs=RenderType.RunLengthEncoding)],
            page=0)
        hexstr = px.create_data_block(body)
    raw = bytes.fromhex(hexstr)
    crc = int.from_bytes(raw[-2:], "little")
    assert crc == crc16_ccitt(raw[:-2])                 # CRC valid over the body
    assert raw[3] == 0x01 and raw[4] == 0x03            # legacy header magic preserved


def test_get_image_part_bitmap_returns_bytes():
    px = Pixel(None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        part = px.get_image_part_bitmap(_blank(16, 8))
    assert isinstance(part, (bytes, bytearray)) and len(part) > 6   # was None before


def test_legacy_methods_emit_deprecation_warnings():
    px = Pixel(None)
    for call in (
        lambda: px.get_image_block([ImagePartDefinition(_blank(8, 8))]),
        lambda: px.create_data_block(b"\x00\x01"),
        lambda: px.get_image_part_rle(_blank(8, 8)),
        lambda: px.get_crc16(b"\x00"),
    ):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            call()
            assert any(issubclass(x.category, DeprecationWarning) for x in w), call


# ------------------------------------------------------------- display_data_block I/O
class _CaptureSerial(SerialConnector):
    def __init__(self):
        self.buf = b""
        self.sent = b""
    def open(self):
        return True
    def write(self, data):
        self.buf += data
    def flush(self):
        self.sent += self.buf
        self.buf = b""
    def read_until(self, expected):
        return b"\x02_2700000000\x04"
    def set_timeout(self, t):
        pass
    def get_timeout(self):
        return 0.25


def test_display_data_block_accepts_ddbblock_str_bytes():
    conn = _CaptureSerial()
    px = Pixel(conn)
    px.open()
    px.check_response = lambda resp, no: "OK"     # accept the minimal fake reply
    r = PixelLPC1768Renderer(96, 36, color_mode=ColorMode.MONO)
    blk = r.render_image(_blank(40, 12), encoding="nibble_rle")
    for form in (blk, blk.to_hex(), blk.to_bytes()):
        conn.sent = b""
        px.display_data_block(7, form)
        assert b"DDB " + blk.to_hex().encode() in conn.sent


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print("\n%d tests passed" % len(fns))


if __name__ == "__main__":
    _run_all()
