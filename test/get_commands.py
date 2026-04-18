serial_addr: str | None = None # if waveshare eth
serial_port: int | None = None # if waveshare eth
serial_name: str | None = None # if hw serial
serial_gpio: int | None = None # if hw serial with gpio on rpi

### SETUP

display_no: int = 7

serial_addr = "10.12.10.196"
#serial_addr = "10.42.76.80" # if waveshare eth
serial_port = 4196 # if waveshare eth

### END SETUP ^

import sys
sys.path.insert(1, '../src')
from hwserial import HwSerial
from pixel import Pixel
from serialbase import SerialConnector
from waveshareeth import WaveshareEthernet

serial: SerialConnector = None
if serial_addr is not None and serial_port is not None:
    serial = WaveshareEthernet((serial_addr, serial_port))
else:
    serial = HwSerial(serial_name, serial_gpio)

pixel = Pixel(serial)
pixel.open()
gid = pixel.get_factory_identification(display_no)

print(gid)