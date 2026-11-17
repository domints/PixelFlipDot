"""Runnable examples for the pixel.renderer engine (no serial port needed).

Run with the package importable (``pip install -e .`` in the repo root, or rely on the
sys.path shim below), e.g. ``python test/render_examples.py``. It prints the ``DDB`` block
hex for a few cases; sending is shown in comments.

    from pixel.pixel import Pixel
    px = Pixel(conn); px.open()
    r = px.make_renderer("lpc1768", 96, 36)
    px.display_image(7, r, Image.open("hello.png"))
"""
from __future__ import annotations

import os
import sys

# Allow running straight from the repo without installing.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pixel.renderer import (ColorMode, Frame, Layer, Pixel8051Renderer,
                            PixelLPC1768Renderer, blocks_to_hex)


def checkerboard(width: int, height: int, mode: ColorMode = ColorMode.MONO) -> Frame:
    """Build a Frame without PIL so the demo always runs."""
    px = []
    for x in range(width):
        col = []
        for y in range(height):
            on = (x + y) & 1
            if mode is ColorMode.RGB:
                col.append((255, 0, 0) if on else (0, 0, 64))
            elif mode is ColorMode.GRAY4:
                col.append(15 if on else 2)
            else:
                col.append(on)
        px.append(col)
    return Frame.from_matrix(px, mode)


def box(width: int, height: int) -> Frame:
    px = [[1 if (x in (0, width - 1) or y in (0, height - 1)) else 0
           for y in range(height)] for x in range(width)]
    return Frame.from_matrix(px, ColorMode.MONO)


def demo_8051() -> None:
    print("== 8051 PIXEL-SIMS (112x16, mono) ==")
    r = Pixel8051Renderer(width=112, height=16)
    print("encodings:", r.supported_encodings)
    block = r.render_image(checkerboard(84, 16), encoding="nibble_rle", page=0)
    print("nibble_rle:", block, block.to_hex()[:48], "...")
    show = r.render_slideshow([checkerboard(84, 16), box(84, 16)], dwell=2)
    print("slideshow :", show)


def demo_lpc() -> None:
    print("\n== LPC1768 (96x36) ==")
    r = PixelLPC1768Renderer(width=96, height=36, color_mode=ColorMode.MONO)
    print("encodings:", r.supported_encodings)

    still = r.render_image(checkerboard(96, 36), encoding="nibble_rle", page=0)
    print("still     :", still)

    composite = r.render_composite([
        Layer(box(20, 10), left=0, bottom=0),
        Layer(box(20, 10), left=40, bottom=20),
    ], encoding="nibble_rle")
    print("composite :", composite, "sub-images:", len(composite.images))

    # scroll a 300-wide image through the 96-wide panel
    blocks = r.render_scroll(checkerboard(300, 16), encoding="nibble_rle", direction="rtl")
    print("scroll    :", blocks, "->", blocks_to_hex(blocks)[0][:48], "...")

    # MIXED page: a static box at the bottom + a message scrolling above it
    mixed = r.render_composite([
        Layer(box(20, 10), left=0, bottom=0),                       # static
        Layer(checkerboard(300, 12), bottom=14, scroll=True,        # scrolling
              scroll_direction="ltr", scroll_rate=40),
    ], encoding="nibble_rle")
    kinds = [("scroll" if s.scroll else "static") for s in mixed.images]
    print("mixed page:", mixed, "sub-images:", kinds)

    # page-cycled animation (explicit frames)
    anim = r.render_animation([checkerboard(96, 36), box(96, 36)], fps=10)
    print("animation :", anim)


def main() -> None:
    demo_8051()
    demo_lpc()
    print("\nTo send via the driver:")
    print("    r = px.make_renderer('lpc1768', 96, 36)")
    print("    px.display_composite(7, r, [Layer(logo, bottom=0),")
    print("                                Layer(msg, bottom=20, scroll=True)])")


if __name__ == "__main__":
    main()
