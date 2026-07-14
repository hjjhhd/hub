"""Create UARTs across pyboard, machine.UART, and CanMV-style ports."""


def _uart_class():
    try:
        from pyb import UART
    except ImportError:
        from machine import UART
    return UART


def _uart_id(uart_class, uart_id):
    """K230 uses UART.UART1 enums while pyboard uses plain integers."""
    if isinstance(uart_id, int):
        return getattr(uart_class, "UART%d" % uart_id, uart_id)
    return uart_id


def open_uart(config, uart_class=None):
    """Open a non-blocking UART while tolerating port-specific APIs.

    Some CanMV/K230 builds reject ``parity=None`` with ``can't convert
    NoneType to int``.  The progressively smaller argument sets preserve the
    pyboard configuration where supported while allowing those builds to use
    their 8N1 defaults.
    """
    UART = uart_class or _uart_class()
    uart_id = _uart_id(UART, config["uart"])
    full_kwargs = {
        "baudrate": config.get("baudrate", 115200),
        "bits": 8,
        "parity": None,
        "stop": 1,
        "timeout": 0,
        "timeout_char": 0,
    }
    if "rxbuf" in config:
        full_kwargs["rxbuf"] = config["rxbuf"]

    candidates = (
        full_kwargs,
        {"baudrate": config.get("baudrate", 115200), "bits": 8, "stop": 1},
        {"baudrate": config.get("baudrate", 115200)},
    )
    for kwargs in candidates:
        try:
            return UART(uart_id, **kwargs)
        except (TypeError, ValueError):
            pass

    # Older STM32 MicroPython builds create first, then configure.
    try:
        uart = UART(uart_id)
    except TypeError:
        raise
    for kwargs in candidates:
        try:
            uart.init(**kwargs)
            return uart
        except TypeError:
            pass
    raise TypeError("UART does not support a usable baudrate configuration")
