import socket
import struct
import xml.etree.ElementTree as ET
import json
import os
import time
from typing import Any, Dict


class ESocketClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 23001):
        self.host = host
        self.port = port
        self.socket = None
        self.terminal_id = None
        self.is_connected = False
        self.reconnect_attempts = 3  # Add reconnection attempts
        self.reconnect_delay = 2  # seconds

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

    def connect(self) -> bool:
        """Establish TCP connection to eSocket.POS with retry logic"""
        for attempt in range(self.reconnect_attempts):
            try:
                if self.socket:
                    self.disconnect()  # Clean up any existing connection

                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(10)  # Add timeout
                self.socket.connect((self.host, self.port))
                self.is_connected = True
                return True
            except Exception as e:
                print(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < self.reconnect_attempts - 1:
                    time.sleep(self.reconnect_delay)
                continue
        self.is_connected = False
        return False

    def _send_message(self, xml_message: str) -> str:
        """Send XML message with timeout handling"""
        if not self.is_connected:
            if not self.connect():
                raise Exception("Not connected to eSocket.POS")

        try:
            # Set timeout for operations
            self.socket.settimeout(30)  # 30 seconds timeout

            message_bytes = xml_message.encode("utf-8")
            header = self._create_message_header(len(message_bytes))

            # Send header + message with error checking
            total_sent = 0
            while total_sent < len(header + message_bytes):
                sent = self.socket.send((header + message_bytes)[total_sent:])
                if sent == 0:
                    raise Exception("Socket connection broken")
                total_sent += sent

            # Read response header with timeout
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
        except socket.timeout:
            self.is_connected = False
            raise Exception("Operation timed out")
        except socket.error as e:
            self.is_connected = False
            raise Exception(f"Socket error: {e}")

    def disconnect(self):
        """Close connection with proper cleanup"""
        try:
            if self.socket:
                self.socket.shutdown(socket.SHUT_RDWR)  # Properly shutdown socket
                self.socket.close()
        except Exception as e:
            print(f"Error during disconnect: {e}")
        finally:
            self.socket = None
            self.is_connected = False
            self.terminal_id = None  # Reset terminal ID on disconnect

    def initialize_terminal(
        self, terminal_id: str = None, register_callbacks: bool = True
    ) -> Dict[str, Any]:
        """Initialize terminal with eSocket.POS"""
        if not self.is_connected and not self.connect():
            raise Exception("Cannot initialize terminal - not connected")

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
        """Close terminal session with proper cleanup"""
        if not self.is_connected:
            return {"success": True, "message": "Already disconnected"}

        try:
            # Create XML root element
            root = ET.Element(
                "Esp:Interface",
                {
                    "Version": "1.0",
                    "xmlns:Esp": "http://www.mosaicsoftware.com/Postilion/eSocket.POS/",
                },
            )

            # Add Admin element with CLOSE action
            ET.SubElement(
                root,
                "Esp:Admin",
                {
                    "TerminalId": self.terminal_id,
                    "Action": "CLOSE",
                },
            )

            # Convert to proper XML string with declaration
            xml_message = ET.tostring(root, encoding="unicode")
            xml_message = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_message}'

            # Send close message and get response
            response = self._send_message(xml_message)

            # Parse and validate response
            parsed_response = self._parse_response(response)

            # Check if close was successful
            if (
                parsed_response.get("success")
                and 'ActionCode="APPROVE"' in parsed_response.get("raw_response", "")
            ):
                self.disconnect()  # Ensure we disconnect after closing
                return parsed_response
            else:
                raise Exception("Terminal close failed: " + str(parsed_response))
        except Exception as e:
            self.disconnect()  # Always try to disconnect on error
            raise Exception(f"Failed to close terminal: {str(e)}")

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

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Parse XML response from eSocket.POS"""
        try:
            root = ET.fromstring(response)
            # Basic response parsing - extend based on actual response structure
            result = {
                "raw_response": response,
                "success": True,  # Simplified - implement proper status checking
            }
            return result
        except Exception as e:
            return {
                "raw_response": response,
                "success": False,
                "error": str(e),
            }
