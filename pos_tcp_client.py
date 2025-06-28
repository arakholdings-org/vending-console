import socket
import logging

class POSTcpClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port))
        logging.info(f"Connected to POS server at {self.host}:{self.port}")

    def send_message(self, message: str):
        if not self.sock:
            self.connect()
        self.sock.sendall(message.encode('utf-8'))
        logging.info(f"Sent: {message}")

    def receive_message(self, bufsize=4096) -> str:
        if not self.sock:
            self.connect()
        data = self.sock.recv(bufsize)
        logging.info(f"Received: {data.decode('utf-8')}")
        return data.decode('utf-8')

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None