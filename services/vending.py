import asyncio

import time
from asyncio import Queue
import serial_asyncio
from utils import VMC_COMMANDS
from services.esocket import ESocketClient


class VendingMachine:
    def __init__(self, port="/dev/ttyUSB0", debug=False):
        self.port = port
        self.debug = debug
        self.STX = bytes([0xFA, 0xFB])
        self.packet_number = 1
        self.running = False
        self.reader = None
        self.writer = None
        self.current_selection = None
        self.recv_buffer = bytearray()
        self.dispensing_active = False

        # Command queue
        self.command_queue = Queue()
        self.MAX_RETRIES = 5
        self.last_command_time = 0

        # Payment terminal
        self.esocket_client = ESocketClient()
        self.esocket_connected = False

        # Simple state tracking
        self.state = "idle"  # idle, selecting, paying, dispensing

    def log(self, *args):
        if self.debug:
            print(*args)

    async def connect(self):
        """Establish serial connection and initialize payment terminal"""
        try:
            self.reader, self.writer = await serial_asyncio.open_serial_connection(
                url=self.port,
                baudrate=57600,
                parity="N",
                stopbits=1,
                bytesize=8,
            )
            self.running = True

            # Initialize payment terminal
            try:
                await self.esocket_client.connect()
                await self.esocket_client.initialize_terminal()
                self.esocket_connected = True
                self.log("Payment terminal initialized")
            except Exception as e:
                self.log(f"Payment terminal init failed: {e}")
                self.esocket_connected = False

            # Start communication task
            asyncio.create_task(self._communication_loop())
            self.log("Connection established")

        except Exception as e:
            self.log(f"Connection failed: {e}")
            raise

    async def close(self):
        """Clean shutdown"""
        self.running = False

        # Close serial connection
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except:
                pass

        # Close payment terminal
        if self.esocket_connected:
            try:
                await self.esocket_client.close_terminal()
                await self.esocket_client.disconnect()
            except:
                pass

        self.log("Shutdown complete")

    def _calculate_xor(self, data):
        """Calculate XOR checksum"""
        xor_value = 0
        for b in data:
            xor_value ^= b
        return xor_value

    def create_packet(self, command, data=None):
        """Create protocol packet with checksum"""
        packet = self.STX + bytes([command])

        if data:
            packet += bytes([len(data) + 1])  # +1 for packet number
            packet += bytes([self.packet_number]) + data
        else:
            packet += bytes([1]) + bytes([self.packet_number])

        # Add checksum
        packet += bytes([self._calculate_xor(packet)])

        # Increment packet number (1-255)
        self.packet_number = (self.packet_number % 255) + 1
        return packet

    async def _send_command(self, command, data=None):
        """Send a command to the machine"""
        packet = self.create_packet(command, data)
        self.writer.write(packet)
        await self.writer.drain()
        self.log(f"Sent: {packet.hex(' ').upper()}")
        self.last_command_time = time.time()

    async def _communication_loop(self):
        """Handle incoming data and process commands"""
        while self.running:
            try:
                # Process incoming data
                try:
                    data = await asyncio.wait_for(self.reader.read(1024), timeout=0.1)
                    if data:
                        self.recv_buffer.extend(data)
                        await self._process_incoming_data()
                except asyncio.TimeoutError:
                    pass

                # Process queued commands
                if not self.command_queue.empty():
                    cmd = await self.command_queue.get()
                    (
                        await self._send_command(*cmd)
                        if isinstance(cmd, tuple)
                        else await self._send_command(cmd)
                    )

                await asyncio.sleep(0.01)  # Prevent CPU overload

            except Exception as e:
                self.log(f"Communication error: {e}")
                if not self.running:
                    break
                await asyncio.sleep(0.1)

    async def _process_incoming_data(self):
        """Process all available data in buffer"""
        while len(self.recv_buffer) >= 5:  # Minimum packet size
            packet, remaining = self._extract_packet(self.recv_buffer)
            if not packet:
                break

            await self._handle_packet(packet)
            self.recv_buffer = remaining

    def _extract_packet(self, data):
        """Extract complete packet from raw data"""
        stx_pos = data.find(self.STX)
        if stx_pos == -1:
            return None, data

        data = data[stx_pos:]  # Skip bytes before STX

        if len(data) < 5:  # Minimum packet size
            return None, data

        cmd = data[2]
        length = data[3]
        packet_end = 4 + length + 1  # Header + data + checksum

        if len(data) < packet_end:
            return None, data

        packet = data[:packet_end]
        remaining = data[packet_end:]

        # Verify checksum
        if self._calculate_xor(packet[:-1]) != packet[-1]:
            self.log(f"Invalid checksum in packet: {packet.hex(' ')}")
            return None, data[2:]  # Skip bad STX and resync

        return packet, remaining

    async def _handle_packet(self, packet):
        """Handle a single validated packet"""
        cmd = packet[2]
        payload = packet[4:-1]  # Skip header and checksum

        # Handle specific commands
        if cmd == VMC_COMMANDS["POLL"]["code"]:
            await self._handle_poll()
        elif cmd == VMC_COMMANDS["SELECTION_INFO"]["code"]:
            await self._handle_selection_info(payload)
        elif cmd == VMC_COMMANDS["DISPENSING_STATUS"]["code"]:
            await self._handle_dispensing_status(payload)
        elif cmd == VMC_COMMANDS["SELECT_CANCEL"]["code"]:
            await self._handle_selection_cancel(payload)
        else:
            await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def _handle_poll(self):
        """Respond to poll request"""
        if not self.command_queue.empty():
            cmd = await self.command_queue.get()
            (
                await self._send_command(*cmd)
                if isinstance(cmd, tuple)
                else await self._send_command(cmd)
            )
        else:
            await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def _handle_selection_info(self, payload):
        """Handle selection info from machine"""
        if len(payload) < 7:
            self.log("Invalid SELECTION_INFO packet")
            return

        await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def _handle_selection_cancel(self, payload):
        """Handle selection cancel"""
        if len(payload) < 2:
            self.log("Invalid SELECT_CANCEL packet")
            return

        selection = int.from_bytes(payload[1:3], "big")
        if selection == 0:
            self.current_selection = None
            self.state = "idle"
            print("\nSelection cancelled")
        else:
            if self.state == "idle":
                self.current_selection = selection
                self.state = "selecting"
                print(f"\nSelected product #{selection}")
                asyncio.create_task(self._process_payment(selection))

    async def _process_payment(self, selection):
        """Handle payment process"""
        try:
            self.state = "paying"

            if not self.esocket_connected:
                print("Reconnecting payment terminal...")
                await self.esocket_client.connect()
                await self.esocket_client.initialize_terminal()
                self.esocket_connected = True

            # Generate transaction ID
            transaction_id = str(int(time.time()) % 1000000).zfill(6)
            amount = 100  # $1.00 in cents

            print(f"Processing payment ${amount/100:.2f} (TXN: {transaction_id})")

            response = await self.esocket_client.send_purchase_transaction(
                transaction_id=transaction_id, amount=amount
            )

            if 'ActionCode="APPROVE"' in response.get("raw_response", ""):
                print("Payment approved")
                self.state = "dispensing"
                await self.direct_drive_selection(selection)
            else:
                print("Payment declined")
                await self.cancel_selection()
                self.state = "idle"

        except Exception as e:
            print(f"Payment error: {e}")
            await self.cancel_selection()
            self.state = "idle"

    async def _handle_dispensing_status(self, payload):
        """Handle dispensing status updates"""
        if len(payload) < 2:
            self.log("Invalid DISPENSING_STATUS packet")
            return

        status_code = payload[1]
        selection = self.current_selection

        status_messages = {
            0x00: f"Product #{selection} dispensed successfully",
            0x02: f"Product #{selection} dispensed successfully",
            0x03: f"Product #{selection} jammed",
            0x04: f"Product #{selection} motor error",
            0x06: f"Product #{selection} motor doesn't exist",
            0x07: f"Product #{selection} elevator error",
            0xFF: f"Product #{selection} purchase terminated",
        }

        message = status_messages.get(status_code, f"Unknown status {status_code}")
        print(message)

        # Reset state if dispensing is complete
        if status_code in (0x00, 0x02, 0x03, 0x04, 0x06, 0x07, 0xFF):
            self.state = "idle"
            self.current_selection = None

        await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def queue_command(self, command_name, data=None):
        """Queue a command for execution"""
        if command_name in VMC_COMMANDS:
            cmd_code = VMC_COMMANDS[command_name]["code"]
            if data:
                await self.command_queue.put((cmd_code, data))
            else:
                await self.command_queue.put(cmd_code)
            return True
        return False

    async def direct_drive_selection(self, selection_number):
        """Directly drive a selection motor"""
        data = bytes([1, 1])  # Use both drop sensor and elevator
        data += selection_number.to_bytes(2, byteorder="big")
        return await self.queue_command("DIRECT_DRIVE", data)

    async def cancel_selection(self):
        """Cancel current selection"""
        data = (0).to_bytes(2, byteorder="big")
        return await self.queue_command("SELECT_CANCEL", data)
