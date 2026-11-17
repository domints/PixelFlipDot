# PixelFlipDot
Python package to drive Pixel Bydgoszcz flip-dot displays

![PyPI](https://img.shields.io/pypi/v/pixel-flipdot?label=pypi%20package)
![PyPI - Downloads](https://img.shields.io/pypi/dm/pixel-flipdot)

Install with `pip install pixel-flipdot`

Library in very alpha stage.

For usage look at: [PythonPixelBydgoszcz repo](https://github.com/domints/PythonPixelBydgoszcz)

## Rendering images (`pixel.renderer`)

The image pipeline is now the feature-complete `pixel.renderer` engine (see
[`src/pixel/renderer/README.md`](src/pixel/renderer/README.md) for the full API and the
reverse-engineering confidence notes). It builds `DDB` blocks from PIL images for both
controller generations:

- `Pixel8051Renderer` — mono flip-dot `PIXEL-SIMS` (bitmap / nibble-RLE, page-cycled
  slideshow; no scrolling).
- `PixelLPC1768Renderer` — colour-capable LPC1768: all encodings, tall-image band
  splitting, native hardware **scrolling**, and page-cycled **animation**.

High-level helpers on `Pixel` build and send in one call:

```python
from PIL import Image
from pixel.pixel import Pixel
from pixel.renderer import Layer

px = Pixel(conn); px.open()
r = px.make_renderer("lpc1768", width=96, height=36)      # or "8051"

# a single still image
px.display_image(7, r, Image.open("hello.png"), encoding="nibble_rle")

# a scrolling message
px.display_scroll(7, r, Image.open("wide_message.png"), direction="rtl")

# ONE page mixing a static logo with a message scrolling above it
px.display_composite(7, r, [
    Layer(Image.open("logo.png"), left=0, bottom=0),                     # static
    Layer(Image.open("msg.png"), bottom=20, scroll=True,                 # scrolling
          scroll_direction="rtl", scroll_rate=40),
])
```

`render_composite` is the core primitive: a page composites up to 31 sub-images, and each
`Layer` is independently static or scrolling (with its own placement, window, direction and
rate). `render_image` / `render_scroll` are thin wrappers over it. See runnable examples in
[`test/render_examples.py`](test/render_examples.py).

> On 8051 flip-dot panels prefer `encoding="nibble_rle"` (verified). The renderer emits
> `bitmap` MSB-first per spec, which can differ from the old LSB-first / 16-row bank-swapped
> output on some panels.

### Legacy API

The old rendering methods (`get_image_block`, `get_image_part_bitmap` / `_rle`,
`get_image_data`, `create_data_block`, `get_crc16`, …) still work — they now delegate to
`pixel.renderer` — but are **deprecated** and emit `DeprecationWarning`s. `ImagePartDefinition`
and `RenderType` are unchanged. `display_data_block` now also accepts a `DDBBlock` or raw
`bytes` in addition to an ASCII-hex string.

### Note for meself

To build and upload to pypi do:
`rm -rf build && rm -rf dist && (rm -rf src/*.egg-info || true) && python -m build && python -m twine upload dist/*`

To run scripts in `test` dir you need to run `pip install -e .` in root, it'll create link in venv so it'll know to look ar the `root/src/pixel`
