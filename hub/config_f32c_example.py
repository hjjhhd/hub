"""Example F407 allocation: one F32C gimbal and five development boards."""

from .f32c_adapter import F32CGimbalAdapter
from .gy25z_adapter import GY25ZAdapter

# Change UART numbers to match the selected F407 board's actual pin mapping.
# The F32C needs 115200 8N1, 3.3 V TTL, crossed TX/RX, and common ground.
PORTS = [
    {
        "uart": 3,
        "kind": "peripheral",
        "name": "f32c_gimbal",
        "baudrate": 115200,
        "rxbuf": 512,
        "adapter": F32CGimbalAdapter(timeout_ms=100),
    },
    {"uart": 1, "kind": "module", "name": "controller_1", "baudrate": 115200, "rxbuf": 512},
    {
        "uart": 2,
        "kind": "peripheral",
        "name": "gy25z_imu",
        "baudrate": 115200,
        "rxbuf": 512,
        "adapter": GY25ZAdapter(),
    },
    {"uart": 4, "kind": "module", "name": "module_3", "baudrate": 115200, "rxbuf": 512}
]
