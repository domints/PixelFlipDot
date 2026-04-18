import serial

from serialbase import SerialConnector

class HwSerial(SerialConnector):
    def __init__(self, portName: str, dePin: int | None = None, baudRate: int = 4800) -> None:
        self.port = portName
        self.baudRate = baudRate
        self.out_driving = False
        if dePin is not None:
            try:
                from gpiozero import DigitalOutputDevice # type: ignore
                from gpiozero.pins.native import NativeFactory # type: ignore
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
        self.serial = serial.Serial(self.portName, self.baudRate, 8, 'E')
        self.serial.timeout = 3
        return self.serial.is_open
    
    def write(self, data: bytes) -> None:
        if not self.out_driving:
            self.beforeWrite()
            self.out_driving = True
        self.serial.write(data)
    
    def read_until(self, expected: bytes):
        return self.serial.read_until(expected)

    def flush(self):
        self.serial.flush()
        self.afterWrite()
        self.out_driving = False

    def gpio_set(self):
        self.dePin.on()
        pass

    def gpio_reset(self):
        self.dePin.off()

    def gpio_null(self):
        pass

    def set_timeout(self, timeout: float):
        self.timeout = timeout
        self.serial.timeout = timeout

    def get_timeout(self):
        return self.serial.timeout