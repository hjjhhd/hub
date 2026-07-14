"""Service registration and the adapter interface used by the serial hub."""

from .protocol import (
    STATUS_ACCEPTED,
    STATUS_BAD_REQUEST,
    STATUS_FAILED,
    STATUS_NOT_FOUND,
    STATUS_OK,
)


class Accepted:
    """A handler result for work that will complete through a later event."""

    def __init__(self, job, data=None):
        self.job = job
        self.data = {} if data is None else data


class CallContext:
    """The Hub-owned context supplied to a service handler."""

    def __init__(self, hub, channel, request_id):
        self.hub = hub
        self.channel = channel
        self.request_id = request_id

    def accept(self, event_prefix, data=None):
        job = self.hub.start_job(self.channel.name, event_prefix)
        return Accepted(job, data)


class ServiceRegistry:
    """Map public operation names to small, synchronous service handlers."""

    def __init__(self, hub):
        self.hub = hub
        self._handlers = {}

    def register(self, operation, handler):
        if not isinstance(operation, str) or not operation:
            raise ValueError("operation must be a non-empty string")
        if operation in self._handlers:
            raise ValueError("duplicate service: %s" % operation)
        self._handlers[operation] = handler

    def dispatch(self, channel, frame):
        body = frame["body"]
        operation = body["op"]
        handler = self._handlers.get(operation)
        if handler is None:
            channel.fail(frame["request_id"], "not_found", {"op": operation}, STATUS_NOT_FOUND)
            return

        args = body.get("args", {})
        if not isinstance(args, dict):
            channel.fail(frame["request_id"], "invalid_args", status=STATUS_BAD_REQUEST)
            return

        context = CallContext(self.hub, channel, frame["request_id"])
        try:
            result = handler(args, context)
        except ValueError as exc:
            channel.fail(frame["request_id"], "invalid_args", {"message": str(exc)}, STATUS_BAD_REQUEST)
            return
        except Exception as exc:
            channel.fail(frame["request_id"], "service_failed", {"message": str(exc)}, STATUS_FAILED)
            return

        if isinstance(result, Accepted):
            data = {"job": result.job}
            data.update(result.data)
            channel.reply(frame["request_id"], STATUS_ACCEPTED, {"data": data})
            return
        channel.reply(frame["request_id"], STATUS_OK, {"data": result})


class PeripheralAdapter:
    """Base class for wrapping an existing UART peripheral library.

    An adapter owns exactly one peripheral UART.  It should expose selected
    library operations through ``register_services`` and advance non-blocking
    work from ``tick``.  It deliberately does not impose a device protocol.
    """

    def bind(self, hub, uart, config):
        self.hub = hub
        self.uart = uart
        self.config = config

    def register_services(self, services):
        pass

    def tick(self, now):
        pass
