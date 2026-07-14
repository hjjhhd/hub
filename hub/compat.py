"""Small compatibility helpers shared by CPython tests and MicroPython."""

try:
    import ujson as json
except ImportError:
    import json

try:
    import utime as _time

    def ticks_ms():
        return _time.ticks_ms()

    def ticks_add(value, delta):
        return _time.ticks_add(value, delta)

    def ticks_diff(left, right):
        return _time.ticks_diff(left, right)

    def sleep_ms(delay):
        _time.sleep_ms(delay)
except ImportError:
    import time as _time

    def ticks_ms():
        return int(_time.monotonic() * 1000)

    def ticks_add(value, delta):
        return value + delta

    def ticks_diff(left, right):
        return left - right

    def sleep_ms(delay):
        _time.sleep(delay / 1000)


def json_dumps(value):
    """Return compact UTF-8 JSON without requiring CPython-only options."""
    try:
        text = json.dumps(value, separators=(",", ":"))
    except TypeError:
        text = json.dumps(value)
    return text.encode("utf-8")


def json_loads(payload):
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return json.loads(payload)
