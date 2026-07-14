"""Reusable runtime for a programmable development-board module."""

from .channel import RpcChannel
from .compat import ticks_add, ticks_diff, ticks_ms
from .protocol import STATUS_BAD_REQUEST, STATUS_FAILED, STATUS_NOT_FOUND, STATUS_OK, VERSION

HELLO_RETRY_MS = 1000


class ModuleRuntime:
    """Run the same RPC protocol on a satellite development board."""

    def __init__(self, name, uart, firmware="dev", capabilities=None):
        self.name = name
        self.firmware = firmware
        self.capabilities = capabilities or []
        self.channel = RpcChannel(name, uart, self._on_call, self._on_event)
        self.handlers = {}
        self.joined = False
        self._hello_in_flight = False
        self._next_hello = 0
        self.on_event = None

    def register(self, operation, handler):
        if operation in self.handlers:
            raise ValueError("duplicate operation: %s" % operation)
        self.handlers[operation] = handler

    def call_hub(self, operation, args=None, callback=None, timeout_ms=500):
        return self.channel.call(operation, args, callback, timeout_ms)

    def emit(self, event, data=None):
        self.channel.emit(event, data)

    def tick(self, now=None):
        if now is None:
            now = ticks_ms()
        self.channel.tick(now)
        if not self.joined and not self._hello_in_flight and ticks_diff(now, self._next_hello) >= 0:
            self._hello_in_flight = True
            self.channel.call("system.hello", {
                "name": self.name,
                "firmware": self.firmware,
                "protocol": VERSION,
                "capabilities": self.capabilities,
            }, self._on_hello)

    def _on_hello(self, frame):
        self._hello_in_flight = False
        self.joined = frame["status"] == STATUS_OK
        if not self.joined:
            self._next_hello = ticks_add(ticks_ms(), HELLO_RETRY_MS)

    def _on_call(self, channel, frame):
        body = frame["body"]
        operation = body["op"]
        handler = self.handlers.get(operation)
        if handler is None:
            channel.fail(frame["request_id"], "not_found", {"op": operation}, STATUS_NOT_FOUND)
            return
        args = body.get("args", {})
        if not isinstance(args, dict):
            channel.fail(frame["request_id"], "invalid_args", status=STATUS_BAD_REQUEST)
            return
        try:
            result = handler(args)
        except ValueError as exc:
            channel.fail(frame["request_id"], "invalid_args", {"message": str(exc)}, STATUS_BAD_REQUEST)
            return
        except Exception as exc:
            channel.fail(frame["request_id"], "module_failed", {"message": str(exc)}, STATUS_FAILED)
            return
        channel.reply(frame["request_id"], STATUS_OK, {"data": result})

    def _on_event(self, channel, frame):
        if self.on_event is not None:
            self.on_event(frame["body"])
