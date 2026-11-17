# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project tries to adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Additions
* New `pixel.renderer` engine (vendored) builds `DDB` blocks from PIL images for both the
  8051 `PIXEL-SIMS` and LPC1768 controllers: all encodings, tall-image band splitting,
  native hardware scrolling, and page-cycled animation. See `src/pixel/renderer/README.md`.
* `render_composite` is the core layered primitive — a single page can mix static and
  scrolling `Layer`s, each with its own placement, window, direction and rate.
* High-level helpers on `Pixel`: `make_renderer`, `display_image`, `display_composite`,
  `display_scroll`, `display_animation`, `display_slideshow`.
* `display_data_block` now accepts a `DDBBlock` or raw `bytes` as well as an ASCII-hex string.
* Runnable examples (`test/render_examples.py`) and unit tests (`test/test_renderer.py`).

### Updates
* `pillow` is now a core dependency (the renderer builds frames from PIL images); `numpy`
  stays optional (only the deprecated numpy-array paths use it).
* `get_image_part_bitmap` now returns the sub-image bytes (previously returned `None`).
* Rendering internals now delegate to `pixel.renderer`; `get_image_block` remains
  CRC-less so the legacy `create_data_block(...)` → `display_data_block(...)` flow is
  unchanged.

### Deprecations
* Deprecated (still working via the new engine): `get_image_data`, `get_image_block`,
  `get_image_part_bitmap`, `get_image_part_rle`, `rle_add_block`, `get_pixel_val`,
  `create_data_block`, `get_crc16`, `_set_bit`, `_clear_bit`. Prefer the renderer / the
  high-level `display_*` helpers.

## [0.0.5] - 2024-11-23
* Improvement: Reduced timeout to something closer to what display needs to respond, to make it all more responsive in case of problems

## [0.0.4] - 2024-11-14
* Improvement: Remove unnecessary print
* Improvement: pin requirements to specific versions, as PIL already kicked me in the butt

## [0.0.3] - 2024-10-19

### Updates
* Fix: Fix support for displays with other than 16 rows. 

### Additions

### Deprecations
* `get_image_data` - parameter `columns` is not used anymore, function gets this information from the image data itself, since having e.g. 12 rows made this information irrelevant to all other calculations. Probably will remove it in next version or something.

### Contributors to this release