# time 模块用于轮询 UART 状态，以及在发送完成前进行毫秒级等待。
import time

# UART 类用于创建和控制 STM32 的硬件串口。
from pyb import UART


# 模块级变量：保存 UART1 最近一次接收到的原始字节数据。
uart1_read = None

class Command:
    def __init__(self):
        pass

    def get_bcc(frame_byte):    #计算BCC校验码
        bcc = 0
        for b in frame_byte:
            bcc ^= b
        return bcc


# UART 数据转发管理类，负责 UART1 接收以及向 UART2、UART3 转发。
class uart_hub:
    # 初始化三个硬件串口，并记录它们共用的通信波特率。
    def __init__(self, baudrate=115200):
        # UART1: TX=PB6 (X9), RX=PB7 (X10).
        self.uart1 = UART(1, baudrate)
        # UART2: TX=PA2 (X3), RX=PA3 (X4).
        self.uart2 = UART(2, baudrate)
        # UART3: TX=PB10 (Y9), RX=PB11 (Y10).
        self.uart3 = UART(3, baudrate)
        self.baudrate = baudrate

    # 读取 UART1 缓冲区中的数据，并将最新有效数据保存到 uart1_read。
    def uart1_read(self):
        """Read pending UART1 data and save it in the uart1_read variable."""
        global uart1_read

        if self.uart1.any():
            data = self.uart1.read()
            if data:
                uart1_read = data

        return uart1_read

    # 等待指定 UART 结束上一帧发送；无 txdone() 时按波特率估算发送时间。
    def _wait_tx_idle(self, uart, data_length=0):
        """Wait for the UART to finish its previous transmission."""
        txdone = getattr(uart, "txdone", None)
        if txdone:
            while not txdone():
                time.sleep_ms(1)
        elif data_length:
            # UART frames use 1 start bit, 8 data bits, and 1 stop bit.
            duration_ms = (data_length * 10000 + self.baudrate - 1) // self.baudrate
            time.sleep_ms(duration_ms + 1)

    # staticmethod 表示该工具函数不访问 self 或类成员，只依赖传入的 UART 和数据。
    @staticmethod

    # 循环写入数据，避免 UART 单次 write() 未写完时丢失剩余字节。
    def _write_all(uart, data):
        """Write every byte, including when a UART write is partial."""
        offset = 0
        data_length = len(data)

        while offset < data_length:
            written = uart.write(data[offset:])
            if not written:
                return False
            offset += written

        return True

    def uart2_to_uart1(self):
        """Forward all pending UART2 data to UART1."""
        if not self.uart2.any():
            return False

        data = self.uart2.read()
        if not data:
            return False

        self._wait_tx_idle(self.uart1)
        sent = self._write_all(self.uart1, data)
        self._wait_tx_idle(self.uart1, len(data))

        return sent

    # 检查 UART1 数据帧头；帧头为 0x7A 时完整转发至 UART2 和 UART3。
    def send(self):
        """Forward a UART1 frame starting with 0x7A to UART2 and UART3."""
        global uart1_read
        data = self.uart1_read()  # 读取 UART1 当前缓存的数据。
        if not data:  # 没有收到任何数据时不转发。
            return False  # 返回未发送状态。
        frame_start = data.find(b"\x7A")  # 在当前读取块中搜索协议帧头。
        if frame_start < 0:  # 当前数据中不存在有效帧头时丢弃该块。
            uart1_read = None  # 清除无效缓存，避免下次重复处理。
            return False  # 返回未发送状态。
        data = data[frame_start:]  # 从帧头开始转发后续数据。

        # Both output ports must be idle before starting a new frame.
        self._wait_tx_idle(self.uart2)
        self._wait_tx_idle(self.uart3)

        sent_to_uart2 = self._write_all(self.uart2, data)
        sent_to_uart3 = self._write_all(self.uart3, data)

        # Do not accept another frame until both copies are fully sent.
        self._wait_tx_idle(self.uart2, len(data))
        self._wait_tx_idle(self.uart3, len(data))

        if sent_to_uart2 and sent_to_uart3:
            print((" ".join(["%02X" % byte for byte in data])))
            uart1_read = None
            return True

        return False
