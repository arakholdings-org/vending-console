import asyncio
import socket
import struct
import xml.etree.ElementTree as ET
import json
import os
import time
from typing import Dict, Any
import subprocess


class ESocketClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 23001):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.terminal_id = None
        self.is_connected = False
        self._last_activity = 0

    def _load_terminal_id(self) -> str:
        """Load terminal ID from config file"""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config.json"
        )
        try:
            with open(config_path, "r") as f:
                return json.load(f)["TERMINAL_ID"]
        except Exception as e:
            raise Exception(f"Failed to load terminal ID: {e}")

    async def connect(self) -> bool:
        """Establish connection to eSocket server with service restart"""
        if self.is_connected:
            return True

        # Try to connect to the service
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=5.0
            )
            self.is_connected = True
            self._last_activity = time.time()
            print(f"Connected to eSocket at {self.host}:{self.port}")
            return True

        except Exception as e:
            print(f"Connection failed: {e}")
            await self._cleanup_connection()
            return False

    async def _cleanup_connection(self):
        """Clean up any existing connection"""
        self.is_connected = False
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except:
                pass
        self.writer = None
        self.reader = None

    def _create_message_header(self, message_length: int) -> bytes:
        """Create TCP message header based on length"""
        if message_length < 65535:
            return struct.pack("BB", message_length // 256, message_length % 256)
        return b"\xff\xff" + struct.pack(">I", message_length)

    async def _send_message(self, xml_message: str) -> str:
        """Send XML message and receive response"""
        if not await self.connect():
            raise Exception("Not connected to eSocket")

        try:
            # Prepare and send message
            message_bytes = xml_message.encode("utf-8")
            header = self._create_message_header(len(message_bytes))
            self.writer.write(header + message_bytes)
            await self.writer.drain()
            self._last_activity = time.time()

            # Read response header
            response_header = await asyncio.wait_for(
                self.reader.readexactly(2), timeout=10.0
            )

            # Determine message length
            if response_header == b"\xff\xff":
                length_bytes = await asyncio.wait_for(
                    self.reader.readexactly(4), timeout=10.0
                )
                response_length = struct.unpack(">I", length_bytes)[0]
            else:
                response_length = response_header[0] * 256 + response_header[1]

            # Read response body
            response_data = await asyncio.wait_for(
                self.reader.readexactly(response_length), timeout=10.0
            )
            self._last_activity = time.time()
            return response_data.decode("utf-8")

        except asyncio.TimeoutError:
            await self._cleanup_connection()
            raise Exception("Operation timed out")
        except Exception as e:
            await self._cleanup_connection()
            raise Exception(f"Communication error: {e}")

    async def initialize_terminal(self, terminal_id: str = None) -> Dict[str, Any]:
        """Initialize terminal session"""
        try:
            if not terminal_id:
                terminal_id = self._load_terminal_id()

            self.terminal_id = terminal_id

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

            # Only register for essential callbacks and remove PAN prompt
            ET.SubElement(
                admin,
                "Esp:Register",
                {"Type": "EVENT", "EventId": "PROMPT_INSERT_CARD"},
            )
            ET.SubElement(
                admin,
                "Esp:Register",
                {"Type": "EVENT", "EventId": "CARD_INSERTED"},
            )

            xml_message = f'<?xml version="1.0" encoding="UTF-8"?>\n{ET.tostring(root, encoding="unicode")}'
            response = await self._send_message(xml_message)

            return self._parse_response(response)
        except Exception as e:
            raise Exception(f"Terminal initialization failed: {e}")

    async def close_terminal(self) -> Dict[str, Any]:
        """Close terminal session"""
        if not self.is_connected:
            return {"success": True, "message": "Already disconnected"}

        try:
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

            xml_message = f'<?xml version="1.0" encoding="UTF-8"?>\n{ET.tostring(root, encoding="unicode")}'
            response = await self._send_message(xml_message)
            parsed = self._parse_response(response)

            if parsed.get("success") and 'ActionCode="APPROVE"' in parsed.get(
                "raw_response", ""
            ):
                await self._cleanup_connection()
                return parsed
            raise Exception("Terminal close failed")
        except Exception as e:
            await self._cleanup_connection()
            raise Exception(f"Failed to close terminal: {e}")

    async def send_purchase_transaction(
        self, transaction_id: str, amount: int, currency_code: str = "840"
    ) -> Dict[str, Any]:
        """Send purchase transaction"""
        try:
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

            xml_message = f'<?xml version="1.0" encoding="UTF-8"?>\n{ET.tostring(root, encoding="unicode")}'
            response = await self._send_message(xml_message)
            return self._parse_response(response)
        except Exception as e:
            raise Exception(f"Purchase transaction failed: {e}")

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Parse XML response from eSocket"""
        try:
            root = ET.fromstring(response)
            return {
                "raw_response": response,
                "success": 'ActionCode="APPROVE"' in response,
            }
        except Exception as e:
            return {
                "raw_response": response,
                "success": False,
                "error": str(e),
            }
