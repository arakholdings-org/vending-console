import threading
import time
import serial
from queue import Queue, Empty
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
        self.product_info = {}
        self._response_queue = Queue()
        self._command_lock = threading.Lock()
        self.recv_buffer = bytearray()

    def _debug_print(self, *args):
        if self.debug:
            print(*args)

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

        # Always ACK non-ACK packets (Section 2)
        if cmd != VMC_COMMANDS["ACK"]["code"]:
            self._send_command(VMC_COMMANDS["ACK"]["code"])

        # Handle specific commands
        handler_map = {
            VMC_COMMANDS["SELECTION_INFO"]["code"]: self._handle_selection_info,
            VMC_COMMANDS["SELECT_CANCEL"]["code"]: self._handle_selection_cancel,
            VMC_COMMANDS["DISPENSING_STATUS"]["code"]: self._handle_dispensing_status,
            VMC_COMMANDS["POLL"]["code"]: self._handle_poll,
        }

        handler = handler_map.get(cmd)
        if handler:
            handler(payload)

    def _send_command(self, command, data=None, timeout=1.0):
        """Send a command and wait for response"""
        with self._command_lock:
            packet = self.create_packet(command, data)
            self.serial.write(packet)
            self.serial.flush()
            self._debug_print(f"Sent: {packet.hex(' ').upper()}")
            # For most commands, just return after sending (no response expected)
            # If you want to wait for a response, use self._response_queue.get(timeout=timeout)
            return True

    def _handle_selection_info(self, payload):
        """Process SELECTION_INFO (0x11) packet"""
        if len(payload) < 12:
            self._debug_print("Invalid SELECTION_INFO packet length")
            return

        selection = int.from_bytes(payload[1:3], "big")
        price = int.from_bytes(payload[3:7], "big")
        inventory = payload[7]
        capacity = payload[8]
        product_id = int.from_bytes(payload[9:11], "big")
        status = payload[11]

        self.product_info[selection] = {
            "price": price,
            "inventory": inventory,
            "capacity": capacity,
            "product_id": product_id,
            "status": status,
        }

        # Ensure all values are numeric for formatting
        print(
            f"\n[UPDATE] Selection #{selection}: "
            f"Price: {float(price)/100:.2f} "
            f"Stock: {int(inventory)}/{int(capacity)} "
            f"(Status: {self._get_status_name(status)})"
        )

    def _handle_selection_cancel(self, payload):
        """Process SELECT/CANCEL (0x05) packet"""
        if len(payload) < 2:
            self._debug_print("Invalid SELECT_CANCEL packet length")
            return

        selection = int.from_bytes(payload[1:3], "big")
        if selection == 0:
            self.current_selection = None
            print("\n🚫 Selection cancelled")
        else:
            self.current_selection = selection
            info = self.product_info.get(selection, {})
            price = info.get("price", 0)
            inventory = info.get("inventory", 0)
            capacity = info.get("capacity", 0)
            # Ensure all values are numeric for formatting
            print(
                f"\n🛒 Selected #{selection}: "
                f"{float(price)/100:.2f} "
                f"({int(inventory)}/{int(capacity)})"
            )

    def _handle_dispensing_status(self, payload):
        """Process DISPENSING_STATUS (0x04) packet"""
        if len(payload) < 3:
            self._debug_print("Invalid DISPENSING_STATUS packet length")
            return

        status = payload[1]
        selection = int.from_bytes(payload[2:4], "big") if len(payload) >= 4 else 0

        status_messages = {
            0x02: f"✅ Dispensed #{selection} successfully",
            0xFF: f"❌ Failed to dispense #{selection}",
            0x03: f"⚠️ Selection #{selection} jammed",
            0x04: f"⚠️ Motor didn't stop normally for #{selection}",
        }

        if status in status_messages:
            print(f"\n{status_messages[status]}")
        else:
            print(f"\nUnknown dispensing status {status:02X} for #{selection}")

    def _handle_poll(self, payload):
        """Process POLL (0x41) packet"""
        self._debug_print("Received POLL from VMC")
        # According to protocol, upper computer should respond within 100ms
        self._send_command(VMC_COMMANDS["ACK"]["code"])

    def _get_status_name(self, status_code):
        """Convert status code to human-readable name"""
        statuses = {
            0x00: "Normal",
            0x01: "Paused",
            0x02: "Out of Stock",
            0x03: "Does Not Exist",
            0x04: "Error",
        }
        return statuses.get(status_code, f"Unknown ({hex(status_code)})")

    def request_selection_info(self, selection_number):
        """Request specific selection info (using menu command)"""
        if not 1 <= selection_number <= 1000:
            raise ValueError("Selection number must be 1-1000")

        # Use menu command 0x70 with sub-command 0x42
        data = bytes([0x42, 0x00]) + selection_number.to_bytes(2, "big")
        self._send_command(VMC_COMMANDS["MENU_COMMAND"]["code"], data)
        # If you
