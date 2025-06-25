import threading
import time
import logging
import requests
from serial import Serial

class SerialBridge:
    def __init__(self, serial_port, baudrate, pos_api_url):
        self.serial = Serial(serial_port, baudrate, timeout=1)
        self.pos_api_url = pos_api_url
        self.running = False
        self.current_session = None

    def start(self):
        self.running = True
        threading.Thread(target=self.listen_serial, daemon=True).start()

    def listen_serial(self):
        while self.running:
            try:
                msg = self.serial.readline()
                if msg:
                    logging.info(f"Received from VMC: {msg.hex()}")
                    self.handle_vmc_message(msg)
            except Exception as e:
                logging.error(f"Serial read error: {e}")
            time.sleep(0.05)

    def handle_vmc_message(self, msg: bytes):
        try:
            payload = {"raw": msg.hex()}
            resp = requests.post(f"{self.pos_api_url}/vmc/message", json=payload, timeout=2)
            logging.info(f"Forwarded to POS API, response: {resp.status_code}")
        except Exception as e:
            logging.error(f"Error forwarding to POS API: {e}")

    def send_to_vmc(self, msg: bytes):
        try:
            self.serial.write(msg)
            self.serial.flush()
            logging.info(f"Sent to VMC: {msg.hex()}")
        except Exception as e:
            logging.error(f"Serial write error: {e}")

    def stop(self):
        self.running = False
        self.serial.close()
        self.running = False
        self.serial.close()
