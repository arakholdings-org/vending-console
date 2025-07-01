import socket
import struct
import xml.etree.ElementTree as ET
import json
import os
from typing import Any, Dict


class ESocketClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 23001):
        self.host = host
        self.port = port
        self.socket = None
        self.terminal_id = None

    def _load_terminal_id_from_config(self) -> str:
        """Load terminal ID from config.json"""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config.json"
        )
        with open(config_path, "r") as f:
            config = json.load(f)
        return config["TERMINAL_ID"]

    def _create_message_header(self, message_length: int) -> bytes:
        """Create TCP message header based on message length"""
        if message_length < 65535:
            # Two-byte header
            quotient = message_length // 256
            remainder = message_length % 256
            return struct.pack("BB", quotient, remainder)
        else:
            # Six-byte header for large messages
            header = struct.pack("BB", 0xFF, 0xFF)
            header += struct.pack(">I", message_length)
            return header

    def _send_message(self, xml_message: str) -> str:
        """Send XML message with proper TCP header"""
        message_bytes = xml_message.encode("utf-8")
        header = self._create_message_header(len(message_bytes))

        # Send header + message
        self.socket.sendall(header + message_bytes)

        # Read response header
        response_header = self.socket.recv(2)
        if len(response_header) < 2:
            raise Exception("Failed to read response header")

        # Parse header to get message length
        if response_header == b"\xff\xff":
            # Six-byte header
            length_bytes = self.socket.recv(4)
            response_length = struct.unpack(">I", length_bytes)[0]
        else:
            # Two-byte header
            response_length = response_header[0] * 256 + response_header[1]

        # Read response message
        response_data = self.socket.recv(response_length)
        return response_data.decode("utf-8")

    def connect(self) -> bool:
        """Establish TCP connection to eSocket.POS"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    def disconnect(self):
        """Close connection"""
        if self.socket:
            self.socket.close()
            self.socket = None

    def initialize_terminal(
        self, terminal_id: str = None, register_callbacks: bool = True
    ) -> Dict[str, Any]:
        """Initialize terminal with eSocket.POS"""
        if terminal_id is None:
            terminal_id = self._load_terminal_id_from_config()

        self.terminal_id = terminal_id

        # Build initialization XML
        root = ET.Element(
            "Esp:Interface",
            {
                "Version": "1.0",
                "xmlns:Esp": "http://www.mosaicsoftware.com/Postilion/eSocket.POS/",
            },
        )

        admin = ET.SubElement(
            root,
            "Esp:Admin",
            {
                "TerminalId": terminal_id,
                "Action": "INIT",
            },
        )

        # Register for callbacks if needed
        if register_callbacks:
            ET.SubElement(
                admin,
                "Esp:Register",
                {
                    "Type": "CALLBACK",
                    "EventId": "DATA_REQUIRED",
                },
            )
            ET.SubElement(
                admin,
                "Esp:Register",
                {
                    "Type": "EVENT",
                    "EventId": "PROMPT_INSERT_CARD",
                },
            )

        xml_message = ET.tostring(root, encoding="unicode")
        xml_message = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_message}'

        response = self._send_message(xml_message)
        return self._parse_response(response)

    def close_terminal(self) -> Dict[str, Any]:
        """Close terminal session"""
        root = ET.Element(
            "Esp:Interface",
            {
                "Version": "1.0",
                "xmlns:Esp": "http://www.mosaicsoftware.com/Postilion/eSocket.POS/",
            },
        )

        ET.SubElement(
            root,
            "Esp:Admin",
            {
                "TerminalId": self.terminal_id,
                "Action": "CLOSE",
            },
        )

        xml_message = ET.tostring(root, encoding="unicode")
        xml_message = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_message}'

        response = self._send_message(xml_message)
        return self._parse_response(response)

    def send_purchase_transaction(
        self, transaction_id: str, amount: int, currency_code: str = "840"
    ):
        """Send purchase transaction (amount in minor denominations)"""
        root = ET.Element(
            "Esp:Interface",
            {
                "Version": "1.0",
                "xmlns:Esp": "http://www.mosaicsoftware.com/Postilion/eSocket.POS/",
            },
        )

        ET.SubElement(
            root,
            "Esp:Transaction",
            {
                "TerminalId": self.terminal_id,
                "TransactionId": transaction_id,
                "Type": "PURCHASE",
                "TransactionAmount": str(amount),
                "CurrencyCode": currency_code,
            },
        )

        xml_message = ET.tostring(root, encoding="unicode")
        xml_message = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_message}'

        response = self._send_message(xml_message)
        return self._parse_response(response)

    def send_deposit_transaction(
        self, transaction_id: str, amount: int, currency_code: str = "840"
    ):
        """Send deposit transaction for change disbursement"""
        root = ET.Element(
            "Esp:Interface",
            {
                "Version": "1.0",
                "xmlns:Esp": "http://www.mosaicsoftware.com/Postilion/eSocket.POS/",
            },
        )

        ET.SubElement(
            root,
            "Esp:Transaction",
            {
                "TerminalId": self.terminal_id,
                "TransactionId": transaction_id,
                "Type": "DEPOSIT",
                "TransactionAmount": str(amount),
                "CurrencyCode": currency_code,
                "ExtendedTransactionType": "6001",
            },
        )

        xml_message = ET.tostring(root, encoding="unicode")
        xml_message = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_message}'

        response = self._send_message(xml_message)
        return self._parse_response(response)
