import asyncio
import socket
import struct
import xml.etree.ElementTree as ET
import json
import os
import time
import subprocess
from typing import Any, Dict


class ESocketClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 23001):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.terminal_id = None
        self.is_connected = False
        self.reconnect_attempts = 3  # Add reconnection attempts
        self.reconnect_delay = 1  # Reduced delay for faster reconnection
        self.restart_services = True  # Flag to control service restart behavior
        self._connection_lock = asyncio.Lock()  # Prevent concurrent connection attempts
        self._last_activity = 0  # Track last activity for connection health

    def _load_terminal_id_from_config(self):
        """Load terminal ID from config.json"""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config.json"
        )
        with open(config_path, "r") as f:
            config = json.load(f)
        return config["TERMINAL_ID"]

    async def _restart_esocket_services(self):
        """Restart eSocket services and reload daemon"""
        try:
            print("🔄 Restarting eSocket services...")
            sudo_password = "00000000"

            # ESP services that need to be restarted
            services_to_restart = [
                "espupgmgr.service",
                "espconfigagent.service",
                "esp.service",
            ]

            # First, reload systemd daemon
            print("  📋 Initial systemd daemon reload...")
            process = await asyncio.create_subprocess_exec(
                "sudo",
                "-S",
                "systemctl",
                "daemon-reload",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate(
                input=(sudo_password + "\n").encode()
            )
            if process.returncode == 0:
                print("  ✅ Systemd daemon reloaded successfully")
            else:
                print(f"  ⚠️  Daemon reload warning: {stderr.decode()}")

            for service in services_to_restart:
                try:
                    print(f"  🔄 Attempting to restart {service}...")
                    process = await asyncio.create_subprocess_exec(
                        "sudo",
                        "-S",
                        "systemctl",
                        "restart",
                        service,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await process.communicate(
                        input=(sudo_password + "\n").encode()
                    )
                    if process.returncode == 0:
                        print(f"  ✅ Successfully restarted {service}")
                    else:
                        print(
                            f"  ⚠️  Service {service} failed to restart: {stderr.decode()}"
                        )
                except asyncio.TimeoutError:
                    print(f"  ⏰ Timeout restarting {service}")
                except Exception as e:
                    print(f"  ❌ Error restarting {service}: {e}")

            # Reload systemd daemon after services
            print("  📋 Final systemd daemon reload...")
            process = await asyncio.create_subprocess_exec(
                "sudo",
                "-S",
                "systemctl",
                "daemon-reload",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate(
                input=(sudo_password + "\n").encode()
            )
            if process.returncode == 0:
                print("  ✅ Final systemd daemon reload successful")
            else:
                print(f"  ⚠️  Final daemon reload warning: {stderr.decode()}")

        except Exception as e:
            print(f"❌ Error during service restart: {e}")
            return False

    def _create_message_header(self, message_length: int):
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

    async def connect(self):
        """Establish TCP connection to eSocket.POS with retry logic and improved speed"""
        async with self._connection_lock:
            if self.is_connected and self._is_connection_healthy():
                return True

            # Restart services on first connection attempt if enabled
            if self.restart_services and not self.is_connected:
                print("🔧 Preparing eSocket environment...")
                await self._restart_esocket_services()

            # Only retry if not connected
            for attempt in range(self.reconnect_attempts):
                try:
                    if self.writer:
                        await self.disconnect()  # Clean up any existing connection

                    self.reader, self.writer = await asyncio.wait_for(
                        asyncio.open_connection(self.host, self.port),
                        timeout=5.0,  # Reduced timeout
                    )
                    self.is_connected = True
                    self._last_activity = time.time()
                    print(f"✅ Connected to eSocket.POS at {self.host}:{self.port}")
                    return True
                except Exception as e:
                    print(f"Connection attempt {attempt + 1} failed: {e}")
                    if self.writer:
                        try:
                            self.writer.close()
                            await self.writer.wait_closed()
                        except:
                            pass
                        self.writer = None
                        self.reader = None
                    if attempt < self.reconnect_attempts - 1:
                        await asyncio.sleep(self.reconnect_delay)
                    continue
            self.is_connected = False
            return False

    async def _send_message(self, xml_message: str):
        """Send XML message with improved timeout handling and immediate response"""
        if not self.is_connected or not self.writer:
            if not await self.connect():
                raise Exception("Not connected to eSocket.POS")

        try:
            message_bytes = xml_message.encode("utf-8")
            header = self._create_message_header(len(message_bytes))
            full_message = header + message_bytes

            # Send header + message with error checking
            self.writer.write(full_message)
            await self.writer.drain()
            self._last_activity = time.time()

            # Read response header with reduced timeout for faster response
            response_header = await asyncio.wait_for(
                self.reader.readexactly(2), timeout=10.0  # Reduced from 30s
            )

            # Parse header to get message length
            if response_header == b"\xff\xff":
                # Six-byte header
                length_bytes = await asyncio.wait_for(
                    self.reader.readexactly(4), timeout=10.0
                )
                response_length = struct.unpack(">I", length_bytes)[0]
            else:
                # Two-byte header
                response_length = response_header[0] * 256 + response_header[1]

            # Read response message with timeout
            response_data = await asyncio.wait_for(
                self.reader.readexactly(response_length), timeout=10.0
            )

            self._last_activity = time.time()
            return response_data.decode("utf-8")
        except asyncio.TimeoutError:
            self.is_connected = False
            raise Exception("Operation timed out - connection may be unstable")
        except Exception as e:
            self.is_connected = False
            raise Exception(f"Communication error: {e}")

    async def disconnect(self):
        """Close connection with proper cleanup and immediate response"""
        self.is_connected = False
        if self.writer:
            try:
                self.writer.close()
                await asyncio.wait_for(self.writer.wait_closed(), timeout=2.0)
            except asyncio.TimeoutError:
                print("⚠️ eSocket disconnect timeout")
            except Exception as e:
                print(f"Warning during disconnect: {e}")
            finally:
                self.writer = None
                self.reader = None
        self.terminal_id = None  # Reset terminal ID on disconnect
        self._last_activity = 0

    async def initialize_terminal(
        self, terminal_id: str = None, register_callbacks: bool = True
    ):
        """Initialize terminal with eSocket.POS"""
        # Ensure we have a fresh connection
        if not self.is_connected or not self.writer:
            print("🔌 Establishing connection for terminal initialization...")
            if not await self.connect():
                raise Exception("Cannot initialize terminal - connection failed")

        try:
            if terminal_id is None:
                terminal_id = self._load_terminal_id_from_config()

            self.terminal_id = terminal_id
            print(f"🔧 Initializing terminal {terminal_id}...")

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

            response = await self._send_message(xml_message)
            result = self._parse_response(response)

            if result.get("success"):
                print(f"✅ Terminal {terminal_id} initialized successfully")
            else:
                print(f"❌ Terminal initialization failed: {result}")

            return result
        except Exception as e:
            print(f"❌ Terminal initialization error: {e}")
            # Don't disconnect here - let the caller decide
            raise

    async def close_terminal(self):
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
            response = await self._send_message(xml_message)

            # Parse and validate response
            parsed_response = self._parse_response(response)

            # Check if close was successful
            if parsed_response.get(
                "success"
            ) and 'ActionCode="APPROVE"' in parsed_response.get("raw_response", ""):
                await self.disconnect()  # Ensure we disconnect after closing
                return parsed_response
            else:
                raise Exception("Terminal close failed: " + str(parsed_response))
        except Exception as e:
            await self.disconnect()  # Always try to disconnect on error
            raise Exception(f"Failed to close terminal: {str(e)}")

    async def send_purchase_transaction(
        self, transaction_id: str, amount: int, currency_code: str = "840"
    ):
        """Send purchase transaction with immediate processing (amount in minor denominations)"""
        # Ensure fresh connection for transaction
        if not self._is_connection_healthy():
            await self.connect()

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

        # Send immediately without delay
        response = await self._send_message(xml_message)
        return self._parse_response(response)

    async def send_deposit_transaction(
        self, transaction_id: str, amount: int, currency_code: str = "840"
    ):
        """Send deposit transaction for change disbursement with immediate processing"""
        # Ensure fresh connection for transaction
        if not self._is_connection_healthy():
            await self.connect()

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

        response = await self._send_message(xml_message)
        return self._parse_response(response)

    def _parse_response(self, response: str):
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

    def _is_connection_healthy(self):
        """Check if the connection is still healthy"""
        if not self.writer or self.writer.is_closing():
            return False

        # Check if connection is stale (no activity for 30 seconds)
        current_time = time.time()
        if current_time - self._last_activity > 30:
            return False

        return True
