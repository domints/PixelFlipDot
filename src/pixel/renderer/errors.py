"""Exceptions raised by the :mod:`pixel_renderer` package."""


class PixelRenderError(Exception):
    """Base class for every :mod:`pixel_renderer` error."""


class GeometryError(PixelRenderError):
    """An image / block does not fit the target panel or a DDB size limit."""


class UnsupportedFeatureError(PixelRenderError):
    """The selected controller does not support the requested feature/encoding."""
