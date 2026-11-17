# pixel.renderer

Build PIXEL **`DDB`** image blocks from PIL images, for both reverse-engineered PIXEL
controllers. The output is the ASCII-hex block string you pass straight to the driver's
`Pixel.display_data_block(displayNo, block)`.

This package is vendored into `pixel-flipdot` as `pixel.renderer`. The old top-level
`pixel_renderer` import still works as a compatibility alias; prefer `pixel.renderer` in new
code, or the high-level `Pixel.display_*` helpers (see the top-level `README.md`).

```python
from PIL import Image
from pixel.renderer import Pixel8051Renderer

r = Pixel8051Renderer(width=112, height=16)
block = r.render_image(Image.open("hello.png"), encoding="nibble_rle", page=0)

# plug into PixelFlipDot / the reference driver:
px.display_data_block(0, block.to_hex())
```

## Architecture

```
PixelRenderer (ABC)                # geometry, encoding resolution, fit checks
├── Pixel8051Renderer             # mono, 6-byte classic header, no scroll
└── PixelLPC1768Renderer          # colour/grey, extended header, scroll + animation

Frame            # PIL/matrix -> native coords (column-major, y=0 bottom)
Encoding (ABC)   # Frame -> packed pixel bytes; how it's selected in the header
  BitmapEncoding, NibbleRleEncoding, ProstaRbitEncoding, ProstaRgbEncoding,
  HalfByteEncoding, HalfByteRgbEncoding, StuffedByteEncoding(x3),
  HalfByteStuffed2Encoding, StuffedByte2RgbEncoding, RgbStatic4x4Encoding
SubImage         # one image: header (classic 6B / extended 15B) + data
BlockHeader      # 7-byte block header (page, dwell, timebase, show-now, bg, hide)
DDBBlock         # header + N sub-images + CRC-16 -> .to_bytes() / .to_hex()
```

Layered API: use the high-level `render_*` methods, or drop down to
`BlockHeader`/`SubImage`/`DDBBlock` for full control over anything `DDB` can express
(multiple stacked sub-images, invert, background fill, hidden pages, dwell/time-base,
show-now, explicit page numbers, classic vs. extended headers).

## Controllers & capabilities

| | `Pixel8051Renderer` | `PixelLPC1768Renderer` |
|---|---|---|
| Colour | mono only | mono / grey4 / RGB (`color_mode=`) |
| Geometry | 8-bit (width ≤255, rows ≤31) | tall images auto-split into composited bands |
| Header | classic 6-byte | classic (verified); extended 15-byte only via `force_extended` (unverified) |
| Max block | 2048 B | 8191 B |
| Composite | `render_composite` (multi-image page) | `render_composite` (multi-image page) |
| Scroll | ✗ (`render_slideshow` page-cycling) | ✓ `render_scroll` / `render_animation` |
| Encodings | `bitmap`, `nibble_rle` | all of them |

## Encodings

Choose with `encoding="..."`. Inspect availability with `renderer.supported_encodings`.

| name | controllers | mode | verified | notes |
|------|-------------|------|:--------:|-------|
| `bitmap` | 8051, LPC | mono | ✅ | 1 bpp, 8 px/byte, MSB-first (LPC `Prosta`) |
| `nibble_rle` | 8051, LPC | mono | ✅ | run-length; 8051's preferred encoding |
| `prosta` | LPC | mono | ✅ | LPC alias of `bitmap` |
| `prosta_rbit` | LPC | mono | ⚠️ | bitmap, reversed bit order |
| `prosta_rgb` | LPC | RGB | ⚠️ | 3 bytes/pixel |
| `halfbyte` | LPC | grey4 | ⚠️ | 4 bpp, 2 px/byte |
| `halfbyte_rgb` | LPC | RGB | ⚠️ | 4 bpp/channel (12-bit) |
| `stuffed_byte_2/3/4` | LPC | grey4 | ⚠️ | N px/byte (packing is a best guess) |
| `halfbyte_stuffed_2` | LPC | grey4 | ⚠️ | placeholder = `halfbyte` |
| `stuffed_byte_2_rgb` | LPC | RGB | ⚠️ | placeholder = `halfbyte_rgb` |
| `rgb_static_4x4` | LPC | RGB | ⚠️ | one colour per 4×4 tile |

**✅ verified** = byte layout confirmed from the firmware / reference driver.
**⚠️ unverified** = framing/CRC/geometry are confirmed, but the exact bit packing and
the extended-header flag-nibble values still need a bench check
(`../findings/ddb-build-guide.md` §6). Using one emits a `warnings.warn` once. The
flag values and packing are easy to override on the `Encoding` instances in
`encodings.py` once you capture a real vendor frame.

## Compositing multiple images — the core primitive (both controllers)

`render_composite` is the core rendering call. Sub-images within one page **composite**
(paint in order; later layers overlay earlier ones), and a page holds at most 31 sub-images
total (bands included), else `GeometryError`. Each `Layer` carries its own placement and
encoding, and — on the LPC1768 — may independently **scroll** (see below). `render_image`
and `render_scroll` are thin wrappers over `render_composite`. Tall (>31-row) static layers
are assembled from stacked bands internally, so you never touch "segments" for a plain image.

```python
from pixel.renderer import PixelLPC1768Renderer, Layer

r = PixelLPC1768Renderer(width=96, height=36)
block = r.render_composite([
    Layer(hskrk, left=6, bottom=0),    # bottom of the panel
    Layer(papa,  left=6, bottom=20),   # top of the panel
], encoding="nibble_rle")              # (encoding can also be per-Layer)
px.display_data_block(0, block.to_hex())
```

A layer entry can be a `Layer`, a dict of its fields, or an `(image, left, bottom)`
tuple. See `../../../../send_composite.py` for a runnable end-to-end example.

## Scrolling (LPC1768 only) — native hardware scroll, per layer

The LPC1768 scrolls **in hardware**: a scrolling layer is uploaded as a single wide
**extended** sub-image whose data is larger than its on-screen `window_width`, and the
firmware pans the window across it automatically (verified live, `DDB E00`). It is *not*
page cycling. Because scrolling is a per-sub-image property, a single page can mix static
and scrolling layers.

```python
from pixel.renderer import PixelLPC1768Renderer, Layer

r = PixelLPC1768Renderer(width=96, height=36, color_mode=ColorMode.MONO)

# convenience wrapper for a single scrolling image (wide -> scrolls):
blocks = r.render_scroll(wide_image, encoding="nibble_rle", direction="rtl")
px.display_data_block(0, blocks[0].to_hex())

# or mix a static logo with a message scrolling above it in ONE page:
block = r.render_composite([
    Layer(logo, left=0, bottom=0),                                   # static
    Layer(message, bottom=20, scroll=True, scroll_direction="rtl"),  # scrolling
], encoding="nibble_rle")
px.display_data_block(0, block.to_hex())
```

Per-layer scroll options (also accepted by `render_scroll`):

- `scroll=True` — make this layer a wide, windowed, scrolling extended sub-image.
- `scroll_direction` — `"rtl"` (flag bit6 = 0) or `"ltr"` (bit6 = 1). Both vendor-attested.
- `scroll_vertical=True` — vertical scroll (flag bit7); horizontal is bench-verified,
  vertical is decoded from firmware but not yet bench-confirmed.
- `scroll_rate` — header byte13; **must be >= 1 to move**. Higher is slightly slower but
  saturates (~40); the base speed is a fixed hardware tick. `dwell`/`timebase` do not affect
  it. For genuinely slow/controllable scrolling the firmware's `WBD` images-per-second path
  is the intended route (not implemented here).
- `window_width` — on-screen window (defaults to the panel width, or height when vertical);
  motion happens when it is smaller than the data dimension.

Only the verified mono decoders scroll (`bitmap` / `nibble_rle`). For discrete frames use
`render_animation([...], fps=...)` (one page per frame, cycled). The 8051 cannot scroll;
a scrolling layer / `render_scroll` raises `UnsupportedFeatureError` — use
`render_slideshow([...])` for slow page-cycling instead.

## Coordinate convention

`Frame` stores `pixels[x][y]` with **y = 0 at the bottom**, matching the firmware's
column-major, bottom-to-top plot cursor. `Frame.from_pil` handles the flip; a lit
mono pixel is `1`. `invert=` flips at load time.

## Notes / decisions

- **Invert** is applied at the frame level (pre-inverted pixels) so it behaves the
  same for classic and extended headers; the classic per-image invert bit is left 0.
- **8051 bitmap** is emitted per spec (MSB-first, no bank swap). The reference driver
  used LSB-first with a panel-specific 16-row bank swap; prefer `nibble_rle` there.
- **Block size** is validated against each controller's limit; oversized RGB frames
  raise `GeometryError` — split across pages/frames.

## Confidence

The 8051 path (bitmap, nibble-RLE, classic header, CRC) is authoritative. For the
LPC1768, the wrapper, page model, both header formats, geometry and CRC are confirmed
from the firmware; the colour/stuffed **bit packings** and extended **flag-nibble**
mapping are the remaining unknowns (marked ⚠️). See `../findings/lpc1768.md` and
`../findings/ddb-build-guide.md`.
```
