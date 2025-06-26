import serial
import time
import threading
import binascii
from utils.commands import VMC_COMMANDS


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

        if self.serial.in_waiting:
            response = self.serial.read(self.serial.in_waiting)
            if response and (not is_ack_packet or self.print_ack_packets):
                self._debug_print(f"<< RECEIVED RESPONSE:")
                self._print_hex(response, "<< ", force_print=True)
            return response
        return None

    def check_selection(self, selection_number):
        """Check if a selection is available"""
        command = VMC_COMMANDS["CHECK_SELECTION"]["code"]
        data = selection_number.to_bytes(2, "big")
        packet = self.create_packet(command, data)
        response = self.send_packet(packet)
        return self._parse_selection_status(response) if response else None

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

    def initiate_purchase(self, selection_number):
        """Start the purchase process for a selection"""
        # First check selection status
        status = self.check_selection(selection_number)
        if status != 0x01:  # If not normal
            return False, self._get_status_message(status)

        # Send purchase command
        command = VMC_COMMANDS["SELECT_TO_BUY"]["code"]
        data = selection_number.to_bytes(2, "big")
        packet = self.create_packet(command, data)
        response = self.send_packet(packet)

        return True, "Purchase initiated"

    def _get_status_message(self, status):
        """Convert status code to human readable message"""
        status_messages = {
            0x01: "Normal",
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

    def get_product_price(self, selection_number):
        """Get the price of a product by selection number"""
        # Check if we have the price cached
        if selection_number in self.product_prices:
            return self.product_prices[selection_number]

        # We need to send a command to request selection info
        # According to vending.md section 4.2.1, we need to use the SELECTION_INFO command
        # But the protocol doesn't define a direct way for upper computer to request this

        # Instead, we'll use check_selection first to confirm the product exists
        status = self.check_selection(selection_number)
        if status != 0x01:  # Not normal
            return None

        # If the product exists, we'll parse selection info if VMC sends it
        # This is a placeholder for when we receive the SELECTION_INFO from VMC
        # The price will be updated when we receive a SELECTION_INFO packet

        return None

    def format_price(self, price_value):
        """Format price value into a display string"""
        if price_value is None:
            return "Unknown"

        # According to vending.md, price is a 4-byte value
        # Convert from cents (or smallest unit) to display currency
        price_decimal = price_value / 100.0
        return f"${price_decimal:.2f}"

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

        # Handle specific commands that need to be displayed to the user

        # VMC Select/Cancel Selection command
        if command == VMC_COMMANDS["SELECT_CANCEL"]["code"]:
            if (
                len(data) >= 7
            ):  # Command(1) + Length(1) + PackNo(1) + Selection(2) + XOR(1)
                selection_number = int.from_bytes(data[4:6], "big")

                if selection_number == 0:
                    print("\n🚫 SELECTION CANCELLED")
                    self.current_selection = None
                    self.current_price = None
                else:
                    # Get product price and details
                    self.current_selection = selection_number

                    # Check if selection is valid and get price
                    status = self.check_selection(selection_number)
                    if status == 0x01:  # Normal
                        # Try to get price information
                        price = self.get_product_price(selection_number)
                        self.current_price = price

                        if price is not None:
                            print(
                                f"\n🛒 PRODUCT SELECTED: #{selection_number} - PRICE: {self.format_price(price)}"
                            )
                        else:
                            print(f"\n🛒 PRODUCT SELECTED: #{selection_number}")

                        if self._selection_callback:
                            self._selection_callback(selection_number)
                        else:
                            # If no callback, process selection immediately
                            self.handle_selection(selection_number)
                    else:
                        status_msg = self._get_status_message(status)
                        print(f"\n⚠️ SELECTION ERROR #{selection_number}: {status_msg}")
                        self.current_selection = None
            return True

        # Process SELECTION_INFO command to get product details
        elif command == VMC_COMMANDS["SELECTION_INFO"]["code"]:
            # According to section 4.2.1, selection info includes:
            # selection number (2) + price (4) + inventory (1) + capacity (1) + product ID (2) + status (1)
            if len(data) >= 13:  # Including header and packet number
                selection_number = int.from_bytes(data[4:6], "big")
                price = int.from_bytes(data[6:10], "big")
                inventory = data[10]
                status = data[13]

                # Store price in our price cache
                self.product_prices[selection_number] = price

                # If this is the current selection, update the displayed price
                if (
                    selection_number == self.current_selection
                    and price != self.current_price
                ):
                    self.current_price = price
                    print(
                        f"\nℹ️ PRODUCT #{selection_number} PRICE: {self.format_price(price)}"
                    )

                self._debug_print(
                    f"Received selection info - Selection: {selection_number}, "
                    f"Price: {self.format_price(price)}, Inventory: {inventory}"
                )
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

        # Handle money collection notice
        elif command == VMC_COMMANDS["MONEY_NOTICE"]["code"]:
            if len(data) >= 10:  # Ensure we have enough data for the payment info
                mode = data[4]
                amount_bytes = data[5:9]
                amount = (
                    int.from_bytes(amount_bytes, "big") / 100.0
                )  # Convert to decimal

                mode_names = {
                    1: "Bill",
                    2: "Coin",
                    3: "IC Card",
                    4: "Bank Card",
                    5: "WeChat",
                    6: "AliPay",
                    7: "JD Pay",
                    9: "Union Pay",
                }
                mode_name = mode_names.get(mode, "Unknown")

                print(f"\n💰 PAYMENT RECEIVED: {mode_name} - Amount: ${amount:.2f}")
                self.payment_amount = amount

                # If we have a current product selected and price available, show how much more is needed
                if (
                    self.current_selection
                    and self.current_price
                    and amount < self.current_price
                ):
                    remaining = self.current_price - amount
                    print(f"   Still needed: ${remaining/100.0:.2f}")
            return True

        # Handle current amount report
        elif command == VMC_COMMANDS["CURRENT_AMOUNT"]["code"]:
            if len(data) >= 9:
                amount_bytes = data[4:8]
                amount = int.from_bytes(amount_bytes, "big") / 100.0

                if amount > 0:
                    print(f"\n💲 CURRENT BALANCE: ${amount:.2f}")
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
