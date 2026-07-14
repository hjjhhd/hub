"""Production F407 entry point for K230 RPC, GY-25Z, and F32C."""

from hub.config import PORTS
from hub.runtime import SerialHub


print("Starting serial hub: K230 UART1, GY-25Z UART2, F32C UART3")
hub = SerialHub(PORTS)
print("Serial hub ready; waiting for controller_1")
hub.run_forever()
