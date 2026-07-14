"""Production F407 UART allocation for the K230, GY-25Z, and F32C setup."""

from .f32c_adapter import F32CGimbalAdapter
from .gy25z_adapter import GY25ZAdapter

# UART1: K230 RPC link. UART2: GY-25Z IMU. UART3: F32C two-axis gimbal.
# Confirm the corresponding board pins in the selected F407 board schematic.
PORTS = [
    {"uart": 1, "kind": "module", "name": "controller_1", "baudrate": 115200, "rxbuf": 512},
    {
        "uart": 2,
        "kind": "peripheral",
        "name": "gy25z_imu",
        "baudrate": 115200,
        "rxbuf": 512,
        "adapter": GY25ZAdapter(),
    },
    {
        "uart": 3,
        "kind": "peripheral",
        "name": "f32c_gimbal",
        "baudrate": 115200,
        "rxbuf": 512,
        "adapter": F32CGimbalAdapter(timeout_ms=100),
    },
]
