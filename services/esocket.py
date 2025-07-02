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
        self.socket = None
        self.terminal_id = None
        self.is_connected = False
        self.reconnect_attempts = 3  # Add reconnection attempts
        self.reconnect_delay = 2  # seconds
        self.restart_services = True  # Flag to control service restart behavior

    def _load_terminal_id_from_config(self):
        """Load terminal ID from config.json"""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config.json"
        )
        with open(config_path, "r") as f:
            config = json.load(f)
        return config["TERMINAL_ID"]

    def _restart_esocket_services(self):
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
            daemon_result = subprocess.run(
                ["sudo", "-S", "systemctl", "daemon-reload"],
                input=sudo_password + "\n",
                check=False,
                capture_output=True,
                text=True,
            )
            if daemon_result.returncode == 0:
                print("  ✅ Systemd daemon reloaded successfully")
            else:
                print(f"  ⚠️  Daemon reload warning: {daemon_result.stderr}")

            for service in services_to_restart:
                try:
                    print(f"  🔄 Attempting to restart {service}...")
                    result = subprocess.run(
                        ["sudo", "-S", "systemctl", "restart", service],
                        input=sudo_password + "\n",
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        print(f"  ✅ Successfully restarted {service}")

                    else:
                        print(
                            f"  ⚠️  Service {service} failed to restart: {result.stderr}"
                        )
                except subprocess.TimeoutExpired:
                    print(f"  ⏰ Timeout restarting {service}")
                except Exception as e:
                    print(f"  ❌ Error restarting {service}: {e}")

            # Reload systemd daemon after services
            print("  📋 Final systemd daemon reload...")
            final_daemon_result = subprocess.run(
                ["sudo", "-S", "systemctl", "daemon-reload"],
                input=sudo_password + "\n",
                check=False,
                capture_output=True,
                text=True,
            )
            if final_daemon_result.returncode == 0:
                print("  ✅ Final systemd daemon reload successful")
            else:
                print(f"  ⚠️  Final daemon reload warning: {final_daemon_result.stderr}")

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

    def connect(self):
        """Establish TCP connection to eSocket.POS with retry logic"""
        # Restart services on first connection attempt if enabled
        if self.restart_services and not self.is_connected:
            print("🔧 Preparing eSocket environment...")
            self._restart_esocket_services()

        for attempt in range(self.reconnect_attempts):
            try:
                if self.socket:
                    self.disconnect()  # Clean up any existing connection

                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(10)  # Add timeout

                # Enable socket reuse to prevent "Address already in use" errors
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

                self.socket.connect((self.host, self.port))
                self.is_connected = True
                print(f"✅ Connected to eSocket.POS at {self.host}:{self.port}")
                return True
            except Exception as e:
                print(f"Connection attempt {attempt + 1} failed: {e}")
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
                if attempt < self.reconnect_attempts - 1:
                    time.sleep(self.reconnect_delay)
                continue
        self.is_connected = False
        return False

    def _send_message(self, xml_message: str):
        """Send XML message with timeout handling"""
        if not self.is_connected or not self.socket:
            if not self.connect():
                raise Exception("Not connected to eSocket.POS")

        try:
            # Verify socket is still valid
            self.socket.settimeout(30)  # 30 seconds timeout

            message_bytes = xml_message.encode("utf-8")
            header = self._create_message_header(len(message_bytes))
            full_message = header + message_bytes

            # Send header + message with error checking
            total_sent = 0
            while total_sent < len(full_message):
                try:
                    sent = self.socket.send(full_message[total_sent:])
                    if sent == 0:
                        raise Exception("Socket connection broken during send")
                    total_sent += sent
                except socket.error as e:
                    if e.errno == 9:  # Bad file descriptor
                        self.is_connected = False
                        raise Exception(f"Socket closed unexpectedly: {e}")
                    raise

            # Read response header with timeout
            response_header = b""
            while len(response_header) < 2:
                try:
                    chunk = self.socket.recv(2 - len(response_header))
                    if not chunk:
                        raise Exception("Connection closed while reading header")
                    response_header += chunk
                except socket.error as e:
                    if e.errno == 9:  # Bad file descriptor
                        self.is_connected = False
                        raise Exception(f"Socket closed during header read: {e}")
                    raise

            # Parse header to get message length
            if response_header == b"\xff\xff":
                # Six-byte header
                length_bytes = self.socket.recv(4)
                if len(length_bytes) < 4:
                    raise Exception("Failed to read extended header")
                response_length = struct.unpack(">I", length_bytes)[0]
            else:
                # Two-byte header
                response_length = response_header[0] * 256 + response_header[1]

            # Read response message in chunks
            response_data = b""
            while len(response_data) < response_length:
                try:
                    chunk = self.socket.recv(response_length - len(response_data))
                    if not chunk:
                        raise Exception("Connection closed while reading response")
                    response_data += chunk
                except socket.error as e:
                    if e.errno == 9:  # Bad file descriptor
                        self.is_connected = False
                        raise Exception(f"Socket closed during response read: {e}")
                    raise

            return response_data.decode("utf-8")
        except socket.timeout:
            self.is_connected = False
            raise Exception("Operation timed out")
        except socket.error as e:
            self.is_connected = False
            raise Exception(f"Socket error: {e}")
        except Exception as e:
            self.is_connected = False
            raise

        except socket.error as e:
            self.is_connected = False
            raise Exception(f"Socket error: {e}")

    def disconnect(self):
        """Close connection with proper cleanup"""
        self.is_connected = False
        if self.socket:
            try:
                # Try to shutdown gracefully first
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    # Socket might already be closed, continue with close()
                    pass
                self.socket.close()
            except Exception as e:
                print(f"Warning during disconnect: {e}")
            finally:
                self.socket = None
        self.terminal_id = None  # Reset terminal ID on disconnect

    def initialize_terminal(
        self, terminal_id: str = None, register_callbacks: bool = True
    ):
        """Initialize terminal with eSocket.POS"""
        # Ensure we have a fresh connection
        if not self.is_connected or not self.socket:
            print("🔌 Establishing connection for terminal initialization...")
            if not self.connect():
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

            response = self._send_message(xml_message)
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

    def close_terminal(self):
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
            if parsed_response.get(
                "success"
            ) and 'ActionCode="APPROVE"' in parsed_response.get("raw_response", ""):
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
