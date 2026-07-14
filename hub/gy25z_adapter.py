"""Hub services for a GY-25Z inclinometer on a dedicated UART."""

from .compat import ticks_diff, ticks_ms
from .services import PeripheralAdapter


def _load_gy25z_driver():
    try:
        from .gy25z import GY25Z
    except ImportError:
        try:
            from gy25z import GY25Z
        except ImportError:
            raise ImportError(
                "copy gy25z.py from the GY25Z micropython project beside "
                "main_f32c.py or into hub/ before enabling GY25ZAdapter"
            )
    return GY25Z


class GY25ZAdapter(PeripheralAdapter):
    """Continuously cache GY-25Z frames and expose the most recent reading."""

    def __init__(self, driver_class=None, set_continuous=True):
        self.driver_class = driver_class
        self.set_continuous = set_continuous
        self.imu = None
        self.latest = None
        self.latest_at = None

    def bind(self, hub, uart, config):
        PeripheralAdapter.bind(self, hub, uart, config)
        driver_class = self.driver_class or _load_gy25z_driver()
        self.imu = driver_class(uart)
        if self.set_continuous:
            self.imu.continuous(True)

    def register_services(self, services):
        services.register("imu.read", self.read)
        services.register("imu.status", self.status)
        services.register("imu.set_rate", self.set_rate)
        services.register("imu.set_vertical_mode", self.set_vertical_mode)
        services.register("imu.calibrate", self.calibrate)

    def tick(self, now):
        # update() drains the UART once and returns one decoded frame.  Repeat
        # a few times so a high output rate cannot monopolize the Hub loop.
        for _ in range(4):
            reading = self.imu.update()
            if reading is None:
                break
            self.latest = self._json_safe(reading)
            self.latest_at = now

    def read(self, args, context):
        if self.latest is None:
            return {"available": False}
        # Keep the public reply safely below the UART RPC 256-byte payload
        # limit. Raw sensor integers remain available internally for logging.
        result = {}
        for key in ("accel", "gyro", "roll", "pitch", "yaw", "temperature"):
            if key in self.latest:
                result[key] = self.latest[key]
        result["available"] = True
        result["age_ms"] = ticks_diff(ticks_ms(), self.latest_at)
        return result

    def status(self, args, context):
        return {
            "available": self.latest is not None,
            "age_ms": None if self.latest_at is None else ticks_diff(ticks_ms(), self.latest_at),
            "bytes_received": self.imu.bytes_received,
            "frames_received": self.imu.frames_received,
            "invalid_frames": self.imu.invalid_frames,
        }

    def set_rate(self, args, context):
        rate = args.get("rate")
        if rate not in (10, 50, 100, 200):
            raise ValueError("rate must be 10, 50, 100, or 200")
        self.imu.set_rate(rate)
        return {"rate": rate}

    def set_vertical_mode(self, args, context):
        enabled = args.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        self.imu.set_vertical_mode(enabled)
        return {"vertical_mode": enabled}

    def calibrate(self, args, context):
        self.imu.calibrate_accel_gyro()
        return {"started": True}

    @staticmethod
    def _json_safe(reading):
        result = {}
        for key, value in reading.items():
            if isinstance(value, tuple):
                result[key] = list(value)
            else:
                result[key] = value
        return result
