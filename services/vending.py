import threading
import time
from queue import Empty, Queue

import serial

from utils import VMC_COMMANDS
from services.esocket import ESocketClient


class VendingMachine:
    def __init__(self, port="/dev/ttyUSB0", debug=False):
        self.port = port
        self.debug = debug
        self.STX = bytes([0xFA, 0xFB])
        self.packet_number = 1
        self.running = False
        self.serial = None
        self.poll_thread = None
        self.current_selection = None
        self._command_lock = threading.Lock()
        self.recv_buffer = bytearray()
        self.dispense_lock = threading.Lock()
        self.dispensing_active = False

        # Initialize command queue with retry tracking
        self.command_queue = Queue()
        self._command_retries = {}  # Track retries per command
        self.MAX_RETRIES = 5  # According to protocol spec
        self.last_command_time = 0  # Track last command time

        # Initialize eSocket client
        self.esocket_client = ESocketClient()
        self.esocket_connected = False

        # Thread management
        self.threads = {
            "poll": None,
            "monitor": None,
        }

        # State management
        self.state = {
            "machine": "idle",
            "payment": "idle",
            "dispensing": False,
        }

        # Timeouts
        self.timeouts = {
            "poll": 0.1,  # 100ms
            "payment": 30.0,  # 30s
            "dispense": 60.0,  # 60s
        }

    def _debug_print(self, *args):
        if self.debug:
            print(*args)

    def connect(self):
        """Establish connection and initialize communication"""
        self.serial = serial.Serial(
            port=self.port,
            baudrate=57600,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=0.1,
        )
        self.running = True
        self.poll_thread = threading.Thread(
            target=self._communication_loop, daemon=True
        )
        self.poll_thread.start()

        # Initialize eSocket connection synchronously
        self._initialize_esocket()

        # Initial synchronization (Section 4.4.4)
        self._send_command(VMC_COMMANDS["SYNC_INFO"]["code"])
        self._debug_print("Connection established and synchronized")

    def _initialize_esocket(self):
        """Initialize eSocket connection synchronously"""
        try:
            print("🔌 Connecting to payment terminal...")
            if self.esocket_client.connect():
                print("✅ Connected to payment terminal")
                try:
                    # Add small delay to ensure connection is stable
                    time.sleep(0.5)
                    self.esocket_client.initialize_terminal()
                    self.esocket_connected = True
                    print("✅ Payment terminal initialized successfully")
                    self._debug_print("eSocket connection established")
                except Exception as e:
                    print(f"❌ Failed to initialize payment terminal: {e}")
                    self.esocket_connected = False
                    # Try to disconnect cleanly on initialization failure
                    try:
                        self.esocket_client.disconnect()
                    except:
                        pass
            else:
                print("❌ Failed to connect to payment terminal")
                self.esocket_connected = False
        except Exception as e:
            print(f"❌ Payment terminal connection error: {e}")
            self.esocket_connected = False
            # Ensure clean state on error
            try:
                self.esocket_client.disconnect()
            except:
                pass

    def close(self):
        """Clean shutdown"""
        self.running = False
        if self.poll_thread:
            self.poll_thread.join(timeout=1)
        if self.serial and self.serial.is_open:
            self.serial.close()

        # Close eSocket connection
        if self.esocket_connected:
            try:
                self.esocket_client.close_terminal()
                self.esocket_client.disconnect()
            except:
                pass

        self._debug_print("Connection closed")

    def create_packet(self, command, data=None):
        """Create a protocol-compliant packet with XOR checksum"""
        packet = self.STX + bytes([command])

        if data:
            packet += bytes([len(data) + 1])  # +1 for packet number
            packet += bytes([self.packet_number]) + data
        else:
            packet += bytes([1]) + bytes([self.packet_number])  # Just packet number

        # Calculate XOR
        xor = 0
        for b in packet:
            xor ^= b
        packet += bytes([xor])

        # Increment packet number (1-255)
        self.packet_number = (self.packet_number % 255) + 1
        return packet

    def _send_command(self, command, data=None):
        """Send a command"""
        with self._command_lock:
            packet = self.create_packet(command, data)
            self.serial.write(packet)
            self.serial.flush()
            self._debug_print(f"Sent: {packet.hex(' ').upper()}")
            return True

    def _communication_loop(self):
        """Main communication handling loop with timeout"""
        last_poll_time = time.time()

        while self.running:
            try:
                # Check if we missed polls
                current_time = time.time()
                if current_time - last_poll_time > 0.5:  # 500ms without poll
                    self._debug_print("Warning: Possible missed POLL")

                data = self.serial.read(1024)
                if data:
                    self.recv_buffer.extend(data)
                    self._process_incoming_data()
                    last_poll_time = current_time

                time.sleep(0.01)  # 10ms sleep to prevent CPU thrashing

            except Exception as e:
                self._debug_print(f"Communication error: {str(e)}")
                break

    def _process_incoming_data(self):
        """Process all available incoming data"""
        while len(self.recv_buffer) >= 5:  # Minimum packet size
            packet, remaining = self._extract_packet(self.recv_buffer)
            if not packet:
                break

            self._handle_packet(packet)
            self.recv_buffer = bytearray(remaining)

    def _extract_packet(self, data):
        """Extract a complete packet from raw data"""
        # Find STX marker
        stx_pos = data.find(self.STX)
        if stx_pos == -1:
            return None, b""

        data = data[stx_pos:]  # Skip bytes before STX

        if len(data) < 5:  # STX(2) + CMD(1) + LEN(1) + XOR(1)
            return None, data  # Wait for more data

        cmd = data[2]
        length = data[3]
        packet_end = 4 + length + 1  # STX(2)+CMD(1)+LEN(1)+DATA+XOR(1)

        if len(data) < packet_end:
            return None, data  # Wait for more data

        packet = data[:packet_end]
        remaining = data[packet_end:]

        # Verify XOR
        xor = 0
        for b in packet[:-1]:
            xor ^= b
        if xor != packet[-1]:
            self._debug_print(f"Invalid checksum in packet: {packet.hex(' ')}")
            # Remove STX and try to resync
            return None, data[2:]

        return packet, remaining

    def _handle_packet(self, packet):
        """Handle a single validated packet"""
        cmd = packet[2]
        payload = packet[4:-1]  # Skip STX, CMD, LEN, XOR

        # Log packet information
        cmd_name = next(
            (k for k, v in VMC_COMMANDS.items() if v["code"] == cmd),
            f"UNKNOWN_CMD_{cmd:02X}",
        )

        # Handle specific commands
        if cmd == VMC_COMMANDS["POLL"]["code"]:
            self._handle_poll(payload)
        elif cmd == VMC_COMMANDS["SELECTION_INFO"]["code"]:
            self._handle_selection_info(payload)
        elif cmd == VMC_COMMANDS["DISPENSING_STATUS"]["code"]:
            self._handle_dispensing_status(payload)
        elif cmd == VMC_COMMANDS["SELECT_CANCEL"]["code"]:
            self._handle_selection_cancel(payload)
        elif cmd != VMC_COMMANDS["ACK"]["code"]:
            # For any other non-ACK packet, respond with ACK
            self._send_command(VMC_COMMANDS["ACK"]["code"])

    def _handle_poll(self, payload):
        """Process POLL (0x41) packet and respond within 100ms"""
        try:
            current_time = time.time()

            # Check if we have commands to process
            if not self.command_queue.empty():
                # Ensure we're not responding too quickly (protocol requires 200ms between polls)
                if current_time - self.last_command_time < 0.2:  # 200ms
                    self._send_command(VMC_COMMANDS["ACK"]["code"])
                    return

                next_cmd = self.command_queue.get_nowait()
                cmd_id = id(next_cmd)  # Use command object id as unique identifier

                # Check retry count
                retries = self._command_retries.get(cmd_id, 0)
                if retries >= self.MAX_RETRIES:
                    self._debug_print(
                        f"Maximum retries reached for command: {next_cmd}"
                    )
                    self._command_retries.pop(cmd_id, None)
                    self._send_command(VMC_COMMANDS["ACK"]["code"])
                    return

                # Send command
                if isinstance(next_cmd, tuple):
                    cmd_code, data = next_cmd
                    success = self._send_command(cmd_code, data)
                else:
                    success = self._send_command(next_cmd)

                if not success:
                    # Put command back in queue for retry
                    self._command_retries[cmd_id] = retries + 1
                    self.command_queue.put(next_cmd)
                else:
                    # Command sent successfully, reset retry counter
                    self._command_retries.pop(cmd_id, None)
                    self.last_command_time = current_time
            else:
                self._send_command(VMC_COMMANDS["ACK"]["code"])
        except Empty:
            self._send_command(VMC_COMMANDS["ACK"]["code"])
        except Exception as e:
            self._debug_print(f"Poll handling error: {e}")
            self._send_command(VMC_COMMANDS["ACK"]["code"])

    def _handle_selection_info(self, payload):
        """Process SELECTION_INFO (0x11) packet"""
        if len(payload) < 7:
            self._debug_print("Invalid SELECTION_INFO packet length")
            return

        # Acknowledge receipt of selection info
        self._send_command(VMC_COMMANDS["ACK"]["code"])

    def _handle_selection_cancel(self, payload):
        """Process SELECT/CANCEL (0x05) packet"""
        if len(payload) < 2:
            self._debug_print("Invalid SELECT_CANCEL packet length")
            return

        selection = int.from_bytes(payload[1:3], "big")
        if selection == 0:
            # Only process cancel if we have an active selection
            if self.current_selection is not None:
                self.current_selection = None
                print("\n🚫 Selection cancelled")
                # Clear any ongoing dispensing
                with self.dispense_lock:
                    self.dispensing_active = False
        else:
            # Only process selection if we don't already have one
            if self.current_selection is None:
                self.current_selection = selection
                print(f"\n📦 Selection #{selection} received - processing payment...")
                # Directly handle payment after selection
                self._handle_payment(selection)
            else:
                self._debug_print(
                    f"Ignoring selection {selection}, already processing {self.current_selection}"
                )

    def _handle_payment(self, selection):
        """Process payment synchronously instead of using a separate thread"""
        try:
            if not self.esocket_connected:
                print("⚠️ Payment terminal not connected, attempting to reconnect...")
                self._initialize_esocket()

            # Generate transaction ID
            timestamp_mod = int(time.time()) % 900000
            transaction_id = str(100000 + timestamp_mod)[:6]

            amount = 200  # $2.00 in cents
            print(f"💰 Processing ${amount/100:.2f} payment... (TXN: {transaction_id})")

            with self._command_lock:  # Prevent concurrent payment processing
                response = self.esocket_client.send_purchase_transaction(
                    transaction_id=transaction_id, amount=amount
                )

            if self._is_payment_successful(response):
                print("✅ Payment approved!")
                with self.dispense_lock:
                    if (
                        self.current_selection == selection
                    ):  # Verify selection hasn't changed
                        self.dispensing_active = True
                        self.direct_drive_selection(selection, True, True)
                    else:
                        print("❌ Selection changed during payment processing")
                        self._cancel_current_selection()
            else:
                print("❌ Payment declined")
                self._cancel_current_selection()

        except Exception as e:
            print(f"❌ Payment error: {e}")
            self._cancel_current_selection()

    def _handle_dispensing_status(self, payload):
        """Process DISPENSING_STATUS (0x04) packet"""
        if len(payload) < 2:
            self._debug_print("Invalid DISPENSING_STATUS packet length")
            return

        status_code = payload[1]
        selection = self.current_selection

        # Update status codes according to documentation section 4.3.3
        status_messages = {
            0x00: f"🎉 Product #{selection} dispensed successfully!",
            0x01: f"🔄 Product #{selection} dispensing...",
            0x02: f"🎉 Product #{selection} dispensed successfully!",
            0x03: f"❌ Product #{selection} selection jammed - dispensing cancelled",
            0x04: f"❌ Product #{selection} motor error - dispensing cancelled",
            0x06: f"❌ Product #{selection} motor doesn't exist - dispensing cancelled",
            0x07: f"❌ Product #{selection} elevator error - dispensing cancelled",
            0xFF: f"❌ Product #{selection} purchase terminated",
        }

        success = status_code == 0x02

        message = status_messages.get(
            status_code,
            f"❌ Unknown error (code: {status_code}) - dispensing cancelled",
        )
        print(message)

        # Handle dispensing completion
        with self.dispense_lock:
            if status_code == 0x01:
                # Still dispensing, wait for next status update
                pass
            elif success:
                # Successful dispensing
                self.dispensing_active = False
                print(f"✅ Transaction completed for product #{selection}")
            else:
                # Any error - cancel dispensing immediately
                self.dispensing_active = False
                print(
                    f"🚫 Dispensing cancelled for product #{selection}. Please contact support if needed."
                )

        # If dispensing is complete (success or failure), reset current selection
        if not self.dispensing_active:
            self.current_selection = None

        # Acknowledge receipt of dispensing status
        self._send_command(VMC_COMMANDS["ACK"]["code"])

    def _cancel_current_selection(self):
        """Cancel the current selection and send cancel command to VMC"""
        if self.current_selection:
            selection = self.current_selection
            self.current_selection = None
            print(f"🚫 Cancelling selection #{selection}")
            self.cancel_selection()

    def _is_payment_successful(self, response):
        """Check if the payment response indicates success"""
        try:
            # Check if response contains success indicators
            if isinstance(response, dict):
                # Check for success flag
                if response.get("success", False):
                    # Parse the XML response to check for approval
                    raw_response = response.get("raw_response", "")
                    if 'ActionCode="APPROVE"' in raw_response:
                        return True
                    elif 'ActionCode="DECLINE"' in raw_response:
                        # Extract error message for better debugging
                        if 'Description="' in raw_response:
                            start = raw_response.find('Description="') + 13
                            end = raw_response.find('"', start)
                            error_msg = raw_response[start:end]
                            print(f"Payment declined: {error_msg}")
                        return False
                return False

            # If response is a string, check for approval indicators
            if isinstance(response, str):
                return 'ActionCode="APPROVE"' in response

            self._debug_print(f"Payment response: {response}")
            return False

        except Exception as e:
            self._debug_print(f"Error parsing payment response: {e}")
            return False

    def queue_command(self, command_name, data=None):
        """Queue a command to be sent when next POLL is received"""
        if command_name in VMC_COMMANDS:
            cmd_code = VMC_COMMANDS[command_name]["code"]
            if data:
                self.command_queue.put(
                    (cmd_code, data)
                )  # Use .put() instead of .append()
            else:
                self.command_queue.put(cmd_code)
            self._debug_print(f"Command {command_name} queued for next POLL")
            return True
        else:
            self._debug_print(f"Unknown command: {command_name}")
            return False

    def check_selection(self, selection_number):
        """Queue a command to check selection status"""
        data = selection_number.to_bytes(2, byteorder="big")
        return self.queue_command("CHECK_SELECTION", data)

    def buy_selection(self, selection_number):
        """Queue a command to buy a selection"""
        data = selection_number.to_bytes(2, byteorder="big")
        return self.queue_command("SELECT_TO_BUY", data)

    def direct_drive_selection(
        self, selection_number, use_drop_sensor=True, use_elevator=True
    ):
        """Queue a command to directly drive a selection motor"""
        data = bytes([1 if use_drop_sensor else 0, 1 if use_elevator else 0])
        data += selection_number.to_bytes(2, byteorder="big")
        return self.queue_command("DIRECT_DRIVE", data)

    def cancel_selection(self):
        """Queue a command to cancel current selection"""
        data = (0).to_bytes(2, byteorder="big")
        return self.queue_command("SELECT_CANCEL", data)

    def request_machine_status(self):
        """Queue a command to request machine status"""
        return self.queue_command("MACHINE_STATUS_REQ")
