import threading
import time
from queue import Empty, Queue

import serial

from utils import VMC_COMMANDS


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
        self.command_queue = []
        self.dispense_lock = threading.Lock()
        self.dispensing_active = False
        self.dispense_retry_count = 0
        self.max_dispense_retries = 3

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

        # Initial synchronization (Section 4.4.4)
        self._send_command(VMC_COMMANDS["SYNC_INFO"]["code"])
        self._debug_print("Connection established and synchronized")

    def close(self):
        """Clean shutdown"""
        self.running = False
        if self.poll_thread:
            self.poll_thread.join(timeout=1)
        if self.serial and self.serial.is_open:
            self.serial.close()
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
        """Main communication handling loop"""
        while self.running:
            try:
                data = self.serial.read(1024)
                if data:
                    self.recv_buffer.extend(data)
                    self._process_incoming_data()
                time.sleep(0.01)
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
        self._debug_print(
            f"Received: {cmd_name} ({cmd:02X}), Payload: {payload.hex(' ').upper() if payload else 'none'}"
        )

        # Handle specific commands
        if cmd == VMC_COMMANDS["POLL"]["code"]:
            self._handle_poll(payload)
        elif cmd == VMC_COMMANDS["SELECTION_INFO"]["code"]:
            self._handle_selection_info(payload)
        elif cmd == VMC_COMMANDS["SELECTION_STATUS"]["code"]:
            self._handle_selection_status_response(payload)
        elif cmd == VMC_COMMANDS["DISPENSING_STATUS"]["code"]:
            self._handle_dispensing_status(payload)
        elif cmd == VMC_COMMANDS["SELECT_CANCEL"]["code"]:
            self._handle_selection_cancel(payload)
        elif cmd != VMC_COMMANDS["ACK"]["code"]:
            # For any other non-ACK packet, respond with ACK
            self._send_command(VMC_COMMANDS["ACK"]["code"])

    def _handle_poll(self, payload):
        """Process POLL (0x41) packet and respond within 100ms"""
        self._debug_print("Received POLL from VMC")

        if self.command_queue:
            # Get next command to send
            next_cmd = self.command_queue.pop(0)
            if isinstance(next_cmd, tuple):
                cmd_code, data = next_cmd
                self._send_command(cmd_code, data)
            else:
                self._send_command(next_cmd)
        else:
            # Just respond with ACK if no pending commands
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
            self.current_selection = None
            print("\n🚫 Selection cancelled")
            # Clear any ongoing dispensing
            with self.dispense_lock:
                self.dispensing_active = False
        else:
            self.current_selection = selection
            print(f"\n📦 Selection #{selection} received - checking availability...")
            # Start the proper flow: check status → get product info → payment → dispensing
            self._initiate_purchase_flow(selection)

    def _initiate_purchase_flow(self, selection):
        """Initiate the complete purchase flow: check status → get product info → payment → dispensing"""
        # Step 1: Check selection status first
        self._debug_print(f"Step 1: Checking status for selection #{selection}")
        self.check_selection(selection)

    def _handle_selection_status_response(self, payload):
        """Handle the response from CHECK_SELECTION command"""
        if len(payload) < 4:
            self._debug_print("Invalid SELECTION_STATUS packet length")
            return

        status = payload[1]
        selection = int.from_bytes(payload[2:4], "big")

        self._debug_print(f"Selection #{selection} status: {status}")

        if status == 0x01:  # Normal - product available
            print(f"✅ Product #{selection} is available")
            # Step 2: Get product info from database
            self._get_product_info_from_database(selection)
        elif status == 0x02:  # Out of stock
            print(f"❌ Product #{selection} is out of stock")
            self._cancel_current_selection()
        elif status == 0x03:  # Selection doesn't exist
            print(f"❌ Selection #{selection} doesn't exist")
            self._cancel_current_selection()
        elif status == 0x04:  # Selection pause
            print(f"⏸️ Selection #{selection} is paused")
            self._cancel_current_selection()
        else:
            print(f"⚠️ Selection #{selection} has error status: {status}")
            self._cancel_current_selection()

    def _get_product_info_from_database(self, selection):
        """Get product information from database (currently just logging)"""
        self._debug_print(
            f"Step 2: Getting product info for selection #{selection} from database"
        )

        # TODO: Replace with actual database query
        # For now, just log the operation
        print(f"📋 Getting product info for selection #{selection}...")
        print(f"   - Fetching price from database...")
        print(f"   - Fetching inventory count from database...")
        print(f"   - Fetching product details from database...")

        # Simulate database response - in real implementation, check actual availability
        product_available = True  # This should come from database query

        if product_available:
            print(f"💰 Product #{selection} info retrieved successfully")
            # Step 3: Process payment
            self._process_payment_for_selection(selection)
        else:
            print(f"❌ Product #{selection} not found in database")
            self._cancel_current_selection()

    def _process_payment_for_selection(self, selection):
        """Process payment for the selected product"""
        self._debug_print(f"Step 3: Processing payment for selection #{selection}")

        # Start the dispensing process with payment handling
        self._start_dispensing(selection)

    def _cancel_current_selection(self):
        """Cancel the current selection and send cancel command to VMC"""
        if self.current_selection:
            selection = self.current_selection
            self.current_selection = None
            print(f"🚫 Cancelling selection #{selection}")
            self.cancel_selection()

    def _handle_dispensing_status(self, payload):
        """Process DISPENSING_STATUS (0x04) packet without retry logic"""
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
            status_code, f"❌ Unknown error (code: {status_code}) - dispensing cancelled"
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
                print(f"🚫 Dispensing cancelled for product #{selection}. Please contact support if needed.")

        # If dispensing is complete (success or failure), reset current selection
        if not self.dispensing_active:
            self.current_selection = None

        # Acknowledge receipt of dispensing status
        self._send_command(VMC_COMMANDS["ACK"]["code"])

    def _start_dispensing(self, selection):
        """Start the dispensing process with proper thread management"""
        # Make sure we're not already dispensing
        with self.dispense_lock:
            if self.dispensing_active:
                self._debug_print("Dispensing already in progress, ignoring request")
                return
            self.dispensing_active = True
            self.dispense_retry_count = 0

        # Start the dispensing thread
        threading.Thread(
            target=self._handle_payment, args=(selection,), daemon=True
        ).start()

    def _handle_payment(self, selection):
        """Wait for 2 seconds and then drive dispensing manually with retry logic"""
        try:
            self._debug_print(f"Step 4: Processing payment for selection #{selection}")
            print(f"💳 Processing payment for product #{selection}...")
            time.sleep(2)  # Simulate payment processing delay

            self._debug_print(
                f"Payment successfully verified for selection #{selection}"
            )
            print(f"✅ Payment verified for product #{selection}")

            # Step 5: Start dispensing
            self._debug_print(f"Step 5: Starting dispensing for selection #{selection}")
            self.direct_drive_selection(selection, True, True)

        except Exception as e:
            self._debug_print(f"Error during payment: {str(e)}")
            with self.dispense_lock:
                self.dispensing_active = False

    def queue_command(self, command_name, data=None):
        """Queue a command to be sent when next POLL is received"""
        if command_name in VMC_COMMANDS:
            cmd_code = VMC_COMMANDS[command_name]["code"]
            if data:
                self.command_queue.append((cmd_code, data))
            else:
                self.command_queue.append(cmd_code)
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
