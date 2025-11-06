import asyncio
import json
import os
import struct
import time
import xml.etree.ElementTree as ET
from typing import Dict, Any


class ESocketClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 23001):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.terminal_id = None
        self.is_connected = False
        self._last_activity = 0
        self._reconnect_delay = 5  # seconds
        self._max_reconnect_delay = 60  # seconds

    def _load_terminal_id(self):
        """Load terminal ID from config file"""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config.json"
        )
        try:
            with open(config_path, "r") as f:
                return json.load(f)["TERMINAL_ID"]
        except Exception as e:
            raise Exception(f"Failed to load terminal ID: {e}")

    async def connect(self):
        """Simulate connection to eSocket server"""
        if self.is_connected:
            return True

        # Simulate connection success
        self.is_connected = True
        self._last_activity = time.time()
        print(f"Simulated connection to eSocket at {self.host}:{self.port}")
        return True

    async def disconnect(self):
        """Simulate disconnect from eSocket server"""
        await self._cleanup_connection()

    async def _cleanup_connection(self):
        """Clean up any existing connection"""
        self.is_connected = False
        self.writer = None
        self.reader = None

    def _create_message_header(self, message_length: int):
        """Create TCP message header based on length"""
        if message_length < 65535:
            return struct.pack("BB", message_length // 256, message_length % 256)
        return b"\xff\xff" + struct.pack(">I", message_length)

    async def _send_message(self, xml_message: str):
        """Simulate sending XML message and receiving response"""
        # Simulate a delay
        await asyncio.sleep(0.1)
        # Always return a simulated approved response
        simulated_response = '''<?xml version="1.0" encoding="UTF-8"?>
<Esp:Interface Version="1.0" xmlns:Esp="http://www.mosaicsoftware.com/Postilion/eSocket.POS/">
    <Esp:Response ActionCode="APPROVE" />
</Esp:Interface>'''
        return simulated_response

    async def initialize_terminal(self, terminal_id: str = None):
        """Simulate initialize terminal session"""
        try:
            if not terminal_id:
                terminal_id = self._load_terminal_id()

            self.terminal_id = terminal_id

            # Simulate success
            response = await self._send_message("")
            return self._parse_response(response)
        except Exception as e:
            raise Exception(f"Terminal initialization failed: {e}")

    async def close_terminal(self) -> Dict[str, Any]:
        """Simulate close terminal session"""
        if not self.is_connected:
            return {"success": True, "message": "Already disconnected"}

        try:
            response = await self._send_message("")
            parsed = self._parse_response(response)

            if parsed.get("success"):
                await self._cleanup_connection()
                return parsed
            raise Exception("Terminal close failed")
        except Exception as e:
            await self._cleanup_connection()
            raise Exception(f"Failed to close terminal: {e}")

    async def send_purchase_transaction(
        self, transaction_id: str, amount: int, currency_code: str = "840"
    ):
        """Simulate send purchase transaction"""
        try:
            # Simulate payment processing with 5 second delay
            await asyncio.sleep(5)

            # Always approve
            response = await self._send_message("")
            return self._parse_response(response)
        except Exception as e:
            raise Exception(f"Purchase transaction failed: {e}")

    async def send_reversal_transaction(
        self, transaction_id: str, original_transaction_id: str, reason_code: str = None
    ):
        """Simulate send reversal transaction"""
        try:
            # Simulate reversal processing
            await asyncio.sleep(1)

            # Always approve
            response = await self._send_message("")
            return self._parse_response(response)
        except Exception as e:
            raise Exception(f"Reversal transaction failed: {e}")

    def _parse_response(self, response: str):
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
