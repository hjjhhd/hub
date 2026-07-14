import time

from pyb import LED
from hub import uart_hub


led = LED(3)
uarthub = uart_hub()


def main():
    """持续轮询 UART1,同时保持板载 LED 闪烁。"""
    last_led_toggle = time.ticks_ms()

    while True:
        # Forward UART2 input to UART1 without applying the UART1 frame filter.
        uarthub.uart2_to_uart1()

        # send() 会读取 UART1，并转发帧头为 0x7A 的有效数据。
        uarthub.send()

        # ticks_ms() 返回单调递增的毫秒计数；ticks_diff() 能在计数器溢出回绕时
        # 正确计算两个时间点的间隔。当前时刻与上次翻转相差至少 1000 毫秒时翻转 LED。
        if time.ticks_diff(time.ticks_ms(), last_led_toggle) >= 1000:
            led.toggle()
            last_led_toggle = time.ticks_ms()

        time.sleep_ms(1)


if __name__ == "__main__":
    main()
