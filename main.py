import logging
from pos_config import POSConfig
from serial_bridge import SerialBridge
import pos_api

logging.basicConfig(level=logging.INFO)

def main():
    config = POSConfig()
    serial_port = config.get("port")
    baudrate = config.get("baudrate")
    pos_api_url = "http://YOUR_IP:8000"  # Replace YOUR_IP with the machine running pos_api.py

    bridge = SerialBridge(serial_port, baudrate, pos_api_url)
    bridge.start()

    pos_api.serial_bridge = bridge

    print("SerialBridge started. Run FastAPI with: uvicorn pos_api:app --reload")

if __name__ == "__main__":
    main()
if __name__ == "__main__":
    main()
