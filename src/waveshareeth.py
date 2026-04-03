import socket
import time

from serialbase import SerialConnector

class WaveshareEthernet(SerialConnector):
    def __init__(self, address: tuple[int, int]):
        self.address = address
        self.timeout = 0.25
        self.read_bfr = b''

    def open(self) -> bool:
        self.socket = socket.socket()
        self.socket.settimeout(self.timeout)
        try:
            self.socket.connect(self.address)
            return True
        except:
            return False
    
    def write(self, data: bytes) -> None:
        self.socket.sendall(data)

    def read_until(self, expected: bytes) -> bytes:
        start_time = time.time()
        while expected not in self.read_bfr:
            read_data = self.socket.recv(16)
            self.read_bfr += read_data
            if time.time() - start_time > self.timeout:
                if expected not in self.read_bfr:
                    raise TimeoutError()
                break
            if not read_data:
                time.sleep(self.timeout / 10)
        data,_,self.read_bfr = self.read_bfr.partition(expected)
        return data

    def flush(self):
        pass
    
    def set_timeout(self, timeout: float):
        self.timeout = timeout
        self.socket.settimeout(timeout)

    def get_timeout(self):
        return self.socket.gettimeout()