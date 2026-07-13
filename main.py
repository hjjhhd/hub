import time

from pyb import LED


led = LED(3)


def blink_led():
    """Flash the red onboard LED once per second."""
    while True:
        led.toggle()
        time.sleep_ms(900)


if __name__ == "__main__":
    blink_led()
