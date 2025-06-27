import serial
import time
import threading
import binascii
from utils import VMC_COMMANDS


class VendingMachine:
    def __init__(self, port="/dev/ttyUSB0", debug=False):
        self.serial = serial.Serial(
            port=port,
            baudrate=57600,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=0,  # Non-blocking read
        )
        self.packet_number = 1
        self.running = False
        self.poll_thread = None
        self._selection_callback = None
        self.debug = debug
        # Initialize STX bytes as per protocol
        self.STX = bytes([0xFA, 0xFB])
        # Disable printing of common packets
        self.print_ack_packets = False
        # Track selection and price information
        self.current_selection = None
        self.current_price = None
        self.product_prices = {}  # Cache product prices

        # Track payment status
        self.payment_success = False
        self.payment_amount = 0

    def _debug_print(self, *args):
        """Print debug information if debug is enabled"""
        if self.debug:
            print(*args)

    def _print_hex(self, data, prefix="", force_print=False):
        """Print data in hexadecimal format for debugging"""
        if (self.debug and data) and (force_print or self.print_ack_packets):
            hex_data = binascii.hexlify(data).decode("ascii")
            formatted = " ".join(
                hex_data[i : i + 2] for i in range(0, len(hex_data), 2)
            ).upper()
            print(f"{prefix}{formatted}")

    def create_packet(self, command, data=None):
        """Create a packet according to the protocol"""
        stx = self.STX  # Start of packet
        cmd = bytes([command])

        if data:
            length = len(data) + 1  # +1 for packet number
            packet = stx + cmd + bytes([length]) + bytes([self.packet_number]) + data
        else:
            packet = stx + cmd + bytes([1]) + bytes([self.packet_number])

        # Calculate XOR
        xor = 0
        for b in packet:
            xor ^= b

        packet += bytes([xor])

        # Increment packet number for next packet (1-255)
        self.packet_number = (self.packet_number % 255) + 1

        return packet

    def send_packet(self, packet):
        """Send a packet and wait for response"""
        # Log outgoing packet
        cmd_type = packet[2] if len(packet) > 2 else "Unknown"

        # Determine if this is an ACK packet
        is_ack_packet = cmd_type == VMC_COMMANDS["ACK"]["code"]

        # Only log non-ACK packets or if ACK printing is enabled
        if not is_ack_packet or self.print_ack_packets:
            cmd_name = next(
                (
                    name
                    for name, details in VMC_COMMANDS.items()
                    if details.get("code") == cmd_type
                ),
                "Unknown",
            )
            self._debug_print(f"\n>> SENDING {cmd_name} PACKET:")
            self._print_hex(packet, ">> ", force_print=not is_ack_packet)

        self.serial.write(packet)

        # For menu commands, wait a bit longer for response
        if cmd_type == 0x70:  # Menu command
            time.sleep(0.1)  # Wait 100ms for menu response

        # Try multiple times to get response
        for i in range(10):  # Try for up to 1 second
            if self.serial.in_waiting:
                response = self.serial.read(self.serial.in_waiting)
                if response and (not is_ack_packet or self.print_ack_packets):
                    self._debug_print(f"<< RECEIVED RESPONSE:")
                    self._print_hex(response, "<< ", force_print=True)
                return response
            time.sleep(0.1)  # Wait 100ms between checks

        return None

    def _parse_selection_status(self, response):
        """Parse selection status response"""
        if (
            len(response) >= 7
            and response[0:2] == self.STX  # Verify STX
            and response[2] == VMC_COMMANDS["SELECTION_STATUS"]["code"]
        ):
            status = response[4]
            return status
        return None

    def handle_payment(self, selection_number):
        """Handle payment processing and initiate product dispensing"""
        # Get selection info including price
        selection_info = self.get_price(selection_number)

        if not selection_info:
            print(
                f"❌ Could not get price information for selection {selection_number}"
            )
            return False

        required_price = selection_info["price"]
        inventory = selection_info["inventory"]

        # Check if product is available
        if inventory <= 0:
            print(f"❌ Product #{selection_number} is out of stock")
            return False

        # Store current selection and price
        self.current_selection = selection_number
        self.current_price = required_price

        # Check if we have sufficient payment
        if self.payment_amount * 100 >= required_price:
            print(f"✅ Sufficient payment received. Dispensing product...")

            # Send purchase command directly
            command = VMC_COMMANDS["SELECT_TO_BUY"]["code"]
            data = selection_number.to_bytes(2, "big")
            packet = self.create_packet(command, data)
            self.send_packet(packet)

            return True
        else:
            needed_amount = (required_price / 100.0) - self.payment_amount
            print(f"💸 Insufficient payment. Need additional: ${needed_amount:.2f}")
            print("💰 Please insert more money...")
            return True  # Payment process continues

    def initiate_purchase(self, selection_number):
        """Start the purchase process for a selection"""
        # Send purchase command directly
        command = VMC_COMMANDS["SELECT_TO_BUY"]["code"]
        data = selection_number.to_bytes(2, "big")
        packet = self.create_packet(command, data)
        response = self.send_packet(packet)
        return True, "Purchase initiated"

    def _get_status_message(self, status):
        """Convert status code to human readable message"""
        status_messages = {
            0x00: "Normal",
            0x01: "Selection pause",
            0x02: "Out of stock",
            0x03: "Selection doesn't exist",
            0x04: "Selection pause",
            0x05: "Product inside elevator",
            0x06: "Delivery door unlocked",
            0x07: "Elevator error",
            0x08: "Elevator self-checking faulty",
            # Add other status codes as needed
        }
        return status_messages.get(status, f"Unknown status: {hex(status)}")

    def start_polling(self):
        """Start the polling thread"""
        self.running = True
        self.poll_thread = threading.Thread(target=self._polling_loop)
        self.poll_thread.daemon = True
        self.poll_thread.start()
        self._debug_print("Polling thread started")

    def stop_polling(self):
        """Stop the polling thread"""
        self.running = False
        if self.poll_thread:
            self.poll_thread.join()
            self._debug_print("Polling thread stopped")

    def _polling_loop(self):
        """Main polling loop that runs in a separate thread"""
        while self.running:
            # Process poll continuously without interval timing
            self.process_poll()
            # Minimal sleep to prevent CPU hogging
            time.sleep(0.001)

    def validate_packet(self, data):
        """Validate packet structure and checksum"""
        if len(data) < 5:  # STX(2) + CMD(1) + LEN(1) + XOR(1) minimum
            return False, "Packet too short"

        if data[0:2] != self.STX:
            return False, f"Invalid STX: {data[0:2].hex()}, expected: {self.STX.hex()}"

        # Check packet length
        length = data[3]
        expected_length = length + 4  # STX(2) + CMD(1) + LEN(1) + DATA(length) + XOR(1)

        if len(data) != expected_length:
            return (
                False,
                f"Invalid packet length: got {len(data)}, expected {expected_length}",
            )

        # Validate XOR checksum
        calculated_xor = 0
        for i in range(len(data) - 1):
            calculated_xor ^= data[i]

        if calculated_xor != data[-1]:
            return (
                False,
                f"Invalid checksum: {hex(data[-1])}, calculated: {hex(calculated_xor)}",
            )

        return True, "Valid packet"

    def check_selection(self, selection_number):
        """Check selection status according to 4.3.1"""
        # Send check selection command (0x01)
        command = 0x01
        data = selection_number.to_bytes(2, "big")
        packet = self.create_packet(command, data)
        response = self.send_packet(packet)

        if response and len(response) >= 7:
            # Verify response: STX(2) + CMD(0x02) + LEN(1) + PackNO(1) + Status(1) + Selection(2)
            if (
                response[0:2] == self.STX and response[2] == 0x02
            ):  # Selection status response
                status = response[4]
                return status
        return None

    def process_poll(self):
        """Process POLL command and other incoming data from VMC"""
        if not self.serial.in_waiting:
            return False

        # Read available data
        data = self.serial.read(self.serial.in_waiting)

        # Skip empty data
        if not data:
            return False

        # Need at least 5 bytes for a valid packet
        if len(data) < 5:
            return False

        # Check if this is a valid packet
        if data[0:2] != self.STX:
            # Only log invalid data if it's not noise and debug is on
            if len(data) > 2 and self.debug:
                self._debug_print("Invalid STX bytes, ignoring data")
                self._print_hex(data, "<< ", force_print=True)
            return False

        command = data[2]

        # Always acknowledge all valid commands from VMC silently
        if command != VMC_COMMANDS["ACK"]["code"]:  # Don't ACK an ACK
            ack_packet = self.create_packet(VMC_COMMANDS["ACK"]["code"])
            self.serial.write(ack_packet)

        # Handle VMC Select/Cancel Selection command (0x05)
        if command == VMC_COMMANDS["SELECT_CANCEL"]["code"]:
            if len(data) >= 7:
                selection_number = int.from_bytes(data[5:7], "big")

                if selection_number == 0:
                    print("\n🚫 SELECTION CANCELLED")
                    self.current_selection = None
                    self.current_price = None
                else:
                    # Set current selection
                    self.current_selection = selection_number

                    # Query price using menu command (0x70/0x42)
                    price = self.get_selection_price(selection_number)

                    print(f"\n🛒 PRODUCT SELECTED: #{selection_number}")
                    print(
                        f"   → Price: {self.format_price(price) if price is not None else 'N/A'}"
                    )

                    # Send MONEY_RECEIVED (0x27) to VMC with the queried price
                    money_received_cmd = VMC_COMMANDS["MONEY_RECEIVED"]["code"]
                    mode = 1  # Payment mode (1: Bill)
                    amount_bytes = (price if price is not None else 0).to_bytes(
                        4, "big"
                    )
                    data_bytes = bytes([mode]) + amount_bytes
                    packet = self.create_packet(money_received_cmd, data_bytes)
                    self.send_packet(packet)

                    ack_packet = self.create_packet(VMC_COMMANDS["ACK"]["code"])
                    self.serial.write(ack_packet)

                    # Initiate dispensing
                    self.dispense_directly(selection_number)

                    ack_packet = self.create_packet(VMC_COMMANDS["ACK"]["code"])
                    self.serial.write(ack_packet)

            return True

        # Handle VMC Dispensing Status command - this indicates dispensing progress
        elif command == VMC_COMMANDS["DISPENSING_STATUS"]["code"]:
            if len(data) >= 6:
                status = data[4]
                selection_number = (
                    int.from_bytes(data[5:7], "big") if len(data) >= 7 else 0
                )

                # Only show successful dispensing or errors
                if status == 0x02:  # Dispensed successfully
                    price_info = (
                        f" - PRICE: {self.format_price(self.current_price)}"
                        if self.current_price is not None
                        else ""
                    )
                    print(
                        f"\n✅ PAYMENT SUCCESSFUL - PRODUCT #{selection_number}{price_info} DISPENSED"
                    )
                    self.payment_success = True
                elif status == 0xFF:  # Purchase terminated
                    print(f"\n🛑 PURCHASE TERMINATED FOR PRODUCT #{selection_number}")
                elif status in [0x03, 0x04, 0x06, 0x07]:  # Error codes
                    status_msg = self._get_status_message(status)
                    print(f"\n❌ DISPENSING ERROR: {status_msg}")
            return True

        # For all other commands, only print if debug is enabled
        elif self.debug:
            cmd_name = next(
                (
                    name
                    for name, details in VMC_COMMANDS.items()
                    if details.get("code") == command
                ),
                f"Unknown (0x{command:02X})",
            )
            self._debug_print(f"Received command: {cmd_name}")

        return True

    def handle_selection(self, selection_number):
        """Handle a selection received from the VMC"""
        if selection_number == 0:
            print("Selection cancelled")
            return

        # First check if selection is available
        status = self.check_selection(selection_number)
        if status != 0x01:  # If not normal
            print(
                f"Selection {selection_number} error: {self._get_status_message(status)}"
            )
            return

        # Initiate the purchase
        success, message = self.initiate_purchase(selection_number)
        if success:
            print(f"Processing selection {selection_number}...")
        else:
            print(f"Error processing selection {selection_number}: {message}")

    def set_selection_callback(self, callback):
        """Set callback function to handle selection events from VMC"""
        self._selection_callback = callback

    def close(self):
        """Close the serial connection and stop polling"""
        self.stop_polling()
        if self.serial.is_open:
            self.serial.close()
            self._debug_print("Serial connection closed")

    def dispense_directly(self, selection_number, drop_sensor=1, elevator=1):
        """Dispense product directly using command 0x06 (DIRECT_DRIVE)"""
        command = VMC_COMMANDS["DIRECT_DRIVE"]["code"]
        # Data: [drop_sensor (1)] + [elevator (1)] + [selection_number (2)]
        data = bytes([drop_sensor, elevator]) + selection_number.to_bytes(2, "big")
        packet = self.create_packet(command, data)
        response = self.send_packet(packet)
        if self.debug:
            print(
                f"\n>> DISPENSE DIRECTLY: selection={selection_number}, drop_sensor={drop_sensor}, elevator={elevator}"
            )
        return response

    def get_selection_price(self, selection_number):
        """
        Query the price of a selection using menu command 0x70 with sub-command 0x42.

        Args:
            selection_number (int): The selection ID to query (1-1000)

        Returns:
            int: Price in smallest currency unit (e.g., cents), or None if failed
        """
        # Create the query packet
        query_packet = self.create_packet(
            command=VMC_COMMANDS["MENU_COMMAND"]["code"],  # 0x70
            data=bytes([0x42, 0x00])
            + selection_number.to_bytes(2, "big"),  # 0x42 (query config) + selection
        )

        # Send and receive response
        response = self.send_packet(query_packet)

        ack_packet = self.create_packet(VMC_COMMANDS["ACK"]["code"])
        self.serial.write(ack_packet)

        # Parse valid response (STX + 0x71 + length + PackNO + 0x42 + 0x00 + price(4) + ...)
        if response and len(response) >= 13:
            if (
                response[0:2] == self.STX
                and response[2] == VMC_COMMANDS["MENU_RESPONSE"]["code"]  # 0x71
                and response[4] == 0x42  # Should match our query type
                and response[5] == 0x00
            ):  # Should match our operation type

                # Extract price (4 bytes starting at position 6)
                return int.from_bytes(response[6:10], "big")

        if self.debug:
            print(f"Failed to get price for selection {selection_number}")
        return None

    def create_menu_packet(self, command_type, params=None):
        """Create a menu command packet (0x70) with command type and parameters as per protocol."""
        stx = self.STX
        cmd = bytes([VMC_COMMANDS["MENU_COMMAND"]["code"]])
        # Always include communication number (packet_number)
        data = bytes([self.packet_number]) + bytes([command_type])
        if params:
            data += params
        length = len(data)
        packet = stx + cmd + bytes([length]) + data
        # Calculate XOR
        xor = 0
        for b in packet:
            xor ^= b
        packet += bytes([xor])
        # Increment packet number for next packet (1-255)
        self.packet_number = (self.packet_number % 255) + 1
        return packet

    def format_price(self, price):
        """Format price in cents to dollars"""
        if price is None:
            return "N/A"
        return f"${price/100:.2f}"
