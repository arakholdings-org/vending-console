import asyncio
import serial_asyncio
from utils import VMC_COMMANDS


class VendingMachine:
    def __init__(self, port="/dev/ttyUSB0", debug=False):
        self.port = port
        self.debug = debug
        self.STX = bytes([0xFA, 0xFB])  # Start of packet
        self.packet_number = 1
        self.running = False
        self.reader = None
        self.writer = None
        self.poll_task = None
        self.current_selection = None
        self.product_info = (
            {}
        )  # Stores selection info {selection: {price, inventory, etc.}}

    def _debug_print(self, *args):
        """Print debug information if debug is enabled"""
        if self.debug:
            print(*args)

    def create_packet(self, command, data=None):
        """Create a protocol-compliant packet"""
        packet = self.STX + bytes([command])

        if data:
            length = len(data) + 1  # +1 for packet number
            packet += bytes([length]) + bytes([self.packet_number]) + data
        else:
            packet += bytes([1]) + bytes([self.packet_number])  # Just packet number

        # Calculate XOR checksum
        xor = 0
        for b in packet:
            xor ^= b
        packet += bytes([xor])

        # Increment packet number (1-255)
        self.packet_number = (self.packet_number % 255) + 1

        return packet

    async def send_packet(self, packet):
        """Send a packet and wait for it to be written"""
        if not self.writer:
            raise RuntimeError("Not connected")
        self.writer.write(packet)
        await self.writer.drain()

    async def connect(self):
        """Establish serial connection"""
        self.reader, self.writer = await serial_asyncio.open_serial_connection(
            url=self.port,
            baudrate=57600,
            parity=serial_asyncio.serial.PARITY_NONE,
            stopbits=serial_asyncio.serial.STOPBITS_ONE,
            bytesize=serial_asyncio.serial.EIGHTBITS,
        )
        self.running = True
        self.poll_task = asyncio.create_task(self._polling_loop())
        self._debug_print("Connected to", self.port)

    async def close(self):
        """Cleanly close the connection"""
        self.running = False
        if self.poll_task:
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self._debug_print("Connection closed")

    async def _polling_loop(self):
        """Main polling loop to process incoming data"""
        while self.running:
            try:
                data = await asyncio.wait_for(self.reader.read(1024), timeout=0.1)
                if data:
                    await self._process_data(data)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self._debug_print("Polling error:", str(e))
                break

    async def _process_data(self, data):
        """Process incoming data packets"""

        # Validate minimum packet length and STX
        if len(data) < 5 or data[0:2] != self.STX:
            return

        command = data[2]
        length = data[3]

        # Validate packet length
        if len(data) < 4 + length + 1:  # STX(2)+CMD(1)+LEN(1)+DATA+XOR(1)
            self._debug_print("Invalid packet length")
            return

        # Validate XOR checksum
        xor = 0
        for b in data[:-1]:
            xor ^= b
        if xor != data[-1]:
            self._debug_print("Invalid checksum")
            return

        # Always ACK valid packets (except ACK itself)
        if command != VMC_COMMANDS["ACK"]["code"]:
            ack_packet = self.create_packet(VMC_COMMANDS["ACK"]["code"])
            await self.send_packet(ack_packet)

        # Handle SELECTION_INFO (0x11)
        if command == VMC_COMMANDS["SELECTION_INFO"]["code"] and length >= 12:
            await self._handle_selection_info(data[4:-1])  # Exclude STX,CMD,LEN,XOR

        # Handle SELECT/CANCEL (0x05)
        elif command == VMC_COMMANDS["SELECT_CANCEL"]["code"] and length >= 2:
            await self._handle_selection_cancel(data[4:-1])

    async def request_sync(self):
        """Send info synchronization request (0x31)"""
        packet = self.create_packet(0x31)
        await self.send_packet(packet)
        self._debug_print("Sent info sync request (0x31)")

    async def _handle_selection_info(self, payload):
        """Process SELECTION_INFO (0x11) packets"""
        selection = int.from_bytes(payload[1:3], "big")  # Skip packet number
        price = int.from_bytes(payload[3:7], "big")
        inventory = payload[7]
        capacity = payload[8]
        product_id = int.from_bytes(payload[9:11], "big")
        status = payload[11]

        # Store the information
        self.product_info[selection] = {
            "price": price,
            "inventory": inventory,
            "capacity": capacity,
            "product_id": product_id,
            "status": status,
        }

        print(
            f"\n[Selection Info] #{selection}: "
            f"Price: {price/100:.2f}, "
            f"Stock: {inventory}/{capacity}, "
            f"PID: {product_id}, "
            f"Status: {self._get_status_name(status)}"
        )

        # Immediately request info sync after receiving selection info
        await self.request_sync()

    async def _handle_selection_cancel(self, payload):
        """Process SELECT/CANCEL (0x05) packets"""
        selection = int.from_bytes(payload[1:3], "big")  # Skip packet number

        if selection == 0:
            self.current_selection = None
            print("\n🚫 Selection cancelled")
        else:
            self.current_selection = selection

            print("selection selected:", selection)

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
