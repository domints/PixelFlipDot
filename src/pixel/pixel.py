from __future__ import annotations
from enum import Enum
import time
import struct
import warnings
from typing import NamedTuple
try:
    from warnings import deprecated
except ImportError:
    def deprecated(msg=""):
        def _wrap(func):
            return func
        return _wrap

from pixel.serialbase import SerialConnector

# The rendering engine now lives in pixel.renderer (see pixel/renderer/README.md).
# These are the building blocks the legacy shim + new high-level API delegate to.
from pixel.renderer import (BlockHeader, ColorMode, DDBBlock, Frame, Layer,
                            Pixel8051Renderer, PixelLPC1768Renderer, PixelRenderer,
                            blocks_to_hex, crc16_ccitt, get_encoding)
from pixel.renderer.ddb import SubImage
from pixel.renderer.errors import UnsupportedFeatureError

# Pillow is a core dependency (pixel.renderer builds frames from PIL images); numpy is
# optional and only used by the deprecated numpy-array code paths.
try:
    from PIL import Image
except ModuleNotFoundError:
    Image = None
try:
    import numpy as np
except ModuleNotFoundError:
    np = None
noImages = Image is None


def _warn_deprecated(msg: str) -> None:
    """Emit a DeprecationWarning at the caller's call site.

    Complements the ``@deprecated`` decorator so the warning also fires on Python
    versions where ``warnings.deprecated`` is unavailable (the no-op fallback above).
    """
    warnings.warn(msg, DeprecationWarning, stacklevel=3)

class RenderType(Enum):
    Bitmap = 0
    RunLengthEncoding = 1

class ImagePartDefinition(NamedTuple):
    image: np.ndarray | Image.Image
    invert: bool = False
    offsetFromLeft: int = 0
    offsetFromBottom: int = 0
    renderAs: RenderType = RenderType.RunLengthEncoding

class Pixel:
    base_full = bytes.fromhex('B7000001010001AE0000003054')
    def __init__(self, serialPort: SerialConnector) -> None:
        self.serial = serialPort

    def open(self) -> bool:
        return self.serial.open()

    def send_command(self, displayNo: int, command: str) -> bool:
        if displayNo < 0 or displayNo > 15:
            raise ValueError('Display number is out of supported range (0-15)')
        self.serial.send_space()
        time.sleep(0.05)
        self.serial.write(b'_')
        self.serial.write(bytes([0x01]))
        self.serial.write(b'2')
        self.serial.write(b'%X' % displayNo)
        self.serial.write(command.encode('utf-8'))
        self.serial.write(b'\r\n')
        self.serial.write(bytes([0x04]))
        self.serial.flush()

    def read_response(self, timeout: float = 0.25) -> bytes:
        orig_timeout = self.serial.get_timeout()
        self.serial.set_timeout(timeout)
        result = self.serial.read_until(bytes([0x04]))
        self.serial.set_timeout(orig_timeout)
        return result
    
    def check_response(self, response: bytes, displayNo: int) -> str | None:
        if displayNo < 0 or displayNo > 15:
            raise ValueError('Display number is out of supported range (0-15)')
        startIx = response.index(0x02)
        displayNoTxt = '%X' % displayNo
        if chr(response[startIx + 2]) != displayNoTxt:
            return None
        
        errCode = int(response[startIx + 8:startIx + 10].decode(), base=16)
        if errCode != 0:
            if errCode == 0x06:
                raise ValueError('Checksum error!')
            else:
                raise ValueError('Display returned error 0x{:2x}'.format(errCode))
        
        return response[startIx + 11:-1].decode()
    
    def read_string_command(self, displayNo: int, command: str) -> str:
        self.send_command(displayNo, command)
        respString: str = None
        while respString is None:
            responseBytes = self.read_response(timeout=5.0)
            respString = self.check_response(responseBytes, displayNo)
        return respString

    def set_validators_block(self, blocked: bool) -> None:
        for i in range(0, 3):
            self.serial.send_dbl_space()
            self.serial.write(b'__\x0100BLK')
            if blocked:
                self.serial.write(b'01F1\r\n\x04')
            else:
                self.serial.write(b'0071\r\n\x04')

        self.serial.flush()


    def get_factory_identification(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, '#FI')
    
    def get_gid(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, 'GID')
    
    def get_did(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, 'DID')
    
    def get_available_commands(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, '#LC')
    
    def get_light_sensor(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, 'GLS')
    
    def get_device_status(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, 'GDS')
    
    def run_test(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, '#TT')
    
    def run_display_show(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, '#DS')
    
    def get_temperature(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, '#TM')
    
    def get_product_information(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, "PII")
    
    def set_one_pixel(self, displayNo: int, x: int, y: int, value: bool) -> None:
        '''Lol, doesn't work'''
        self.send_command(displayNo, 'SPX {:2x} {:2x} {:2x}'.format(x, y, (1 if value else 0)))
        resp = self.read_response()
        self.check_response(resp, displayNo)

    def set_whole_matrix(self, displayNo: int, value: bool) -> None:
        self.send_command(displayNo, 'SMX {}'.format(1 if value else 0))
        resp = self.read_response()
        self.check_response(resp, displayNo)

    def display_data_block(self, displayNo: int, block) -> None:
        """Send a ready DDB block to the display.

        ``block`` may be a :class:`~pixel.renderer.ddb.DDBBlock` (from the renderer),
        an ASCII-hex ``str`` (as produced by :meth:`create_data_block` / ``to_hex()``),
        or raw ``bytes``/``bytearray`` (hex-encoded here). The block must already carry
        its trailing CRC-16.
        """
        if hasattr(block, "to_hex"):
            block = block.to_hex()
        elif isinstance(block, (bytes, bytearray)):
            block = bytes(block).hex().upper()
        self.send_command(displayNo, 'DDB {}'.format(block))
        resp = self.read_response(1.0)
        self.check_response(resp, displayNo)

    @deprecated("Use pixel.renderer.crc16_ccitt instead.")
    def get_crc16(self, data: bytes):
        """Deprecated: use :func:`pixel.renderer.crc16_ccitt` (identical algorithm)."""
        _warn_deprecated("Pixel.get_crc16 is deprecated; use "
                         "pixel.renderer.crc16_ccitt instead.")
        if data is None:
            return 0
        return crc16_ccitt(bytes(data))

    @deprecated("The renderer appends the CRC itself; use DDBBlock.to_hex() instead.")
    def create_data_block(self, data: bytes) -> str:
        """Deprecated: append a CRC-16 and hex-encode a raw block body.

        The new pipeline builds complete blocks with their CRC already included; call
        ``DDBBlock.to_hex()`` (or :func:`pixel.renderer.blocks_to_hex`) instead. Kept so
        the legacy ``create_data_block(get_image_block(...))`` flow keeps working.
        """
        _warn_deprecated("Pixel.create_data_block is deprecated; the renderer appends "
                         "the CRC itself - use DDBBlock.to_hex() instead.")
        crc = crc16_ccitt(bytes(data))
        datastr = bytes(data).hex().upper()
        crcstr = struct.pack('<H', crc).hex().upper()
        return datastr + crcstr
    
    # ------------------------------------------------------------------ rendering
    # The rendering pipeline now lives in pixel.renderer. The methods below either
    # delegate to it (get_image_block / get_image_part_*) or are kept, deprecated, for
    # backwards compatibility. Prefer the high-level helpers further down
    # (render_image / display_image / display_composite / display_scroll / ...).

    def _compat_frame(self, image, invert: bool = False) -> Frame:
        """Convert a legacy image argument (PIL image, numpy array, or Frame) to a
        renderer :class:`~pixel.renderer.frame.Frame`.

        Uses ``threshold=1`` so any non-zero pixel counts as lit, matching the old
        ``get_pixel_val`` (``> 0``) behaviour rather than a mid-grey cut-off.
        """
        if isinstance(image, Frame):
            return image
        if image is None:
            raise ValueError("You need to pass either a numpy array or a PIL Image object")
        if np is not None and isinstance(image, np.ndarray):
            arr = image
            if arr.dtype == bool:
                arr = arr.astype("uint8") * 255
            if Image is None:
                raise ModuleNotFoundError("Pillow is required to render images.")
            image = Image.fromarray(arr)
        return Frame.from_pil(image, ColorMode.MONO, threshold=1, invert=invert)

    @staticmethod
    def _compat_encoding(render_as: "RenderType") -> str:
        return "bitmap" if render_as == RenderType.Bitmap else "nibble_rle"

    @deprecated("Use pixel.renderer.Frame.from_pil for pixel/threshold handling.")
    def get_pixel_val(self, pxl_raw, invert: bool = False):
        """Deprecated: superseded by Frame.from_pil threshold/invert handling."""
        _warn_deprecated("Pixel.get_pixel_val is deprecated; use "
                         "pixel.renderer.Frame.from_pil instead.")
        try:
            v = pxl_raw[0]
        except (TypeError, IndexError, KeyError):
            v = pxl_raw
        if isinstance(v, bool):
            v = 1 if v else 0
        return (v > 0) if not invert else (v == 0)

    @deprecated("Use Pixel.display_image / renderer.render_image instead.")
    def get_image_data(self, imageData=None, imageObj=None, invert: bool = False,
                       page: int = 0, columns: int = 84):
        '''Deprecated legacy "type A" image block. Use render_image / display_image.

        Kept for backwards compatibility only; some displays never understood this
        format (see the original note).
        '''
        _warn_deprecated("Pixel.get_image_data is deprecated and produces the legacy "
                         "type-A block; use Pixel.display_image / render_image instead.")
        if noImages:
            raise ModuleNotFoundError("No image-related modules found. Please install Numpy and PIL.")
        if page > 0xff:
            raise ValueError("You can only fit one byte in screen ID, I think...")
        if imageData is None and imageObj is None:
            raise ValueError("You need to pass either numpy array or PIL Image object")
        if imageData is None:
            imageData = np.asarray(imageObj)
        imgHeight = len(imageData)
        if imgHeight == 0:
            raise ValueError("You can't have no pixels.")
        imgWidth = len(imageData[0])
        if imgWidth == 0:
            raise ValueError("You can't have no pixels in rows.")
        pixelCount = imgHeight * imgWidth
        byteCount = int(pixelCount / 8) + (1 if pixelCount % 8 > 0 else 0)
        img = bytearray(b'\x00' * byteCount)
        for i in range(0, pixelCount):
            byteIx = int(i / 8)
            bitIx = 7 - int(i % 8)
            column = int(i / imgHeight)
            row = (imgHeight - 1) - int(i % imgHeight)
            pxl = True
            if row < len(imageData) and column < len(imageData[row]):
                pxl_dt = imageData[row][column]
                try:
                    v = pxl_dt[0]
                except (TypeError, IndexError, KeyError):
                    v = pxl_dt
                pxl = (v > 0) if not invert else (v == 0)
            if pxl:
                img[byteIx] |= (1 << bitIx)
            else:
                img[byteIx] &= ~(1 << bitIx)
        base = bytearray(self.base_full)
        dataSize = byteCount
        crcSize = 2
        firstHdrSize = 13
        secondHdrSize = 6
        setupByte = 0b00100000 | (imgHeight & 0x1F)
        base[0] = dataSize + crcSize + firstHdrSize
        base[7] = secondHdrSize + dataSize
        base[2] = page
        base[11] = setupByte
        base[12] = imgWidth
        return base + img

    @deprecated("Use Pixel.display_composite / renderer.render_composite instead.")
    def get_image_block(self, images: "list[ImagePartDefinition]", page: int = 0):
        """Build a classic DDB page from :class:`ImagePartDefinition` layers.

        Backwards-compatible shim: delegates to :mod:`pixel.renderer` (verified encoders)
        and returns the block **without** the trailing CRC, so the legacy
        ``create_data_block(get_image_block(...))`` -> ``display_data_block`` flow keeps
        working unchanged. Prefer :meth:`display_composite` / ``render_composite`` in new
        code.
        """
        _warn_deprecated("Pixel.get_image_block is deprecated; use "
                         "Pixel.display_composite / renderer.render_composite instead.")
        if len(images) == 0:
            raise ValueError("You need to pass at least one image, either numpy array or PIL Image object")
        if page > 16:
            raise ValueError("You can only fit one byte in screen ID, I think...")
        subs = []
        for imgPart in images:
            enc = get_encoding(self._compat_encoding(imgPart.renderAs))
            frame = self._compat_frame(imgPart.image, imgPart.invert)
            encoded = enc.encode(frame)
            subs.append(SubImage(left=imgPart.offsetFromLeft,
                                 bottom=imgPart.offsetFromBottom,
                                 width=frame.width, height=frame.height,
                                 encoding=enc, data=encoded.data,
                                 start_color=encoded.start_color, extended=False))
        # timebase=1, dwell=3, show_now=False reproduce the previous header "magic" bytes
        # (0x01, 0x03) and leave the length + CRC to create_data_block.
        header = BlockHeader(page=page, dwell=3, timebase=1, show_now=False)
        block = DDBBlock(header, subs, max_block=Pixel8051Renderer.max_block)
        return bytearray(block.to_bytes()[:-2])

    @deprecated("Use a Layer with encoding='bitmap' via render_composite instead.")
    def get_image_part_bitmap(self, imageData, invert: bool = False,
                              offsetFromLeft: int = 0, offsetFromBottom: int = 0) -> bytearray:
        """Return one classic **bitmap** sub-image (header + data), via the renderer.

        Fixes the original (which returned ``None``). Prefer ``render_composite`` /
        :class:`~pixel.renderer.renderer.Layer` in new code.
        """
        _warn_deprecated("Pixel.get_image_part_bitmap is deprecated; use a Layer with "
                         "encoding='bitmap' via render_composite instead.")
        enc = get_encoding("bitmap")
        frame = self._compat_frame(imageData, invert)
        encoded = enc.encode(frame)
        sub = SubImage(left=offsetFromLeft, bottom=offsetFromBottom, width=frame.width,
                       height=frame.height, encoding=enc, data=encoded.data,
                       start_color=encoded.start_color, extended=False)
        return bytearray(sub.to_bytes())

    @deprecated("Use a Layer with encoding='nibble_rle' via render_composite instead.")
    def get_image_part_rle(self, imageData, invert: bool = False, page: int = 0,
                           offsetFromLeft: int = 0, offsetFromBottom: int = 0) -> bytearray:
        """Return one classic **nibble-RLE** sub-image (header + data), via the renderer."""
        _warn_deprecated("Pixel.get_image_part_rle is deprecated; use a Layer with "
                         "encoding='nibble_rle' via render_composite instead.")
        enc = get_encoding("nibble_rle")
        frame = self._compat_frame(imageData, invert)
        encoded = enc.encode(frame)
        sub = SubImage(left=offsetFromLeft, bottom=offsetFromBottom, width=frame.width,
                       height=frame.height, encoding=enc, data=encoded.data,
                       start_color=encoded.start_color, extended=False)
        return bytearray(sub.to_bytes())

    @deprecated("Superseded by pixel.renderer NibbleRleEncoding.")
    def rle_add_block(self, buffer: bytearray, currCount: int, currNibble: int) -> int:
        """Deprecated: legacy nibble-RLE run emitter (use NibbleRleEncoding)."""
        _warn_deprecated("Pixel.rle_add_block is deprecated; nibble-RLE is handled by "
                         "pixel.renderer NibbleRleEncoding.")
        addedNibbles = 0
        while currCount > 15:
            currNibble += 1
            currCount -= 15

        if currCount == 0:
            return addedNibbles

        if currNibble % 2 == 0:
            buffer[int(currNibble / 2)] |= (currCount << 4)
        else:
            buffer[int(currNibble / 2)] |= (currCount & 0xf)

        return addedNibbles + 1

    @deprecated("Internal bit helper; no longer used by the render pipeline.")
    def _set_bit(self, value, bit):
        _warn_deprecated("Pixel._set_bit is deprecated and no longer used by the "
                         "render pipeline.")
        return value | (1 << bit)

    @deprecated("Internal bit helper; no longer used by the render pipeline.")
    def _clear_bit(self, value, bit):
        _warn_deprecated("Pixel._clear_bit is deprecated and no longer used by the "
                         "render pipeline.")
        return value & ~(1 << bit)

    # -------------------------------------------------------- high-level rendering
    # Feature-complete API built on pixel.renderer. Create a renderer once (with the
    # panel geometry / controller) and reuse it across calls. Each helper builds the
    # DDB block(s) and sends them via display_data_block.

    @staticmethod
    def make_renderer(controller: str = "lpc1768", width: int = 96, height: int = 36,
                      *, color_mode: ColorMode = ColorMode.MONO) -> PixelRenderer:
        """Create a renderer for a controller family.

        ``controller``: ``"8051"`` (mono flip-dot ``PIXEL-SIMS``) or ``"lpc1768"``
        (colour/scroll-capable). ``color_mode`` only applies to the LPC1768.
        """
        key = controller.lower()
        if key in ("8051", "pixel-sims", "sims", "flipdot"):
            return Pixel8051Renderer(width, height)
        if key in ("lpc1768", "lpc", "xtd"):
            return PixelLPC1768Renderer(width, height, color_mode=color_mode)
        raise ValueError(f"unknown controller {controller!r}; use '8051' or 'lpc1768'")

    def display_image(self, displayNo: int, renderer: PixelRenderer, image, **kwargs) -> DDBBlock:
        """Render a single still image to one page and send it."""
        block = renderer.render_image(image, **kwargs)
        self.display_data_block(displayNo, block)
        return block

    def display_composite(self, displayNo: int, renderer: PixelRenderer, layers, **kwargs) -> DDBBlock:
        """Composite several layers onto one page and send it.

        ``layers`` may mix static and scrolling :class:`~pixel.renderer.renderer.Layer`
        objects (each with its own placement, window, direction and rate); the LPC1768
        renders them as a single page.
        """
        block = renderer.render_composite(layers, **kwargs)
        self.display_data_block(displayNo, block)
        return block

    def display_scroll(self, displayNo: int, renderer: PixelRenderer, image, **kwargs) -> "list[DDBBlock]":
        """Scroll a wide (or tall) image using native hardware scrolling (LPC1768).

        Raises :class:`~pixel.renderer.errors.UnsupportedFeatureError` on the 8051.
        """
        blocks = renderer.render_scroll(image, **kwargs)
        for block in blocks:
            self.display_data_block(displayNo, block)
        return blocks

    def display_animation(self, displayNo: int, renderer: "PixelLPC1768Renderer",
                          images, **kwargs) -> "list[DDBBlock]":
        """Play an explicit frame list as page-cycled animation (LPC1768)."""
        blocks = renderer.render_animation(images, **kwargs)
        for block in blocks:
            self.display_data_block(displayNo, block)
        return blocks

    def display_slideshow(self, displayNo: int, renderer: "Pixel8051Renderer",
                          images, **kwargs) -> "list[DDBBlock]":
        """Page-cycled slideshow (the 8051's closest thing to animation)."""
        blocks = renderer.render_slideshow(images, **kwargs)
        for block in blocks:
            self.display_data_block(displayNo, block)
        return blocks

    def send_sat(self):
        '''Yeah, I don't know what it does either. It looks like it's important before sending table'''
        for i in range(0, 3):
            self.serial.send_dbl_space()
            self.serial.write(b'__\x0101SAT" 1"\r\n\x04')
            self.serial.flush()

    def delete_page(self, displayNo: int, page: str):
        '''Doesn't work unfortunately... yet.'''
        self.send_command(displayNo, 'DPM {}'.format(page))
        resp = self.read_response()
        self.check_response(resp, displayNo)

    def delete_all_pages(self, displayNo: int):
        self.send_sat()
        self.send_sat()
        self.send_sat()
        self.serial.send_space()
        self.serial.write(b'_')
        self.serial.write(bytes([0x01]))
        self.serial.write(b'2')
        self.serial.write(bytes([displayNo + 0x30]))
        self.serial.write('DPM 01FF57'.encode('utf-8'))
        self.serial.write(b'\r\n')
        self.serial.write(bytes([0x04]))
        self.serial.flush()
        resp = self.read_response(timeout=2.0)
        self.check_response(resp, displayNo)
