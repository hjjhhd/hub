"""MicroPython driver for the WHEELTEC F32C two-axis gimbal.

The gimbal exposes the two motors on one 3.3 V TTL UART bus.  By default the
X axis has address 1 and the Y axis has address 2.
"""

try:
    from time import ticks_ms, ticks_diff, sleep_ms
except ImportError:
    # Allows protocol tests to run on CPython as well.
    from time import monotonic, sleep

    def ticks_ms():
        return int(monotonic() * 1000)

    def ticks_diff(now, then):
        return now - then

    def sleep_ms(ms):
        sleep(ms / 1000)


class F32CError(Exception):
    pass


class F32CTimeoutError(F32CError):
    pass


class F32CProtocolError(F32CError):
    pass


class F32CGimbal:
    """Control an F32C two-axis gimbal through a ``machine.UART`` object.

    The supplied UART must be configured for 115200 baud, 8 data bits, no
    parity, and one stop bit.  Connect controller TX to gimbal RX, controller
    RX to gimbal TX, and connect grounds together.
    """

    X_AXIS = 1
    Y_AXIS = 2

    MODE_SPEED = 0
    MODE_MULTI_T = 1
    MODE_SINGLE_T = 2
    MODE_MULTI_DIRECT = 3
    MODE_SINGLE_DIRECT = 4

    FEEDBACK_SPEED = 0
    FEEDBACK_TOTAL_ANGLE = 1
    FEEDBACK_MECHANICAL_ANGLE = 2
    FEEDBACK_ACCELERATION = 3
    FEEDBACK_BUS_VOLTAGE = 4

    _HEAD = 0x7A
    _TAIL = 0x7B

    def __init__(self, uart, x_id=1, y_id=2, timeout_ms=500):
        self.uart = uart
        self.x_id = self._validate_id(x_id)
        self.y_id = self._validate_id(y_id)
        self.timeout_ms = timeout_ms
        self._rx = bytearray()
        self.last_rx = bytearray()

    @staticmethod
    def _validate_id(address):
        if not isinstance(address, int) or not 0 <= address <= 255:
            raise ValueError("motor address must be an integer from 0 to 255")
        return address

    def _axis_id(self, axis):
        if axis == "x" or axis == "X":
            return self.x_id
        if axis == "y" or axis == "Y":
            return self.y_id
        return self._validate_id(axis)

    @staticmethod
    def _u16(value):
        if not isinstance(value, int) or not 0 <= value <= 0xFFFF:
            raise ValueError("value must fit in an unsigned 16-bit integer")
        return value

    @staticmethod
    def _i32_bytes(value):
        if not isinstance(value, int) or not -0x80000000 <= value <= 0x7FFFFFFF:
            raise ValueError("value must fit in a signed 32-bit integer")
        if value < 0:
            value += 0x100000000
        return ((value >> 24) & 0xFF, (value >> 16) & 0xFF,
                (value >> 8) & 0xFF, value & 0xFF)

    @staticmethod
    def _xor(data):
        check = 0
        for value in data:
            check ^= value
        return check

    def _frame(self, address, function, data=()):
        body = bytearray((self._HEAD, self._validate_id(address), function))
        # Some MicroPython ports only accept buffer-protocol objects in
        # bytearray.extend(), while all supported ports accept append().
        for value in data:
            body.append(value)
        body.append(self._xor(body))
        body.append(self._TAIL)
        return body

    def _send(self, address, function, data=()):
        frame = self._frame(address, function, data)
        written = self.uart.write(frame)
        if written is not None and written != len(frame):
            raise F32CError("UART could not write a complete F32C frame")
        return frame

    def enable(self, axis):
        """Enable one motor. Use ``enable_all`` for the normal gimbal start."""
        self._send(self._axis_id(axis), 0x06)

    def disable(self, axis):
        self._send(self._axis_id(axis), 0x05)

    def enable_all(self):
        self.enable("x")
        self.enable("y")

    def disable_all(self):
        self.disable("x")
        self.disable("y")

    def set_mode(self, axis, mode):
        """Set motor mode to one of the MODE_* constants."""
        if mode not in (self.MODE_SPEED, self.MODE_MULTI_T, self.MODE_SINGLE_T,
                        self.MODE_MULTI_DIRECT, self.MODE_SINGLE_DIRECT):
            raise ValueError("unknown F32C control mode")
        self._send(self._axis_id(axis), 0x00, ((mode >> 8) & 0xFF, mode & 0xFF))

    def set_mode_all(self, mode):
        self.set_mode("x", mode)
        self.set_mode("y", mode)

    def set_speed(self, axis, rpm):
        """Set speed in RPM. In speed mode it may be negative; range is +/-1000."""
        if not isinstance(rpm, int) or not -1000 <= rpm <= 1000:
            raise ValueError("rpm must be an integer from -1000 to 1000")
        if rpm < 0:
            rpm += 0x10000
        self._send(self._axis_id(axis), 0x01, ((rpm >> 8) & 0xFF, rpm & 0xFF))

    def set_speed_all(self, x_rpm, y_rpm):
        self.set_speed("x", x_rpm)
        self.set_speed("y", y_rpm)

    def set_acceleration(self, axis, rpm_per_s2):
        """Set T-trajectory acceleration in RPM/s^2."""
        value = self._u16(rpm_per_s2)
        self._send(self._axis_id(axis), 0x07,
                   ((value >> 8) & 0xFF, value & 0xFF))

    def move_multiturn(self, axis, degrees):
        """Move to an absolute power-on-relative angle, in degrees.

        Requires MODE_MULTI_T or MODE_MULTI_DIRECT. Resolution is 0.1 degree.
        """
        tenths = int(round(degrees * 10))
        self._send(self._axis_id(axis), 0x02, self._i32_bytes(tenths))

    def move_multiturn_xy(self, x_degrees, y_degrees):
        self.move_multiturn("x", x_degrees)
        self.move_multiturn("y", y_degrees)

    def move_singleturn(self, axis, degrees):
        """Move to an absolute mechanical angle from 0.0 to 359.9 degrees."""
        tenths = int(round(degrees * 10))
        if not 0 <= tenths <= 3599:
            raise ValueError("single-turn angle must be from 0.0 to 359.9 degrees")
        self._send(self._axis_id(axis), 0x03,
                   ((tenths >> 8) & 0xFF, tenths & 0xFF))

    def clear_multiturn_angle(self, axis):
        self._send(self._axis_id(axis), 0x09)

    def set_singleturn_zero(self, axis):
        """Persist the current mechanical position as the single-turn zero."""
        self._send(self._axis_id(axis), 0x0A)

    def set_address(self, axis, new_address, save=False):
        address = self._axis_id(axis)
        new_address = self._validate_id(new_address)
        self._send(address, 0x0D, (new_address,))
        if save:
            self.save(address)

    def save(self, axis):
        self._send(self._axis_id(axis), 0x08)

    def factory_reset(self, axis):
        self._send(self._axis_id(axis), 0x0B)

    @staticmethod
    def _signed32(data):
        value = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]
        return value - 0x100000000 if value & 0x80000000 else value

    def _read_available(self):
        count = self.uart.any()
        if count:
            try:
                data = self.uart.read(count)
            except TypeError:
                # A few MicroPython UART ports expose read() without a size.
                data = self.uart.read()
            if data:
                for value in data:
                    self._rx.append(value)
                self.last_rx = bytearray(data)

    def _pop_feedback(self, address, feedback_type):
        # Feedback packets are always: head, address, type, 4 data bytes, BCC, tail.
        while len(self._rx) >= 9:
            if self._rx[0] != self._HEAD:
                self._rx = self._rx[1:]
                continue
            if self._rx[8] != self._TAIL or self._xor(self._rx[:8]) != 0:
                self._rx = self._rx[1:]
                continue
            frame = self._rx[:9]
            self._rx = self._rx[9:]
            if frame[1] == address and frame[2] == feedback_type:
                return frame
        return None

    def feedback(self, axis, feedback_type, timeout_ms=None):
        """Request feedback and return a value in documented physical units.

        Speed is RPM, total and mechanical angle are degrees, acceleration is
        RPM/s^2, and bus voltage is volts. Raises F32CTimeoutError on no reply.
        """
        if feedback_type not in (self.FEEDBACK_SPEED, self.FEEDBACK_TOTAL_ANGLE,
                                 self.FEEDBACK_MECHANICAL_ANGLE,
                                 self.FEEDBACK_ACCELERATION,
                                 self.FEEDBACK_BUS_VOLTAGE):
            raise ValueError("unknown F32C feedback type")
        address = self._axis_id(axis)
        self._send(address, 0x0E, (feedback_type,))
        limit = self.timeout_ms if timeout_ms is None else timeout_ms
        start = ticks_ms()
        while ticks_diff(ticks_ms(), start) < limit:
            self._read_available()
            frame = self._pop_feedback(address, feedback_type)
            if frame is not None:
                raw = self._signed32(frame[3:7])
                if feedback_type in (self.FEEDBACK_TOTAL_ANGLE,
                                     self.FEEDBACK_MECHANICAL_ANGLE):
                    return raw / 10.0
                if feedback_type == self.FEEDBACK_BUS_VOLTAGE:
                    return raw / 100.0
                return raw
            sleep_ms(1)
        raw = "".join("%02X" % value for value in self.last_rx)
        raise F32CTimeoutError("no matching F32C feedback packet received; "
                               "last UART bytes: " + raw)

    def speed(self, axis, timeout_ms=None):
        return self.feedback(axis, self.FEEDBACK_SPEED, timeout_ms)

    def total_angle(self, axis, timeout_ms=None):
        return self.feedback(axis, self.FEEDBACK_TOTAL_ANGLE, timeout_ms)

    def mechanical_angle(self, axis, timeout_ms=None):
        return self.feedback(axis, self.FEEDBACK_MECHANICAL_ANGLE, timeout_ms)

    def bus_voltage(self, axis, timeout_ms=None):
        return self.feedback(axis, self.FEEDBACK_BUS_VOLTAGE, timeout_ms)
