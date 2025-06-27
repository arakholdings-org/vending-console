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
            # The length byte is the length of the data payload plus the packet number byte.
            length = len(data) + 1
            packet_body = bytes([length]) + bytes([self.packet_number]) + data
        else:
            # If no data, length is 1 (for the packet number)
            length = 1
            packet_body = bytes([length]) + bytes([self.packet_number])

        # XOR checksum is calculated on STX + CMD + + Packet Body
        xor_data = stx + cmd + packet_body
        xor = 0
        for b in xor_data:
            xor ^= b

        packet = xor_data + bytes([xor])  # <-- Fix: append XOR as a single byte

        # Increment packet number for next packet (1-255)
        self.packet_number = (self.packet_number % 255) + 1

        return packet

    def send_packet(self, packet):
        """Send a packet and wait for response"""
        # Log outgoing packet
        cmd_type = packet[2] if len(packet) > 2 else "Unknown"
        is_ack_packet = cmd_type == VMC_COMMANDS["ACK"]["code"]

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

    def initiate_purchase(self, selection_number):
        """Start the purchase process for a selection"""
        command = VMC_COMMANDS["SELECT_TO_BUY"]["code"]
        data = selection_number.to_bytes(2, "big")
        packet = self.create_packet(command, data)
        self.send_packet(packet)
        return True, "Purchase initiated"

    def _get_status_message(self, status):
        """Convert status code to human readable message"""
        status_messages = {
            0x00: "Normal",
            0x01: "Selection pause",
            0x02: "Out of stock",
            0x03: "Selection doesn't exist",
            # ... add other status codes
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
            self.process_poll()
            time.sleep(0.01)  # Minimal sleep to prevent CPU hogging

    def get_selection(self, selection_number):
        """
        Send a Menu Command (0x70) with sub-command 0x42 to fetch the selection query configuration for a given selection number.
        Packet structure (see docs/vending.md 4.5.11):
        [STX][CMD=0x70][LEN=5][PACKNO][CMD_TYPE=0x42][OP_TYPE=0x00][SELECTION(2)][XOR]
        Args:
            selection_number (int): The selection number to query (1-1000)
        """
        self._debug_print(
            f"Fetching selection query configuration for #{selection_number}..."
        )
        # Build data payload: sub-command 0x42 + selection number (2 bytes, big endian)
        data_payload = bytes([0x42, 0x00]) + selection_number.to_bytes(2, "big")
        # Create packet with Menu Command (0x70)
        packet = self.create_packet(VMC_COMMANDS["MENU_COMMAND"]["code"], data_payload)
        # Send packet
        self.send_packet(packet)

    def _parse_menu_response(self, data):
        """
        Parse a Menu Response (0x71) for selection configuration (0x42).
        Extracts price and updates cache.
        """
        # Minimum length: STX(2) + CMD(1) + LEN(1) + PACKNO(1) + CMD_TYPE(1) + OP_TYPE(1) + PRICE(4) + ...
        if len(data) < 12:
            return
        if data[2] != VMC_COMMANDS["MENU_RESPONSE"]["code"]:
            return
        # Check if this is a selection config response (CMD_TYPE == 0x42, OP_TYPE == 0x00)
        cmd_type = data[5]
        op_type = data[6]
        if cmd_type == 0x42 and op_type == 0x00:
            # Extract selection number from request (not in response, so use current_selection)
            selection_number = self.current_selection
            # Extract price (4 bytes, big endian)
            price = int.from_bytes(data[7:11], "big")
            self.product_prices[selection_number] = price
            self.current_price = price
            print(
                f"\n💲 PRICE FOR SELECTION #{selection_number}: {self.format_price(price)}"
            )
            # Optionally, extract inventory, capacity, etc. as needed

    def _parse_selection_info(self, data):
        """
        Parse VMC Reports Selection Info (0x11) and print details.
        Structure:
        [STX(2)][CMD(1)][LEN(1)][PACKNO(1)][SELECTION(2)][PRICE(4)][INVENTORY(1)][CAPACITY(1)][PRODUCT_ID(2)][STATUS(1)][XOR(1)]
        """
        if len(data) < 17:
            return
        selection_number = int.from_bytes(data[5:7], "big")
        price = int.from_bytes(data[7:11], "big")
        inventory = data[11]
        capacity = data[12]
        product_id = int.from_bytes(data[13:15], "big")
        status = data[15]
        print(
            f"\n[SELECTION INFO] Selection: {selection_number}, Price: ${price/100:.2f}, "
            f"Inventory: {inventory}, Capacity: {capacity}, Product ID: {product_id}, Status: {status}"
        )

    def process_poll(self):
        """Process incoming data from VMC"""
        if not self.serial.in_waiting:
            return

        data = self.serial.read(self.serial.in_waiting)
        if not data or len(data) < 5 or data[0:2] != self.STX:
            return

        command = data[2]

        # Always acknowledge VMC-originated packets (see vending.md)
        if command in (
            VMC_COMMANDS["POLL"]["code"],
            VMC_COMMANDS["SELECTION_INFO"]["code"],
            VMC_COMMANDS["MENU_RESPONSE"]["code"],
            VMC_COMMANDS["SELECTION_STATUS"]["code"],
            VMC_COMMANDS["DISPENSING_STATUS"]["code"],
            VMC_COMMANDS["SELECT_CANCEL"]["code"],
            # ...add any other VMC-originated commands as needed...
        ):
            ack_packet = self.create_packet(VMC_COMMANDS["ACK"]["code"])
            self.serial.write(ack_packet)

        # If POLL, just ACK and return (see vending.md, Process 1)
        if command == VMC_COMMANDS["POLL"]["code"]:
            return

        # Handle SELECTION_INFO (0x11)
        if command == VMC_COMMANDS["SELECTION_INFO"]["code"]:
            self._parse_selection_info(data)

        # Parse MENU_RESPONSE (0x71) for selection price
        if command == VMC_COMMANDS["MENU_RESPONSE"]["code"]:
            self._parse_menu_response(data)

        # Handle VMC Select/Cancel Selection command (0x05)
        if command == VMC_COMMANDS["SELECT_CANCEL"]["code"]:
            if len(data) >= 8:  # STX+CMD+LEN+PACKNO+DATA(2)+XOR
                selection_number = int.from_bytes(data[5:7], "big")
                if selection_number == 0:
                    print("\n🚫 SELECTION CANCELLED BY USER")
                else:
                    self.current_selection = selection_number
                    print(f"\n🛒 PRODUCT #{selection_number} SELECTED ON VMC KEYPAD")
                    # Optionally query selection info if you want price/inventory
                    # self.get_selection(selection_number)
                    # Dispense item directly after selection (see 4.3.5)
                    self.direct_drive_dispense(selection_number)

        # Handle VMC Dispensing Status command
        elif command == VMC_COMMANDS["DISPENSING_STATUS"]["code"]:
            if len(data) >= 8:
                status = data[5]
                selection_number = int.from_bytes(data[6:8], "big")
                if status == 0x02:  # Dispensed successfully
                    print(f"\n✅ SUCCESS: PRODUCT #{selection_number} DISPENSED")
                    self.payment_success = True
                else:  # Handle errors
                    print(
                        f"\n❌ DISPENSING ERROR FOR #{selection_number}: STATUS {hex(status)}"
                    )

    def close(self):
        """Close the serial connection and stop polling"""
        self.stop_polling()
        if self.serial.is_open:
            self.serial.close()
            self._debug_print("Serial connection closed")

    def format_price(self, price):
        """Format price in cents to dollars"""
        if price is None:
            return "N/A"
        return f"${price/100:.2f}"

    def direct_drive_dispense(self, selection_number, drop_sensor=1, elevator=1):
        """
        Dispense item directly using the direct drive command (0x06).
        Args:
            selection_number (int): The selection number to dispense.
            drop_sensor (int): 1 to enable drop sensor, 0 to disable.
            elevator (int): 1 to enable elevator, 0 to disable.
        """
        command = VMC_COMMANDS["DIRECT_DRIVE"]["code"]
        # Data: [drop_sensor (1 byte)] + [elevator (1 byte)] + [selection_number (2 bytes, big endian)]
        data = bytes([drop_sensor, elevator]) + selection_number.to_bytes(2, "big")
        packet = self.create_packet(command, data)
        self.send_packet(packet)
