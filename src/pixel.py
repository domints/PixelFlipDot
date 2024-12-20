import serial
import time
import struct

noImages = False
try:
    import numpy as np
    from PIL import Image
except ModuleNotFoundError:
    noImages = True

class Pixel:
    base_full = bytes.fromhex('B7000001010001AE0000003054')
    def __init__(self, serialPort: str, dePin: int | None = None) -> None:
        self.portName = serialPort
        if dePin is not None:
            try:
                from gpiozero import DigitalOutputDevice
                from gpiozero.pins.native import NativeFactory
            except:
                raise ImportError('To use GPIO (in Rpi?) install gpiozero library')
            self.dePin = DigitalOutputDevice(dePin, pin_factory=NativeFactory())
            self.beforeWrite = self.gpio_set
            self.afterWrite = self.gpio_reset
        else:
            self.beforeWrite = self.gpio_null
            self.afterWrite = self.gpio_null
        pass

    def open(self) -> bool:
        self.serial = serial.Serial(self.portName, 4800, 8, 'E')
        self.serial.timeout = 3
        return self.serial.is_open

    def send_space(self) -> None:
        self.serial.write([0x20, 0x04])
    
    def send_dbl_space(self) -> None:
        self.serial.write([0x20, 0x20, 0x04])

    def send_command(self, displayNo: int, command: str) -> bool:
        if displayNo < 0 or displayNo > 7:
            raise ValueError('Display number is out of supported range (0-7)')
        self.beforeWrite()
        self.send_space()
        time.sleep(0.05)
        self.serial.write(b'_')
        self.serial.write([0x01])
        self.serial.write(b'2')
        self.serial.write(bytes([displayNo + 0x30]))
        self.serial.write(command.encode('utf-8'))
        self.serial.write(b'\r\n')
        self.serial.write([0x04])
        self.serial.flush()
        self.afterWrite()

    def read_response(self, timeout: float = 0.25) -> bytes:
        orig_timeout = self.serial.timeout
        self.serial.timeout = timeout
        result = self.serial.read_until(bytes([0x04]))
        self.serial.timeout = orig_timeout
        return result
    
    def check_response(self, response: bytes, displayNo: int) -> str | None:
        if displayNo < 0 or displayNo > 7:
            raise ValueError('Display number is out of supported range (0-7)')
        startIx = response.index(0x02)
        displayNoTxt = str(displayNo)
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
            responseBytes = self.read_response(timeout=2.0)
            respString = self.check_response(responseBytes, displayNo)
        return respString

    def set_validators_block(self, blocked: bool) -> None:
        self.beforeWrite()
        for i in range(0, 3):
            self.send_dbl_space()
            self.serial.write(b'__\x0100BLK')
            if blocked:
                self.serial.write(b'01F1\r\n\x04')
            else:
                self.serial.write(b'0071\r\n\x04')

        self.serial.flush()
        self.afterWrite()


    def get_factory_identification(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, '#FI')
    
    def get_gid(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, 'GID')
    
    def get_did(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, 'DID')
    
    def get_available_commands(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, '#LC')
    
    def run_test(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, '#TT')
    
    def run_display_show(self, displayNo: int) -> str:
        return self.read_string_command(displayNo, '#DS')
    
    def set_one_pixel(self, displayNo: int, x: int, y: int, value: bool) -> None:
        '''Lol, doesn't work'''
        self.send_command(displayNo, 'SPX {:2x} {:2x} {:2x}'.format(x, y, (1 if value else 0)))
        resp = self.read_response()
        self.check_response(resp, displayNo)

    def set_whole_matrix(self, displayNo: int, value: bool) -> None:
        self.send_command(displayNo, 'SMX {}'.format(1 if value else 0))
        resp = self.read_response()
        self.check_response(resp, displayNo)

    def display_data_block(self, displayNo: int, block: str) -> None:
        self.send_command(displayNo, 'DDB {}'.format(block))
        resp = self.read_response()
        self.check_response(resp, displayNo)

    def get_crc16(self, data: bytes):
        if data is None:
            return 0
        crc = 0x0000
        for i in range(0, len(data)):
            crc ^= data[i] << 8
            for j in range(0,8):
                if (crc & 0x8000) > 0:
                    crc =(crc << 1) ^ 0x1021
                else:
                    crc = crc << 1
        return crc & 0xFFFF
    
    def create_data_block(self, data: bytes) -> str:
        crc = self.get_crc16(data)
        datastr = data.hex().capitalize()
        crcstr = struct.pack('<H', crc).hex().upper()
        return datastr + crcstr
    if not noImages:
        def get_image_data(self, imageData: np.ndarray = None, imageObj: Image = None, invert: bool = False, page: int = 0, columns: int = 84):
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
            byteCount = int(pixelCount / 8) + (1 if pixelCount % 8 > 0 else 0) # byte fits 8 pixels, if doesn't divide cleanly add byte for extra pixels
            img = bytearray(b'\x00'*byteCount)
            for i in range(0, pixelCount):
                byteIx = int(i / 8)
                bitIx = 7 - int(i % 8)
                # if bitIx > 7:
                #     bitIx = bitIx - 8
                column = int(i / imgHeight)
                row = (imgHeight - 1) - int(i % imgHeight)
                # HOW DOES BYTE SWAP WORK WITH NON-INTEGER DISPLAYS?
                # if imgHeight % 8 == 0:
                #     if row > 7:
                #         row = row - 8
                #     else:
                #         row = row + 8
                pxl = 1
                if row < len(imageData) and column < len(imageData[row]):
                        pxl_dt = imageData[row][column]
                        if isinstance(pxl_dt, bool) or isinstance(pxl_dt, np.bool):
                            pxl = 1 if pxl_dt else 0
                        else:
                            pxl = pxl_dt
                try:
                    img[byteIx] = self._set_bit(img[byteIx], bitIx) if (pxl[0] > 0 if not invert else pxl[0] == 0) else self._clear_bit(img[byteIx], bitIx)
                except:
                    img[byteIx] = self._set_bit(img[byteIx], bitIx) if (pxl > 0 if not invert else pxl == 0) else self._clear_bit(img[byteIx], bitIx)
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
    
    def _set_bit(self, value, bit):
        return value | (1<<bit)

    
    def _clear_bit(self, value, bit):
        return value & ~(1<<bit)
    
    def send_sat(self):
        '''Yeah, I don't know what it does either. It looks like it's important before sending table'''
        for i in range(0, 3):
            self.send_dbl_space()
            self.serial.write(b'__\x0101SAT" 1"\r\n\x04')
            self.serial.flush()

    def delete_page(self, displayNo: int, page: str):
        '''Doesn't work unfortunately... yet.'''
        self.send_command(displayNo, 'DPM {}'.format(page))
        resp = self.read_response()
        self.check_response(resp, displayNo)

    def delete_all_pages(self, displayNo: int):
        self.beforeWrite()
        self.send_sat()
        self.send_sat()
        self.send_sat()
        self.send_space()
        self.serial.write(b'_')
        self.serial.write([0x01])
        self.serial.write(b'2')
        self.serial.write(bytes([displayNo + 0x30]))
        self.serial.write('DPM 01FF57'.encode('utf-8'))
        self.serial.write(b'\r\n')
        self.serial.write([0x04])
        self.serial.flush()
        self.afterWrite()
        resp = self.read_response(timeout=2.0)
        self.check_response(resp, displayNo)

    def gpio_set(self):
        self.dePin.on()
        pass

    def gpio_reset(self):
        self.dePin.off()

    def gpio_null(self):
        pass
