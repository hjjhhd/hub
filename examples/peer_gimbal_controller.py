"""MicroPython peer program that controls the Hub-owned F32C gimbal.

Copy the ``hub/`` directory to this development board too.  Set PEER_UART_ID
for this board's UART wired to the F407's ``controller_1`` port.
"""

from hub.module_runtime import ModuleRuntime
from hub.compat import ticks_add, ticks_diff, ticks_ms
from hub.platform import open_uart
from hub.protocol import STATUS_OK

# Use the logical UART number; open_uart() converts it to UART.UARTn on K230.
PEER_UART_NUMBER = 1
MODULE_NAME = "controller_1"
RUN_DEMO = True
DEMO_X_DEGREES = 90.0
DEMO_Y_DEGREES = 90.0


class GimbalClient:
    """Small RPC facade used by this board's application logic."""

    def __init__(self, module):
        self.module = module

    def enable(self, axis="all", callback=None):
        return self.module.call_hub("gimbal.enable", {"axis": axis}, callback)

    def disable(self, axis="all", callback=None):
        return self.module.call_hub("gimbal.disable", {"axis": axis}, callback)

    def set_mode(self, mode, axis="all", callback=None):
        return self.module.call_hub(
            "gimbal.set_mode", {"axis": axis, "mode": mode}, callback
        )

    def set_speed(self, x=None, y=None, callback=None):
        args = {}
        if x is not None:
            args["x"] = x
        if y is not None:
            args["y"] = y
        return self.module.call_hub("gimbal.set_speed", args, callback)

    def set_acceleration(self, x=None, y=None, callback=None):
        args = {}
        if x is not None:
            args["x"] = x
        if y is not None:
            args["y"] = y
        return self.module.call_hub("gimbal.set_acceleration", args, callback)

    def move_multiturn(self, x=None, y=None, callback=None):
        args = {}
        if x is not None:
            args["x"] = x
        if y is not None:
            args["y"] = y
        return self.module.call_hub("gimbal.move_multiturn", args, callback)

    def move_singleturn(self, x=None, y=None, callback=None):
        args = {}
        if x is not None:
            args["x"] = x
        if y is not None:
            args["y"] = y
        return self.module.call_hub("gimbal.move_singleturn", args, callback)

    def read(self, axis, metric, callback=None):
        return self.module.call_hub(
            "gimbal.read", {"axis": axis, "metric": metric}, callback
        )


class ImuClient:
    """Read the latest Hub-owned GY-25Z sample without owning its UART."""

    def __init__(self, module):
        self.module = module

    def read(self, callback=None):
        return self.module.call_hub("imu.read", {}, callback)

    def status(self, callback=None):
        return self.module.call_hub("imu.status", {}, callback)

    def set_rate(self, rate, callback=None):
        return self.module.call_hub("imu.set_rate", {"rate": rate}, callback)


def log_reply(frame):
    if frame["status"] == STATUS_OK:
        print("gimbal:", frame["body"])
    else:
        print("gimbal RPC failed:", frame["body"])


class PositionDemo:
    """Send the required F32C position-control sequence one reply at a time."""

    def __init__(self, client):
        self.client = client
        self.index = 0
        self.started = False
        self.failed = False
        self.steps = (
            ("enable", "gimbal.enable", {"axis": "all"}),
            ("set multi-turn mode", "gimbal.set_mode", {"axis": "all", "mode": "multi"}),
            ("set acceleration", "gimbal.set_acceleration", {"x": 100, "y": 100}),
            ("set speed", "gimbal.set_speed", {"x": 100, "y": 100}),
            ("move", "gimbal.move_multiturn", {"x": DEMO_X_DEGREES, "y": DEMO_Y_DEGREES}),
            ("read X bus voltage", "gimbal.read", {"axis": "x", "metric": "bus_voltage"}),
        )

    def tick(self):
        if not self.client.module.joined or self.started or self.failed:
            return
        self.started = True
        print("Hub joined; starting F32C demo")
        self._send_next()

    def _send_next(self):
        if self.index >= len(self.steps):
            print("F32C move command sent")
            return
        label, operation, args = self.steps[self.index]
        print("F32C:", label)
        self.client.module.call_hub(operation, args, self._on_reply)

    def _on_reply(self, frame):
        if frame["status"] != STATUS_OK:
            self.failed = True
            print("F32C demo stopped:", frame["body"])
            return
        print("F32C reply:", frame["body"])
        self.index += 1
        self._send_next()


uart = open_uart({"uart": PEER_UART_NUMBER, "baudrate": 115200, "rxbuf": 512})
module = ModuleRuntime(MODULE_NAME, uart, firmware="gimbal-client-1")
gimbal = GimbalClient(module)
imu = ImuClient(module)
demo = PositionDemo(gimbal)
next_wait_report = 0
reported_join = False

# Keep RUN_DEMO false for normal deployment.  Set it true only after checking
# the motion envelope; it sends DEMO_X_DEGREES and DEMO_Y_DEGREES once.

while True:
    now = ticks_ms()
    module.tick(now)
    if module.joined:
        if not reported_join:
            reported_join = True
            print("Hub handshake complete")
    elif ticks_diff(now, next_wait_report) >= 0:
        print("Waiting for Hub handshake on UART", PEER_UART_NUMBER)
        next_wait_report = ticks_add(now, 2000)
    if RUN_DEMO:
        demo.tick()
