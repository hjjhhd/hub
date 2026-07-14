"""A non-blocking, retrying UART RPC channel for one point-to-point link."""

from .compat import ticks_add, ticks_diff, ticks_ms
from .protocol import (
    FLAG_RETRY,
    KIND_CALL,
    KIND_EVENT,
    KIND_RETURN,
    STATUS_BAD_REQUEST,
    STATUS_BUSY,
    STATUS_FAILED,
    STATUS_UNAVAILABLE,
    FrameDecoder,
    ProtocolError,
    encode_packet,
)

DEFAULT_TIMEOUT_MS = 500
MAX_RETRIES = 2
MAX_PENDING = 4
DUPLICATE_CACHE_SIZE = 8
DUPLICATE_CACHE_MS = 3000
RX_CHUNK_SIZE = 64
MAX_RX_CHUNKS_PER_TICK = 4
MAX_WRITES_PER_TICK = 4
MAX_EVENT_QUEUE = 8


class ChannelBusy(Exception):
    pass


class RpcChannel:
    """Own one UART and present a message-oriented RPC interface."""

    def __init__(self, name, uart, on_call=None, on_event=None):
        self.name = name
        self.uart = uart
        self.on_call = on_call
        self.on_event = on_event
        self.decoder = FrameDecoder()
        self.pending = {}
        self.inbound_pending = {}
        self.duplicate_cache = []
        self._next_request_id = 1
        self._return_queue = []
        self._call_queue = []
        self._event_queue = {}
        self._event_order = []
        self._tx_current = None
        self.stats = {
            "rx_frames": 0,
            "tx_frames": 0,
            "decode_errors": 0,
            "bad_requests": 0,
            "timeouts": 0,
            "retries": 0,
            "duplicates": 0,
            "dropped_events": 0,
            "unsolicited_returns": 0,
        }

    def call(self, op, args=None, callback=None, timeout_ms=DEFAULT_TIMEOUT_MS):
        if not isinstance(op, str) or not op:
            raise ValueError("op must be a non-empty string")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ValueError("args must be an object")
        if len(self.pending) >= MAX_PENDING:
            raise ChannelBusy("too many pending calls on %s" % self.name)

        request_id = self._allocate_request_id()
        body = {"op": op, "args": args}
        wire = encode_packet(KIND_CALL, request_id, body)
        self.pending[request_id] = {
            "body": body,
            "wire": wire,
            "callback": callback,
            "timeout_ms": timeout_ms,
            "deadline": None,
            "retries": 0,
        }
        self._call_queue.append((wire, request_id))
        return request_id

    def emit(self, event, data=None):
        if not isinstance(event, str) or not event:
            raise ValueError("event must be a non-empty string")
        if data is None:
            data = {}
        body = {"event": event, "data": data}
        wire = encode_packet(KIND_EVENT, 0, body)
        if event not in self._event_queue:
            if len(self._event_order) >= MAX_EVENT_QUEUE:
                dropped = self._event_order.pop(0)
                self._event_queue.pop(dropped, None)
                self.stats["dropped_events"] += 1
            self._event_order.append(event)
        self._event_queue[event] = wire

    def reply(self, request_id, status, body=None):
        """Finish an inbound call and cache its reply for retry de-duplication."""
        wire = encode_packet(KIND_RETURN, request_id, body, status)
        self.inbound_pending.pop(request_id, None)
        now = ticks_ms()
        self.duplicate_cache.append({
            "request_id": request_id,
            "wire": wire,
            "expires": ticks_add(now, DUPLICATE_CACHE_MS),
        })
        if len(self.duplicate_cache) > DUPLICATE_CACHE_SIZE:
            self.duplicate_cache.pop(0)
        self._return_queue.append((wire, None))

    def fail(self, request_id, error, detail=None, status=STATUS_FAILED):
        body = {"error": error}
        if detail is not None:
            body["detail"] = detail
        self.reply(request_id, status, body)

    def tick(self, now=None):
        if now is None:
            now = ticks_ms()
        self._read_available()
        self._expire_cache(now)
        self._process_timeouts(now)
        for _ in range(MAX_WRITES_PER_TICK):
            if not self._write_one(now):
                break

    def _read_available(self):
        decoder_errors = self.decoder.errors
        for _ in range(MAX_RX_CHUNKS_PER_TICK):
            count = self.uart.any()
            if not count:
                break
            data = self.uart.read(min(count, RX_CHUNK_SIZE))
            if not data:
                break
            for frame in self.decoder.feed(data):
                self.stats["rx_frames"] += 1
                self._handle_frame(frame)
        self.stats["decode_errors"] += self.decoder.errors - decoder_errors

    def _handle_frame(self, frame):
        kind = frame["kind"]
        if kind == KIND_CALL:
            self._handle_call(frame)
        elif kind == KIND_RETURN:
            self._handle_return(frame)
        else:
            self._handle_event(frame)

    def _handle_call(self, frame):
        request_id = frame["request_id"]
        cached = self._find_cached_reply(request_id)
        if cached is not None:
            self.stats["duplicates"] += 1
            self._return_queue.append((cached, None))
            return
        if request_id in self.inbound_pending:
            self.stats["duplicates"] += 1
            return

        body = frame["body"]
        if not isinstance(body, dict) or not isinstance(body.get("op"), str):
            self.stats["bad_requests"] += 1
            self.fail(request_id, "invalid_call", status=STATUS_BAD_REQUEST)
            return
        if "args" in body and not isinstance(body["args"], dict):
            self.stats["bad_requests"] += 1
            self.fail(request_id, "invalid_args", status=STATUS_BAD_REQUEST)
            return

        self.inbound_pending[request_id] = True
        if self.on_call is None:
            self.fail(request_id, "unavailable", status=STATUS_UNAVAILABLE)
            return
        try:
            self.on_call(self, frame)
        except Exception as exc:
            self.fail(request_id, "handler_exception", {"message": str(exc)})

    def _handle_return(self, frame):
        request_id = frame["request_id"]
        pending = self.pending.pop(request_id, None)
        if pending is None:
            self.stats["unsolicited_returns"] += 1
            return
        # A response can arrive while a retry is still waiting in the queue.
        self._call_queue = [
            item for item in self._call_queue if item[1] != request_id
        ]
        callback = pending["callback"]
        if callback is not None:
            callback(frame)

    def _handle_event(self, frame):
        body = frame["body"]
        if not isinstance(body, dict) or not isinstance(body.get("event"), str):
            self.stats["bad_requests"] += 1
            return
        if self.on_event is not None:
            self.on_event(self, frame)

    def _process_timeouts(self, now):
        for request_id in list(self.pending):
            pending = self.pending[request_id]
            deadline = pending["deadline"]
            if deadline is None or ticks_diff(now, deadline) < 0:
                continue
            if pending["retries"] < MAX_RETRIES:
                pending["retries"] += 1
                pending["wire"] = encode_packet(
                    KIND_CALL, request_id, pending["body"], flags=FLAG_RETRY
                )
                pending["deadline"] = None
                self._call_queue.append((pending["wire"], request_id))
                self.stats["retries"] += 1
                continue

            self.pending.pop(request_id, None)
            self.stats["timeouts"] += 1
            callback = pending["callback"]
            if callback is not None:
                callback({
                    "kind": KIND_RETURN,
                    "request_id": request_id,
                    "status": STATUS_UNAVAILABLE,
                    "body": {"error": "timeout"},
                    "flags": 0,
                })

    def _write_one(self, now):
        if self._tx_current is None:
            self._tx_current = self._next_outbound()
            if self._tx_current is None:
                return False

        wire, request_id, offset = self._tx_current
        written = self.uart.write(wire[offset:])
        if written is None:
            written = len(wire) - offset
        if written <= 0:
            return False
        offset += written
        if offset < len(wire):
            self._tx_current = (wire, request_id, offset)
            return False

        self._tx_current = None
        self.stats["tx_frames"] += 1
        if request_id is not None and request_id in self.pending:
            pending = self.pending[request_id]
            pending["deadline"] = ticks_add(now, pending["timeout_ms"])
        return True

    def _next_outbound(self):
        if self._return_queue:
            wire, request_id = self._return_queue.pop(0)
            return wire, request_id, 0
        if self._call_queue:
            wire, request_id = self._call_queue.pop(0)
            return wire, request_id, 0
        if self._event_order:
            event = self._event_order.pop(0)
            wire = self._event_queue.pop(event)
            return wire, None, 0
        return None

    def _allocate_request_id(self):
        for _ in range(0xffff):
            request_id = self._next_request_id
            self._next_request_id += 1
            if self._next_request_id > 0xffff:
                self._next_request_id = 1
            if request_id not in self.pending:
                return request_id
        raise ChannelBusy("request id space exhausted")

    def _find_cached_reply(self, request_id):
        for cached in self.duplicate_cache:
            if cached["request_id"] == request_id:
                return cached["wire"]
        return None

    def _expire_cache(self, now):
        self.duplicate_cache = [
            item for item in self.duplicate_cache
            if ticks_diff(item["expires"], now) > 0
        ]
