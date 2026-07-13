from pyb import UART


# Stores the most recently received UART1 data.
uart1_read = None


class uart_hub:
    def __init__(self, baudrate=9600):
        # UART1: TX=PB6 (X9), RX=PB7 (X10).
        self.uart1 = UART(1, baudrate)

    def uart1_read(self):
        """Read pending UART1 data and save it in the uart1_read variable."""
        global uart1_read

        if self.uart1.any():
            uart1_read = self.uart1.read()

        return uart1_read
