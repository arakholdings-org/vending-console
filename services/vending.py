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
            timeout=0,
        )
        self.packet_number = 1
        self.running = False
        self.poll_thread = None
        self.debug = debug
        self.STX = bytes([0xFA, 0xFB])
        self.print_ack_packets = False

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
        # start of packet
        stx = self.STX
        cmd = bytes([command])

        # creating packet body using data length

        if data:
            length = len(data) + 1
            packet_body = bytes([length]) + bytes([self.packet_number]) + data
        else:

            length = 1
            packet_body = bytes([length]) + bytes([self.packet_number])

        # XOR checksum is calculated on STX + CMD + + Packet Body
        xor_data = stx + cmd + packet_body
        xor = 0
        for b in xor_data:
            xor ^= b

        packet = xor_data + bytes([xor])

        self.packet_number = (self.packet_number % 255) + 1

        return packet

    def send_packet(self, packet):
        """Send a packet and wait for response"""

        self.serial.write(packet)

        return None

    def _read_single_packet(self):
        """Read a single complete packet from serial buffer"""
        # Read STX (2 bytes)
        if self.serial.in_waiting < 2:
            return None

        stx = self.serial.read(2)
        if stx != self.STX:
            self._debug_print(f"Invalid STX: {stx.hex()}")
            return None

        # Read command and length
        if self.serial.in_waiting < 2:
            return None

        cmd_len = self.serial.read(2)
        command = cmd_len[0]
        length = cmd_len[1]

        remaining_bytes = length + 1
        if self.serial.in_waiting < remaining_bytes:
            return None

        remaining_data = self.serial.read(remaining_bytes)

        complete_packet = stx + cmd_len + remaining_data

        return complete_packet

    # haandlers for incoming data from the VMC
    def _selection_info_handler(self, data):
        """Handle incoming selection info"""

        print("\n🛒 RECEIVED SELECTION INFO FROM VMC:")

    def _select_cancel_handler(self, data):
        """Handle the keypad selection and cancel"""

        if len(data) >= 8:
            selection_number = int.from_bytes(data[5:7], "big")
            if selection_number == 0:
                print("\n🚫 SELECTION CANCELLED BY USER")
            else:

                print(f"\n🛒 PRODUCT #{selection_number} SELECTED ON VMC KEYPAD")

    def _process_single_packet(self, data):
        """Process a single complete packet"""
        if not data or len(data) < 5 or data[0:2] != self.STX:
            return

        command = data[2]

        # handling the incoming commands from the vending machine

        if command == VMC_COMMANDS["POLL"]["code"]:
            return

        if command == VMC_COMMANDS["SELECTION_INFO"]["code"]:

            self._selection_info_handler(data)

        if command == VMC_COMMANDS["SELECT_CANCEL"]["code"]:

            self._select_cancel_handler(data)

    def process_poll(self):
        """Process all incoming data from VMC"""
        while self.serial.in_waiting >= 5:  # Minimum packet size
            packet = self._read_single_packet()
            if not packet:
                break

            self._process_single_packet(packet)

    def close(self):
        """Close the serial connection and stop polling"""
        self.stop_polling()
        if self.serial.is_open:
            self.serial.close()
            self._debug_print("Serial connection closed")
