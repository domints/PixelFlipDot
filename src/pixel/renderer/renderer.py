"""High-level renderers: PIL image -> ``DDB`` block(s).

``PixelRenderer`` is the abstract root. Two concrete controllers are provided:

* :class:`Pixel8051Renderer`   — mono flip-dot ``PIXEL-SIMS``; bitmap / nibble-RLE;
  6-byte classic header; **no scrolling** (page-cycled slideshow only).
* :class:`PixelLPC1768Renderer` — colour/grey, all encodings, tall-image band
  splitting, **native hardware scrolling** (a single wide extended sub-image with an
  on-screen window), and page-cycled **animation** (one page per frame).

Note on segments: within one page, multiple sub-images *composite* (overlay) — this is
how images taller than a classic sub-image are assembled from stacked bands, handled
transparently. Explicit multi-frame animation (:meth:`render_animation`) uses one page
per frame, cycled by the controller at the frame's dwell time; it is never a stack of
sub-images in a single page. Continuous scrolling (:meth:`render_scroll`) instead uses
the firmware's native window-over-wide-buffer mechanism in a single page.

All render methods return :class:`~pixel_renderer.ddb.DDBBlock` objects; call
``.to_hex()`` (or :func:`~pixel_renderer.ddb.blocks_to_hex`) and feed the string to
your driver's ``display_data_block(displayNo, block)``.
"""
from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Union

from .ddb import BlockHeader, DDBBlock, SubImage
from .encodings import (CTRL_8051, CTRL_LPC, Encoding, encodings_for,
                        get_encoding)
from .errors import GeometryError, UnsupportedFeatureError
from .frame import ColorMode, Frame


@dataclass
class Layer:
    """One image placed on the panel, for :meth:`PixelRenderer.render_composite`.

    Several layers share a single page and **composite** (paint in list order; later
    layers overlay earlier ones), which is how the controller shows multiple images at
    once. Each layer carries its own placement and encoding options — the same knobs as
    :meth:`PixelRenderer.render_image`.
    """

    image: Any                              # PIL image or Frame
    left: int = 0
    bottom: int = 0
    encoding: Optional[str] = None
    invert: bool = False
    threshold: int = 128
    start_color: Optional[int] = None
    force_extended: bool = False
    window_width: Optional[int] = None
    # --- per-layer scrolling (LPC1768 only) -------------------------------
    # A scrolling layer is uploaded as one wide extended sub-image whose data is
    # larger than its on-screen ``window_width``; the firmware pans the window
    # across it. Static and scrolling layers can be mixed in one page.
    scroll: bool = False
    scroll_vertical: bool = False
    scroll_direction: str = "rtl"           # "rtl" (bit6=0) | "ltr" (bit6=1)
    scroll_rate: int = 40                   # byte13; >=1 to move, saturates ~40


# what render_composite accepts per entry: a Layer, a dict of Layer fields, or an
# (image, left, bottom) tuple for the common case.
LayerLike = Union[Layer, dict, tuple]


def _as_layer(item: LayerLike) -> Layer:
    if isinstance(item, Layer):
        return item
    if isinstance(item, dict):
        return Layer(**item)
    if isinstance(item, (tuple, list)):
        if not 1 <= len(item) <= 3:
            raise ValueError("tuple layer must be (image[, left[, bottom]])")
        image = item[0]
        left = item[1] if len(item) > 1 else 0
        bottom = item[2] if len(item) > 2 else 0
        return Layer(image=image, left=left, bottom=bottom)
    return Layer(image=item)


class PixelRenderer(ABC):
    """Abstract base for a controller-specific DDB renderer."""

    controller: str = ""
    supports_scroll: bool = False
    max_block: int = 8191
    max_pages: int = 256          # page field is 8-bit
    classic_max_rows: int = 31    # classic header rows field is 5-bit
    default_encoding: str = "bitmap"

    def __init__(self, width: int, height: int, *,
                 color_mode: ColorMode = ColorMode.MONO) -> None:
        if width <= 0 or height <= 0:
            raise GeometryError("width and height must be positive")
        self.width = width
        self.height = height
        self.color_mode = color_mode
        self._warned: set = set()

    # -------------------------------------------------------------- introspection
    @property
    def supported_encodings(self) -> List[str]:
        return sorted(encodings_for(self.controller))

    # -------------------------------------------------------------------- helpers
    def _resolve(self, encoding) -> Encoding:
        enc = get_encoding(encoding if encoding is not None else self.default_encoding)
        if self.controller not in enc.controllers:
            raise UnsupportedFeatureError(
                f"encoding {enc.name!r} is not supported by the {self.controller} "
                f"controller; available: {self.supported_encodings}")
        if not enc.verified and enc.name not in self._warned:
            self._warned.add(enc.name)
            warnings.warn(
                f"encoding {enc.name!r} is not fully verified "
                f"({enc.note or 'packing/selector may be wrong'}). "
                "Bench-test before relying on it.",
                stacklevel=3)
        return enc

    def _to_frame(self, image, enc: Encoding, *, invert: bool, threshold: int) -> Frame:
        if isinstance(image, Frame):
            return image
        return Frame.from_pil(image, enc.color_mode, threshold=threshold, invert=invert)

    @abstractmethod
    def _use_extended(self, enc: Encoding, frame: Frame, force_extended: bool) -> bool:
        ...

    def _make_subimage(self, frame: Frame, enc: Encoding, *, left: int, bottom: int,
                       start_color, force_extended: bool,
                       window_width: Optional[int]) -> SubImage:
        encoded = enc.encode(frame, start_color=start_color)
        extended = self._use_extended(enc, frame, force_extended)
        return SubImage(left=left, bottom=bottom, width=frame.width, height=frame.height,
                        encoding=enc, data=encoded.data, start_color=encoded.start_color,
                        invert=False, extended=extended, window_width=window_width)

    def _static_subimages(self, frame: Frame, enc: Encoding, *, left: int, bottom: int,
                          start_color, force_extended: bool,
                          window_width: Optional[int]) -> List[SubImage]:
        """Turn one image into the sub-image(s) that render it as a single still page.

        A classic 6-byte header only carries a 5-bit row count, so an image taller than
        :attr:`classic_max_rows` is split into stacked bands that the controller
        composites within the page (verified on the LPC ``XTD36x96``). The extended
        header (colour/grey or ``force_extended``) always emits a single sub-image.
        """
        if self._use_extended(enc, frame, force_extended):
            return [self._make_subimage(frame, enc, left=left, bottom=bottom,
                                        start_color=start_color,
                                        force_extended=force_extended,
                                        window_width=window_width)]
        subs: List[SubImage] = []
        y = 0
        while y < frame.height:
            h = min(self.classic_max_rows, frame.height - y)
            band = frame.band(y, h)
            subs.append(self._make_subimage(band, enc, left=left, bottom=bottom + y,
                                            start_color=start_color, force_extended=False,
                                            window_width=window_width))
            y += h
        return subs

    def _check_static_fit(self, frame: Frame, left: int, bottom: int) -> None:
        if frame.width > self.width or frame.height > self.height:
            hint = ("Use render_scroll() for over-wide images."
                    if self.supports_scroll
                    else "This controller cannot scroll; resize the image.")
            raise GeometryError(
                f"image {frame.width}x{frame.height} does not fit the "
                f"{self.width}x{self.height} panel. {hint}")
        if left + frame.width > self.width or bottom + frame.height > self.height:
            raise GeometryError("image placement (left/bottom) overruns the panel bounds")

    def _scroll_subimage(self, frame: Frame, enc: Encoding, layer: "Layer") -> SubImage:
        """Build one wide, windowed, scrolling extended sub-image for *layer*.

        Overridden by controllers that support scrolling. The base implementation
        rejects it, so a controller without :attr:`supports_scroll` (e.g. the 8051)
        raises a clear error when a scrolling layer is used.
        """
        raise UnsupportedFeatureError(
            f"the {self.controller} controller does not support scrolling layers")

    # ------------------------------------------------------------------ rendering
    def render_image(self, image, *, encoding=None, page: int = 0, dwell: int = 3,
                     timebase: int = 1, show_now: bool = True, left: int = 0,
                     bottom: int = 0, invert: bool = False, background: int = 0,
                     hide: bool = False, start_color=None, threshold: int = 128,
                     force_extended: bool = False,
                     window_width: Optional[int] = None) -> DDBBlock:
        """Render a single still image to one page.

        Thin convenience wrapper over :meth:`render_composite` with a single static
        :class:`Layer`. The result is one DDB block; images taller than a classic
        sub-image's 31-row field are transparently split into stacked, composited
        bands (no extended header, no user-visible segments).
        """
        layer = Layer(image=image, left=left, bottom=bottom, encoding=encoding,
                      invert=invert, threshold=threshold, start_color=start_color,
                      force_extended=force_extended, window_width=window_width)
        return self.render_composite([layer], page=page, dwell=dwell, timebase=timebase,
                                     show_now=show_now, background=background, hide=hide)

    def render_composite(self, layers: Sequence[LayerLike], *, encoding=None,
                         page: int = 0, dwell: int = 3, timebase: int = 1,
                         show_now: bool = True, background: int = 0,
                         hide: bool = False) -> DDBBlock:
        """Composite several layers onto one page (one DDB block).

        ``layers`` is a list of :class:`Layer` (or dicts / ``(image, left, bottom)``
        tuples). Each is placed at its own ``left``/``bottom`` and the controller paints
        them in order onto the same page — later layers overlay earlier ones. Tall
        static layers still band-split internally. A page holds at most 31 sub-images
        total (bands included), else a :class:`GeometryError` is raised.

        This is the core rendering primitive. A layer with ``scroll=True`` is uploaded
        as a single wide, windowed **extended** sub-image that the firmware pans (LPC1768
        only); static and scrolling layers can be freely mixed in one page. ``encoding``
        is the default applied to any layer that doesn't set its own.

        Example — a static logo at the bottom with a message scrolling above it::

            r.render_composite([
                Layer(logo, left=0, bottom=0),
                Layer(message, bottom=20, scroll=True, scroll_direction="rtl"),
            ])
        """
        if not layers:
            raise GeometryError("render_composite needs at least one layer")
        subs: List[SubImage] = []
        for item in layers:
            layer = _as_layer(item)
            enc = self._resolve(layer.encoding if layer.encoding is not None
                                else encoding)
            frame = self._to_frame(layer.image, enc, invert=layer.invert,
                                   threshold=layer.threshold)
            if layer.scroll:
                subs.append(self._scroll_subimage(frame, enc, layer))
            else:
                self._check_static_fit(frame, layer.left, layer.bottom)
                subs.extend(self._static_subimages(
                    frame, enc, left=layer.left, bottom=layer.bottom,
                    start_color=layer.start_color, force_extended=layer.force_extended,
                    window_width=layer.window_width))
        header = BlockHeader(page=page, dwell=dwell, timebase=timebase,
                             show_now=show_now, background=background, hide=hide)
        return DDBBlock(header, subs, max_block=self.max_block)

    def render_scroll(self, *args, **kwargs) -> List[DDBBlock]:
        raise UnsupportedFeatureError(
            f"the {self.controller} controller does not support scrolling/animation")


class Pixel8051Renderer(PixelRenderer):
    """Mono flip-dot ``PIXEL-SIMS`` (8051). Classic 6-byte header only, no scroll."""

    controller = CTRL_8051
    supports_scroll = False
    max_block = 2048
    default_encoding = "nibble_rle"

    def __init__(self, width: int = 112, height: int = 16) -> None:
        super().__init__(width, height, color_mode=ColorMode.MONO)

    def _use_extended(self, enc, frame, force_extended):
        if force_extended:
            raise UnsupportedFeatureError(
                "the 8051 controller has no extended sub-image header")
        return False

    def render_slideshow(self, images: Sequence, *, encoding=None, dwell: int = 3,
                         timebase: int = 1, start_page: int = 0, **kwargs) -> List[DDBBlock]:
        """One page per image; the panel cycles pages at their dwell time.

        This is the closest the 8051 gets to animation (slow page cycling, not the
        smooth in-page motion the LPC does).
        """
        blocks = []
        for i, img in enumerate(images):
            blocks.append(self.render_image(
                img, encoding=encoding, page=start_page + i, dwell=dwell,
                timebase=timebase, show_now=(i == 0), **kwargs))
        return blocks


class PixelLPC1768Renderer(PixelRenderer):
    """Colour/grey LPC1768 controller: every encoding + scrolling/animation."""

    controller = CTRL_LPC
    supports_scroll = True
    max_block = 8191

    def __init__(self, width: int, height: int, *,
                 color_mode: ColorMode = ColorMode.MONO,
                 default_encoding: Optional[str] = None) -> None:
        super().__init__(width, height, color_mode=color_mode)
        if default_encoding is None:
            default_encoding = {ColorMode.MONO: "bitmap",
                                ColorMode.GRAY4: "halfbyte",
                                ColorMode.RGB: "prosta_rgb"}[color_mode]
        self.default_encoding = default_encoding

    def _use_extended(self, enc, frame, force_extended):
        if force_extended:
            return True
        if not enc.classic_capable:
            return True
        # A classic sub-image carries an 8-bit width; taller-than-31-row images are
        # handled by band-splitting (see _static_subimages), not the extended header,
        # because the classic mono path is the only one verified on hardware so far.
        return frame.width > 0xFF

    @staticmethod
    def _fps_to_dwell(fps: float) -> int:
        # timebase 0 = ~10 ms ticks -> ~100 ticks/second
        return max(1, round(100 / max(1, fps)))

    def _frames_to_blocks(self, frames: Sequence[Frame], enc: Encoding, *, page: int,
                          dwell: int, timebase: int, left: int, bottom: int,
                          background: int, force_extended: bool,
                          window_width: Optional[int]) -> List[DDBBlock]:
        # One page per frame. Multiple sub-images in a single page *composite* (verified
        # on hardware), so they cannot be used as animation frames; motion is produced by
        # the controller cycling pages at their dwell time instead. Each frame may still
        # expand into several composited bands if it is taller than 31 rows.
        if len(frames) > self.max_pages:
            raise GeometryError(
                f"{len(frames)} frames exceed the {self.max_pages}-page limit; "
                "use a larger step / fewer frames")
        blocks: List[DDBBlock] = []
        for i, frame in enumerate(frames):
            subs = self._static_subimages(frame, enc, left=left, bottom=bottom,
                                          start_color=None, force_extended=force_extended,
                                          window_width=window_width)
            header = BlockHeader(page=page + i, dwell=dwell, timebase=timebase,
                                 show_now=(i == 0), background=background)
            blocks.append(DDBBlock(header, subs, max_block=self.max_block))
        return blocks

    def _scroll_subimage(self, frame: Frame, enc: Encoding, layer: Layer) -> SubImage:
        """Build a single wide, windowed, scrolling extended sub-image for *layer*.

        The whole image becomes one off-screen buffer (extended header,
        ``data_width = image width``) with an on-screen ``window`` (defaults to the panel
        width, or panel height when vertical); the firmware pans the window across the
        buffer automatically. Verified live (``DDB E00``, motion confirmed on an
        ``XTD36x96`` panel).

        Firmware facts (see ``findings/lpc1768.md``):

        * ``scroll_rate`` (header byte13) **must be >= 1 to move**; ``0`` loads the buffer
          but leaves it static. Higher values scroll slightly slower but saturate (~40);
          ``dwell``/``timebase`` do not affect it. For slow/controllable scrolling the
          ``WBD`` images-per-second path is the intended route (not implemented here).
        * ``scroll_direction`` selects horizontal motion via flag bit6: ``"rtl"`` (bit6=0)
          or ``"ltr"`` (bit6=1). Both are vendor-attested.
        * Only the verified mono decoders scroll (``bitmap`` / ``nibble_rle``).
        * ``scroll_vertical`` sets the vertical-scroll bit (bit7); horizontal is
          bench-verified, vertical is decoded from firmware but not yet bench-confirmed.
        """
        if enc.extended_flag is None:
            raise UnsupportedFeatureError(
                f"encoding {enc.name!r} cannot be sent in the extended header needed "
                "for native scrolling; use 'bitmap' or 'nibble_rle'")
        if layer.scroll_vertical:
            if frame.width > self.width:
                raise GeometryError(
                    f"vertical scroll needs width <= panel width; "
                    f"got {frame.width}>{self.width}")
            window = layer.window_width if layer.window_width is not None else self.height
            if window > self.height:
                raise GeometryError(
                    f"scroll window {window} exceeds panel height {self.height}")
            if layer.left + frame.width > self.width or layer.bottom + window > self.height:
                raise GeometryError("scroll placement/window overruns the panel bounds")
        else:
            if frame.height > self.height:
                raise GeometryError(
                    f"image height {frame.height} exceeds panel height {self.height}; "
                    "use scroll_vertical=True to scroll vertically instead")
            window = layer.window_width if layer.window_width is not None else self.width
            if window > self.width:
                raise GeometryError(
                    f"scroll window {window} exceeds panel width {self.width}")
            if layer.left + window > self.width or layer.bottom + frame.height > self.height:
                raise GeometryError("scroll placement/window overruns the panel bounds")

        encoded = enc.encode(frame, start_color=None)
        return SubImage(left=layer.left, bottom=layer.bottom, width=frame.width,
                        height=frame.height, encoding=enc, data=encoded.data,
                        start_color=encoded.start_color, extended=True,
                        window_width=window, scroll=True,
                        scroll_vertical=layer.scroll_vertical,
                        scroll_direction=layer.scroll_direction,
                        scroll_rate=layer.scroll_rate)

    def render_scroll(self, image, *, encoding=None, page: int = 0, dwell: int = 3,
                      timebase: int = 1, show_now: bool = True, left: int = 0,
                      bottom: int = 0, invert: bool = False, threshold: int = 128,
                      background: int = 0, hide: bool = False, vertical: bool = False,
                      window_width: Optional[int] = None, scroll_rate: int = 40,
                      direction: str = "rtl") -> List[DDBBlock]:
        """Scroll a wide (or, with ``vertical``, tall) image using **native hardware
        scrolling**.

        Thin convenience wrapper over :meth:`render_composite` with a single scrolling
        :class:`Layer` (see :meth:`_scroll_subimage` for the firmware details). Returns a
        single-element list for API symmetry with the other multi-block renderers. If the
        image already fits on the panel there is nothing to scroll, so a plain static page
        is emitted instead. To combine a scroll with static overlays, build the layers
        yourself and call :meth:`render_composite`.
        """
        enc = self._resolve(encoding)
        if enc.extended_flag is None:
            raise UnsupportedFeatureError(
                f"encoding {enc.name!r} cannot be sent in the extended header needed "
                "for native scrolling; use 'bitmap' or 'nibble_rle'")
        full = self._to_frame(image, enc, invert=invert, threshold=threshold)

        if full.width <= self.width and full.height <= self.height:
            # fits on screen -> nothing to scroll, emit a plain static page
            return [self.render_image(full, encoding=enc, page=page, dwell=dwell,
                                      timebase=timebase, show_now=show_now, left=left,
                                      bottom=bottom, background=background, hide=hide)]

        layer = Layer(image=full, left=left, bottom=bottom, encoding=enc,
                      window_width=window_width, scroll=True, scroll_vertical=vertical,
                      scroll_direction=direction, scroll_rate=scroll_rate)
        return [self.render_composite([layer], page=page, dwell=dwell, timebase=timebase,
                                      show_now=show_now, background=background, hide=hide)]

    def render_animation(self, images: Sequence, *, encoding=None, page: int = 0,
                         fps: float = 15, dwell: Optional[int] = None, timebase: int = 0,
                         left: int = 0, bottom: int = 0, invert: bool = False,
                         threshold: int = 128, background: int = 0,
                         force_extended: bool = False) -> List[DDBBlock]:
        """Play an explicit list of frames as an animation (one page per frame, cycled)."""
        enc = self._resolve(encoding)
        frames = [self._to_frame(im, enc, invert=invert, threshold=threshold)
                  for im in images]
        for f in frames:
            if f.width > self.width or f.height > self.height:
                raise GeometryError(
                    f"a frame is {f.width}x{f.height}, larger than the "
                    f"{self.width}x{self.height} panel")
        if dwell is None:
            dwell = self._fps_to_dwell(fps)
        return self._frames_to_blocks(frames, enc, page=page, dwell=dwell,
                                      timebase=timebase, left=left, bottom=bottom,
                                      background=background,
                                      force_extended=force_extended, window_width=None)
