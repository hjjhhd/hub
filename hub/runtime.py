"""The autonomous F407 Hub: static ports, dispatch, jobs, and polling."""

from .channel import ChannelBusy, RpcChannel
from .compat import sleep_ms, ticks_ms
from .platform import open_uart
from .protocol import STATUS_BAD_REQUEST, STATUS_OK, STATUS_UNAVAILABLE, VERSION
from .services import ServiceRegistry


class ModuleOffline(Exception):
    pass


class SerialHub:
    """Coordinate static module links and local peripheral adapters."""

    def __init__(self, ports, adapters=None, uart_factory=None):
        self.ports = list(ports)
        self.uart_factory = uart_factory or open_uart
        self.services = ServiceRegistry(self)
        self.channels = {}
        self.module_state = {}
        self.adapters = []
        self.jobs = {}
        self._next_job_id = 1
        self.on_module_event = None

        self.services.register("system.status", self._status_service)
        for config in self.ports:
            self._add_port(config)
        for adapter in adapters or ():
            self.add_adapter(adapter)

    def _add_port(self, config):
        config = dict(config)
        kind = config.get("kind")
        name = config.get("name")
        if kind not in ("module", "peripheral"):
            raise ValueError("port %r must have kind module or peripheral" % config.get("uart"))
        if not isinstance(name, str) or not name:
            raise ValueError("every port needs a non-empty static name")
        if name in self.module_state:
            raise ValueError("duplicate module name: %s" % name)

        uart = config.get("uart_object")
        if uart is None:
            uart = self.uart_factory(config)

        if kind == "module":
            channel = RpcChannel(name, uart, self._on_module_call, self._on_module_event)
            self.channels[name] = channel
            self.module_state[name] = {
                "config": config,
                "online": False,
                "last_seen": None,
            }
            return

        adapter = config.get("adapter")
        if adapter is None:
            raise ValueError("peripheral port %s requires an adapter" % name)
        self._bind_adapter(adapter, uart, config)

    def _bind_adapter(self, adapter, uart, config):
        adapter.bind(self, uart, config)
        adapter.register_services(self.services)
        self.adapters.append(adapter)

    def add_adapter(self, adapter):
        """Register a non-UART adapter, such as a GPIO-only local service."""
        adapter.register_services(self.services)
        self.adapters.append(adapter)

    def tick(self, now=None):
        if now is None:
            now = ticks_ms()
        for channel in self.channels.values():
            channel.tick(now)
        for adapter in self.adapters:
            adapter.tick(now)

    def run_forever(self, idle_ms=1):
        while True:
            self.tick()
            sleep_ms(idle_ms)

    def call_module(self, module_name, operation, args=None, callback=None, timeout_ms=500):
        state = self.module_state.get(module_name)
        if state is None or not state["online"]:
            raise ModuleOffline(module_name)
        return self.channels[module_name].call(operation, args, callback, timeout_ms)

    def publish_event(self, event, data=None, target=None):
        if target is not None:
            state = self.module_state.get(target)
            if state is None or not state["online"]:
                raise ModuleOffline(target)
            self.channels[target].emit(event, data)
            return
        for name, channel in self.channels.items():
            if self.module_state[name]["online"]:
                channel.emit(event, data)

    def start_job(self, owner_module, event_prefix):
        job = self._next_job_id
        self._next_job_id += 1
        if self._next_job_id > 0xffff:
            self._next_job_id = 1
        self.jobs[job] = {
            "owner": owner_module,
            "event_prefix": event_prefix,
        }
        return job

    def complete_job(self, job, data=None):
        entry = self.jobs.pop(job, None)
        if entry is None:
            raise ValueError("unknown job")
        payload = {"job": job}
        if data is not None:
            payload["result"] = data
        self.publish_event(entry["event_prefix"] + ".completed", payload, entry["owner"])

    def fail_job(self, job, error, detail=None):
        entry = self.jobs.pop(job, None)
        if entry is None:
            raise ValueError("unknown job")
        payload = {"job": job, "error": error}
        if detail is not None:
            payload["detail"] = detail
        self.publish_event(entry["event_prefix"] + ".failed", payload, entry["owner"])

    def _on_module_call(self, channel, frame):
        state = self.module_state[channel.name]
        state["last_seen"] = ticks_ms()
        body = frame["body"]
        operation = body["op"]
        if operation == "system.hello":
            self._handle_hello(channel, frame)
            return
        if not state["online"]:
            channel.fail(frame["request_id"], "not_joined", status=STATUS_UNAVAILABLE)
            return
        self.services.dispatch(channel, frame)

    def _on_module_event(self, channel, frame):
        state = self.module_state[channel.name]
        if not state["online"]:
            return
        state["last_seen"] = ticks_ms()
        body = frame["body"]
        if body.get("event") == "gimbal.move_multiturn":
            self.services.dispatch_event("gimbal.move_multiturn", body.get("data", {}))
        if self.on_module_event is not None:
            self.on_module_event(channel.name, body)

    def _handle_hello(self, channel, frame):
        args = frame["body"].get("args", {})
        expected_name = channel.name
        if not isinstance(args, dict) or args.get("name") != expected_name:
            channel.fail(
                frame["request_id"],
                "identity_mismatch",
                {"expected": expected_name},
                STATUS_BAD_REQUEST,
            )
            return
        if args.get("protocol") != VERSION:
            channel.fail(
                frame["request_id"],
                "protocol_mismatch",
                {"expected": VERSION},
                STATUS_BAD_REQUEST,
            )
            return
        state = self.module_state[channel.name]
        state["online"] = True
        state["last_seen"] = ticks_ms()
        channel.reply(
            frame["request_id"],
            STATUS_OK,
            {"data": {"name": expected_name, "protocol": VERSION}},
        )

    def _status_service(self, args, context):
        modules = {}
        for name, state in self.module_state.items():
            modules[name] = state["online"]
        return {"modules": modules, "jobs": len(self.jobs)}
