"""Pixel data in the PIXEL controllers' native coordinate convention.

The firmware plots **column-major, bottom-to-top**: it fills a column of dots from
the bottom upward, then steps one column to the right. :class:`Frame` stores pixels
that way (``pixels[x][y]`` with ``x`` = column from the left and ``y`` = row from the
**bottom**), and :meth:`Frame.stream` yields them in the exact order the encoders and
firmware expect.
"""
from __future__ import annotations

from enum import Enum
from typing import Iterator, List, Sequence, Tuple, Union

Pixel = Union[int, Tuple[int, int, int]]


class ColorMode(Enum):
    """Pixel value domain of a :class:`Frame`."""

    MONO = "mono"     # values 0 / 1            (0 = dark, 1 = lit)
    GRAY4 = "gray4"   # values 0..15            (16 grey levels)
    RGB = "rgb"       # (r, g, b), 0..255 each

    @property
    def channels(self) -> int:
        return 3 if self is ColorMode.RGB else 1


class Frame:
    """One image, normalised to the PIXEL coordinate system.

    Parameters
    ----------
    width, height:
        Dimensions in pixels.
    pixels:
        ``pixels[x][y]`` with ``y = 0`` at the **bottom**. Value type depends on
        *mode* (see :class:`ColorMode`).
    mode:
        The :class:`ColorMode` the values are expressed in.
    """

    __slots__ = ("width", "height", "pixels", "mode")

    def __init__(self, width: int, height: int,
                 pixels: Sequence[Sequence[Pixel]], mode: ColorMode) -> None:
        self.width = width
        self.height = height
        self.pixels = pixels
        self.mode = mode

    # ------------------------------------------------------------------ builders
    @classmethod
    def from_pil(cls, image, mode: ColorMode = ColorMode.MONO, *,
                 threshold: int = 128, invert: bool = False) -> "Frame":
        """Build a :class:`Frame` from a PIL image.

        ``threshold`` is the luminance cut-off for :attr:`ColorMode.MONO`
        (``>= threshold`` -> lit). ``invert`` flips the result (dark<->lit,
        value<->max, colour<->complement).
        """
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError("Pillow is required for Frame.from_pil "
                              "(pip install pillow)") from exc
        if not isinstance(image, Image.Image):
            raise TypeError("image must be a PIL.Image.Image")

        w, h = image.size
        pixels: List[List[Pixel]] = [[0] * h for _ in range(w)]

        if mode is ColorMode.RGB:
            acc = image.convert("RGB").load()
            for x in range(w):
                col = pixels[x]
                for y in range(h):
                    r, g, b = acc[x, y]
                    if invert:
                        r, g, b = 255 - r, 255 - g, 255 - b
                    col[h - 1 - y] = (r, g, b)  # flip so y=0 is bottom
        elif mode is ColorMode.GRAY4:
            acc = image.convert("L").load()
            for x in range(w):
                col = pixels[x]
                for y in range(h):
                    v = acc[x, y] >> 4
                    if invert:
                        v = 15 - v
                    col[h - 1 - y] = v
        else:  # MONO
            acc = image.convert("L").load()
            for x in range(w):
                col = pixels[x]
                for y in range(h):
                    v = 1 if acc[x, y] >= threshold else 0
                    if invert:
                        v ^= 1
                    col[h - 1 - y] = v
        return cls(w, h, pixels, mode)

    @classmethod
    def from_matrix(cls, matrix: Sequence[Sequence[Pixel]],
                    mode: ColorMode = ColorMode.MONO) -> "Frame":
        """Wrap an existing ``matrix[x][y]`` (``y = 0`` bottom) as a :class:`Frame`."""
        width = len(matrix)
        height = len(matrix[0]) if width else 0
        return cls(width, height, matrix, mode)

    @classmethod
    def blank(cls, width: int, height: int, mode: ColorMode = ColorMode.MONO) -> "Frame":
        fill: Pixel = (0, 0, 0) if mode is ColorMode.RGB else 0
        return cls(width, height, [[fill] * height for _ in range(width)], mode)

    # ------------------------------------------------------------------ access
    def stream(self) -> Iterator[Pixel]:
        """Yield pixels in firmware paint order: column-major, **bottom-to-top**.

        The firmware's plot cursor fills each column from the bottom upward, so
        the first pixel of each column (``y = 0`` = bottom) must come first.
        Emitting top-to-bottom here renders the image upside down (verified on
        the LPC XTD36x96). Every encoding reuses this single ordering.
        """
        for x in range(self.width):
            col = self.pixels[x]
            for y in range(self.height):
                yield col[y]

    def window(self, x0: int, width: int, *, wrap: bool = False) -> "Frame":
        """Return a ``width``-wide vertical slice starting at column ``x0``.

        Columns outside ``[0, self.width)`` are filled blank unless ``wrap`` is set,
        in which case they wrap around (useful for looping scrollers).
        """
        blank: Pixel = (0, 0, 0) if self.mode is ColorMode.RGB else 0
        cols: List[Sequence[Pixel]] = []
        for i in range(width):
            sx = x0 + i
            if wrap:
                sx %= self.width
            if 0 <= sx < self.width:
                cols.append(self.pixels[sx])
            else:
                cols.append([blank] * self.height)
        return Frame(width, self.height, cols, self.mode)

    def band(self, y0: int, height: int) -> "Frame":
        """Return a ``height``-tall horizontal band starting at row ``y0`` (``y0`` from
        the **bottom**).

        Used to split an image taller than a classic sub-image's 31-row field into
        stacked bands that the controller composites within one page.
        """
        if y0 < 0 or height <= 0 or y0 + height > self.height:
            raise ValueError(f"band [{y0}:{y0 + height}] out of range for height "
                             f"{self.height}")
        cols = [list(self.pixels[x][y0:y0 + height]) for x in range(self.width)]
        return Frame(self.width, height, cols, self.mode)

    def __repr__(self) -> str:
        return f"<Frame {self.width}x{self.height} {self.mode.value}>"
