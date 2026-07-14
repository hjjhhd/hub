"""MicroPython serial hub package."""

from .protocol import VERSION
from .runtime import SerialHub

__all__ = ("VERSION", "SerialHub")
