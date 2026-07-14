"""K230 MicroPython peer that prints GY-25Z data owned by the F407 Hub."""

from hub.compat import ticks_add, ticks_diff, ticks_ms
from hub.module_runtime import ModuleRuntime
from hub.platform import open_uart
from hub.protocol import STATUS_OK

# This is the K230-side UART connected to F407 UART1.
PEER_UART_NUMBER = 1
MODULE_NAME = "controller_1"
POLL_INTERVAL_MS = 100


class ImuMonitor:
    def __init__(self, module):
        self.module = module
        self.pending = False
        self.next_poll = 0
        self.next_status = 0
        self.reported_unavailable = False

    def tick(self, now):
        if not self.module.joined or self.pending:
            return
        if ticks_diff(now, self.next_poll) < 0:
            return
        self.pending = True
        self.module.call_hub("imu.read", {}, self._on_read)

    def _on_read(self, frame):
        self.pending = False
        self.next_poll = ticks_add(ticks_ms(), POLL_INTERVAL_MS)
        if frame["status"] != STATUS_OK:
            print("IMU RPC failed:", frame["body"])
            return
        data = frame["body"].get("data", {})
        if not data.get("available"):
            if not self.reported_unavailable:
                self.reported_unavailable = True
                print("GY-25Z has not produced a valid frame yet")
            now = ticks_ms()
            if ticks_diff(now, self.next_status) >= 0:
                self.next_status = ticks_add(now, 2000)
                self.pending = True
                self.module.call_hub("imu.status", {}, self._on_status)
            return
        self.reported_unavailable = False
        print(
            "roll={:.2f} pitch={:.2f} yaw={:.2f} temp={:.2f} age={}ms".format(
                data.get("roll", 0.0),
                data.get("pitch", 0.0),
                data.get("yaw", 0.0),
                data.get("temperature", 0.0),
                data.get("age_ms", -1),
            )
        )

    def _on_status(self, frame):
        self.pending = False
        if frame["status"] != STATUS_OK:
            print("IMU status RPC failed:", frame["body"])
            return
        data = frame["body"].get("data", {})
        print(
            "GY-25Z UART2 status: bytes={} valid_frames={} invalid_frames={}".format(
                data.get("bytes_received", 0),
                data.get("frames_received", 0),
                data.get("invalid_frames", 0),
            )
        )


uart = open_uart({"uart": PEER_UART_NUMBER, "baudrate": 115200, "rxbuf": 512})
module = ModuleRuntime(MODULE_NAME, uart, firmware="imu-monitor-1")
monitor = ImuMonitor(module)

next_wait_report = 0
reported_join = False
while True:
    now = ticks_ms()
    module.tick(now)
    if module.joined:
        if not reported_join:
            reported_join = True
            print("Hub handshake complete; reading GY-25Z")
        monitor.tick(now)
    elif ticks_diff(now, next_wait_report) >= 0:
        print("Waiting for Hub handshake on UART", PEER_UART_NUMBER)
        next_wait_report = ticks_add(now, 2000)
