"""MicroPython driver for the GY-25Z enhanced inclinometer module.

The module uses a 3.3 V TTL UART interface.  This driver uses the GY-25Z
firmware's UART protocol, not the optional MPU6050 I2C bypass mode.
"""

try:
    from time import ticks_ms, ticks_diff
except ImportError:
    from utime import ticks_ms, ticks_diff


class GY25Z:
    """Read and configure a GY-25Z module through a MicroPython UART."""

    ACC = 0x01
    GYRO = 0x02
    EULER = 0x10
    TEMPERATURE = 0x40

    _HEADER = 0x5A
    _ACC_SCALE = 2.0 / 32767.0
    _GYRO_SCALE = 2000.0 / 32767.0

    def __init__(self, uart, output=ACC | GYRO | EULER | TEMPERATURE):
        """Create a driver using an initialized ``machine.UART`` instance.

        ``output`` is a bitwise combination of ``ACC``, ``GYRO``, ``EULER``
        and ``TEMPERATURE``.  The module normally starts at 115200 baud.
        """
        self.uart = uart
        self._buffer = bytearray()
        self.output = output
        self.bytes_received = 0
        self.frames_received = 0
        self.invalid_frames = 0

    @staticmethod
    def _int16(data, offset):
        value = (data[offset] << 8) | data[offset + 1]
        return value - 65536 if value & 0x8000 else value

    def _command(self, command, value):
        """Send one four-byte command and return the transmitted bytes."""
        packet = bytearray((0xA5, command, value, 0))
        packet[3] = sum(packet[:3]) & 0xFF
        self.uart.write(packet)
        return packet

    def set_output(self, output):
        """Choose which values the module includes in each frame."""
        output &= self.ACC | self.GYRO | self.EULER | self.TEMPERATURE
        self._command(0x55, output)
        self.output = output

    def continuous(self, enabled=True):
        """Enable continuous frames, or select one-frame query mode."""
        self._command(0x56, 0x02 if enabled else 0x01)

    def request(self):
        """Request one frame when query mode has been selected."""
        self.continuous(False)

    def calibrate_accel_gyro(self):
        """Calibrate while the module is level and completely still."""
        self._command(0x57, 0x01)

    def set_baudrate(self, baudrate):
        """Set the next-boot baud rate to 9600 or 115200."""
        values = {115200: 0x01, 9600: 0x02}
        try:
            self._command(0x58, values[baudrate])
        except KeyError:
            raise ValueError("baudrate must be 9600 or 115200")

    def set_rate(self, rate):
        """Set the output rate in Hz: 10, 50, 100, or 200."""
        values = {10: 0x01, 50: 0x02, 100: 0x03, 200: 0x04}
        try:
            self._command(0x59, values[rate])
        except KeyError:
            raise ValueError("rate must be 10, 50, 100, or 200")

    def set_vertical_mode(self, enabled=True):
        """Choose vertical (Y axis up) or horizontal (Z axis up) mode."""
        self._command(0x5B, 0x01 if enabled else 0x02)

    def save(self):
        """Persist the current module settings to its flash memory."""
        self._command(0x5A, 0x01)

    def _decode(self, frame):
        if len(frame) < 5 or frame[0] != self._HEADER or frame[1] != self._HEADER:
            return None
        data_length = frame[3]
        if len(frame) != data_length + 5 or (sum(frame[:-1]) & 0xFF) != frame[-1]:
            return None

        result = {}
        offset = 4
        flags = frame[2]
        if flags & self.ACC:
            raw = tuple(self._int16(frame, offset + index) for index in (0, 2, 4))
            result["accel_raw"] = raw
            result["accel"] = tuple(value * self._ACC_SCALE for value in raw)
            offset += 6
        if flags & self.GYRO:
            raw = tuple(self._int16(frame, offset + index) for index in (0, 2, 4))
            result["gyro_raw"] = raw
            result["gyro"] = tuple(value * self._GYRO_SCALE for value in raw)
            offset += 6
        if flags & self.EULER:
            raw = tuple(self._int16(frame, offset + index) for index in (0, 2, 4))
            result["euler_raw"] = raw
            result["roll"], result["pitch"], result["yaw"] = (
                value / 100.0 for value in raw
            )
            offset += 6
        if flags & self.TEMPERATURE:
            result["temperature_raw"] = self._int16(frame, offset)
            result["temperature"] = result["temperature_raw"] / 100.0
        return result

    def update(self):
        """Read UART bytes and return one complete decoded frame, if present."""
        count = self.uart.any()
        if count:
            data = self.uart.read(count)
            if data:
                self._buffer.extend(data)
                self.bytes_received += len(data)

        while len(self._buffer) >= 2:
            if self._buffer[0] != self._HEADER or self._buffer[1] != self._HEADER:
                self._buffer = self._buffer[1:]
                continue
            if len(self._buffer) < 4:
                return None
            size = self._buffer[3] + 5
            if size < 5 or size > 29:
                self._buffer = self._buffer[1:]
                continue
            if len(self._buffer) < size:
                return None
            frame = self._buffer[:size]
            self._buffer = self._buffer[size:]
            decoded = self._decode(frame)
            if decoded is not None:
                self.frames_received += 1
                return decoded
            self.invalid_frames += 1
        return None

    def read(self, timeout_ms=1000):
        """Wait for and return one decoded frame, or ``None`` after timeout."""
        start = ticks_ms()
        while ticks_diff(ticks_ms(), start) < timeout_ms:
            data = self.update()
            if data is not None:
                return data
        return None
