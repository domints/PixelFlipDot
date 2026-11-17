"""pixel_renderer — build PIXEL ``DDB`` image blocks from PIL images.

Turns a PIL image (or a :class:`Frame`) into ready-to-send ``DDB`` block hex for the
PIXEL flip-dot / LED matrix controllers reverse-engineered in ``findings/``:

* :class:`Pixel8051Renderer`   — mono ``PIXEL-SIMS`` (bitmap / nibble-RLE, no scroll)
* :class:`PixelLPC1768Renderer` — colour LPC1768 (all encodings + scroll/animation)

Quick start::

    from PIL import Image
    from pixel.renderer import Pixel8051Renderer

    r = Pixel8051Renderer(width=112, height=16)
    block = r.render_image(Image.open("hello.png"), encoding="nibble_rle", page=0)
    # plug into your driver (e.g. PythonPixelBydgoszcz/pixel.py):
    #   px.display_data_block(0, block.to_hex())

See ``pixel_renderer/README.md`` for the full API and confidence notes.
"""
from __future__ import annotations

from .crc import crc16_ccitt
from .ddb import BlockHeader, DDBBlock, SubImage, blocks_to_hex
from .encodings import (ALL_ENCODINGS, CTRL_8051, CTRL_LPC, BitmapEncoding,
                        EncodedImage, Encoding, HalfByteEncoding,
                        HalfByteRgbEncoding, NibbleRleEncoding, ProstaRbitEncoding,
                        ProstaRgbEncoding, RgbStatic4x4Encoding,
                        StuffedByteEncoding, encodings_for, get_encoding)
from .errors import (GeometryError, PixelRenderError, UnsupportedFeatureError)
from .frame import ColorMode, Frame
from .renderer import (Layer, Pixel8051Renderer, PixelLPC1768Renderer,
                       PixelRenderer)

__all__ = [
    "PixelRenderer",
    "Pixel8051Renderer",
    "PixelLPC1768Renderer",
    "Layer",
    "Frame",
    "ColorMode",
    "BlockHeader",
    "SubImage",
    "DDBBlock",
    "blocks_to_hex",
    "Encoding",
    "EncodedImage",
    "BitmapEncoding",
    "NibbleRleEncoding",
    "ProstaRbitEncoding",
    "ProstaRgbEncoding",
    "HalfByteEncoding",
    "HalfByteRgbEncoding",
    "StuffedByteEncoding",
    "RgbStatic4x4Encoding",
    "ALL_ENCODINGS",
    "get_encoding",
    "encodings_for",
    "crc16_ccitt",
    "PixelRenderError",
    "GeometryError",
    "UnsupportedFeatureError",
    "CTRL_8051",
    "CTRL_LPC",
]
