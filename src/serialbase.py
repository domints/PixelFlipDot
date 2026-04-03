from abc import ABC, abstractmethod

class SerialConnector(ABC):
    @abstractmethod
    def open(self) -> bool:
        pass
    
    @abstractmethod
    def write(self, data: bytes) -> None:
        pass
    
    @abstractmethod
    def flush(self) -> None:
        """
        Ensures all data is sent out. 100% needed for HW serial with GPIO to clear state
        """
        pass
    
    @abstractmethod
    def read_until(self, expected: bytes) -> bytes:
        pass

    @abstractmethod
    def set_timeout(self, timeout: float):
        pass

    @abstractmethod
    def get_timeout(self) -> float:
        pass

    def send_space(self) -> None:
        self.write(bytes([0x20, 0x04]))
    
    def send_dbl_space(self) -> None:
        self.write(bytes([0x20, 0x20, 0x04]))