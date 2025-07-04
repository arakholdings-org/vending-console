import asyncio
import time
from asyncio import Queue

import serial_asyncio

from services.esocket import ESocketClient
from utils import VMC_COMMANDS


class VendingMachine:
    POLL_INTERVAL = 0.2  # 200ms as per spec
    RESPONSE_TIMEOUT = 0.1  # 100ms as per spec

    def __init__(self, port="/dev/ttyUSB0", debug=False):
        self.port = port
        self.debug = debug
        self.STX = bytes([0xFA, 0xFB])
        self.packet_number = 1
        self.running = False
        self.reader = None
        self.writer = None
        self.current_selection = None

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

        self.recv_buffer = bytearray()
        self.event_queue = asyncio.Queue()

        self._payment_lock = asyncio.Lock()
        self._command_semaphore = asyncio.Semaphore(5)  # Max 5 concurrent commands

    def log(self, *args):
        if self.debug:
            print(*args)

    async def connect(self):
        """Establish connections with retries"""
        try:
            # Connect serial
            self.reader, self.writer = await serial_asyncio.open_serial_connection(
                url=self.port,
                baudrate=57600,
                parity="N",
                stopbits=1,
                bytesize=8,
            )

            self.running = True

            # Initialize payment terminal once
            if not self.esocket_connected:
                await self._connect_payment_terminal()

            # Start communication and event handling
            asyncio.create_task(self._communication_loop())
            asyncio.create_task(self._handle_events())

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
        """Optimized communication loop"""
        while self.running:
            try:
                data = await self.reader.read(1024)
                if data:
                    self.recv_buffer.extend(data)
                    await self._process_incoming_data()

                # Only send ACKs when needed
                if self.state == "dispensing":
                    await self._send_command(VMC_COMMANDS["ACK"]["code"])

            except Exception as e:
                self.log(f"Communication error: {e}")
                if not self.running:
                    break
                await asyncio.sleep(0.01)

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
        payload = packet[4:-1]

        # Match packet number for responses
        if len(payload) > 0:
            self.packet_number = payload[0]

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
        """Optimized poll handling"""
        if not self.command_queue.empty():
            cmd = await self.command_queue.get()
            # Prioritize dispensing commands
            if (
                isinstance(cmd, tuple)
                and cmd[0] == VMC_COMMANDS["DIRECT_DRIVE"]["code"]
            ):
                await self._send_command(*cmd)
            else:
                await self._send_command(*cmd if isinstance(cmd, tuple) else (cmd,))
        else:
            await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def _handle_selection_info(self, payload):
        """Handle selection info from machine"""
        if len(payload) < 12:  # Changed from 7 to 12 as per spec
            self.log("Invalid SELECTION_INFO packet")
            return

        # Parse according to spec (section 4.2.1)
        selection = int.from_bytes(payload[1:3], "big")
        price = int.from_bytes(payload[3:7], "big")
        inventory = payload[7]
        capacity = payload[8]
        product_id = int.from_bytes(payload[9:11], "big")
        status = payload[11]

        self.log(
            f"Selection {selection}: Price={price}, Inventory={inventory}, Status={status}"
        )
        await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def _handle_selection_cancel(self, payload):
        """Handle selection cancel"""
        if len(payload) < 2:
            self.log("Invalid SELECT_CANCEL packet")
            return

        # Get packet number and selection
        packet_number = payload[0]
        selection = int.from_bytes(payload[1:3], "big")

        # Avoid duplicate processing by tracking packet numbers
        if (
            hasattr(self, "_last_cancel_packet")
            and self._last_cancel_packet == packet_number
        ):
            return
        self._last_cancel_packet = packet_number

        if selection == 0:
            if self.state != "idle":
                self.current_selection = None
                self.state = "idle"
                print("\nSelection cancelled")
        else:
            # Only process if we're not already in a transaction
            if self.state == "idle":
                self.current_selection = selection
                self.state = "paying"
                print(f"\nSelected product #{selection}")
                await self._process_payment(selection)
            else:
                self.log(
                    f"Ignoring selection {selection}, already processing transaction"
                )

        # Send acknowledgment
        await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def _process_payment(self, selection):
        """Enhanced payment processing with response handling"""
        if self.state != "paying":
            self.log("Payment attempted in invalid state")
            await self._send_command(VMC_COMMANDS["ACK"]["code"])
            return

        try:
            async with self._payment_lock:
                transaction_id = str(int(time.time()) % 1000000).zfill(6)
                amount = 100  # $1.00 in cents

                print(f"\nInitiating payment ${amount/100:.2f}")
                print(f"Transaction ID: {transaction_id}")

                def payment_callback(task):
                    """Synchronous callback to handle payment completion"""
                    try:
                        response = (
                            task.result()
                        )  # This is a dict with raw_response and success
                        if response.get(
                            "success", False
                        ) and 'ActionCode="APPROVE"' in response.get(
                            "raw_response", ""
                        ):
                            print("\n✓ Payment approved")
                            self.state = "dispensing"
                            # Queue the dispense command
                            asyncio.create_task(
                                self.queue_command(
                                    "DIRECT_DRIVE",
                                    bytes([1, 1])
                                    + selection.to_bytes(2, byteorder="big"),
                                )
                            )
                        else:
                            error_msg = (
                                self._extract_error_message(
                                    response.get("raw_response", "")
                                )
                                or "Transaction declined"
                            )
                            print(f"\n✗ Payment failed: {error_msg}")
                            self.state = "idle"
                            self.current_selection = None
                    except Exception as e:
                        print(f"\n✗ Payment error: {str(e)}")
                        self.state = "idle"
                        self.current_selection = None

                # Start payment transaction as background task
                transaction_task = asyncio.create_task(
                    self.esocket_client.send_purchase_transaction(
                        transaction_id=transaction_id, amount=amount
                    )
                )

                # Add callback to handle completion
                transaction_task.add_done_callback(payment_callback)

        except Exception as e:
            print(f"\n✗ System error: {str(e)}")
            self.state = "idle"
            self.current_selection = None
        finally:
            await self._send_command(VMC_COMMANDS["ACK"]["code"])

    def _extract_error_message(self, raw_response):
        """Extract error message from response"""
        try:
            if 'ErrorMessage="' in raw_response:
                start = raw_response.index('ErrorMessage="') + 14
                end = raw_response.index('"', start)
                return raw_response[start:end]
            elif 'ActionCode="' in raw_response:
                start = raw_response.index('ActionCode="') + 12
                end = raw_response.index('"', start)
                return f"Transaction declined: {raw_response[start:end]}"
        except:
            pass
        return None

    async def _handle_dispensing_status(self, payload):
        """Simple dispensing status handler"""
        if len(payload) < 2:
            return

        status_code = payload[1]
        selection = self.current_selection

        if status_code in (0x00, 0x02):
            print(f"Product #{selection} dispensed successfully")
            self.current_selection = None
            self.state = "idle"
        elif status_code in (0x03, 0x04, 0x06, 0x07, 0xFF):
            print(f"Product #{selection} - Error code: {status_code:02X}")
            self.current_selection = None
            self.state = "idle"

        await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def queue_command(self, command_name, data=None):
        """Queue a command with concurrency control"""
        async with self._command_semaphore:
            if command_name in VMC_COMMANDS:
                cmd_code = VMC_COMMANDS[command_name]["code"]
                if data:
                    await self.command_queue.put((cmd_code, data))
                else:
                    await self.command_queue.put(cmd_code)
                return True
        return False

    async def direct_drive_selection(self, selection_number):
        """Immediate dispensing command"""
        data = bytes([1, 1])  # Use both drop sensor and elevator
        data += selection_number.to_bytes(2, byteorder="big")
        # Send command immediately for dispensing
        await self._send_command(VMC_COMMANDS["DIRECT_DRIVE"]["code"], data)
        return True

    async def cancel_selection(self):
        """Cancel current selection"""
        data = (0).to_bytes(2, byteorder="big")
        return await self.queue_command("SELECT_CANCEL", data)

    async def _get_next_event(self):
        """Get next event from queue"""
        try:
            return await asyncio.wait_for(self.event_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None

    async def _process_event(self, event):
        """Process a single event"""
        try:
            event_type = event.get("type")
            if event_type == "payment":
                await self._handle_payment_event(event)
            elif event_type == "dispensing":
                await self._handle_dispensing_event(event)
        except Exception as e:
            self.log(f"Event processing error: {e}")

    async def _handle_events(self):
        """Handle multiple events concurrently"""
        event_tasks = set()

        while self.running:
            # Clean up completed tasks
            event_tasks = {task for task in event_tasks if not task.done()}

            # Handle new events
            if new_event := await self._get_next_event():
                task = asyncio.create_task(self._process_event(new_event))
                event_tasks.add(task)

            await asyncio.sleep(0.01)

    async def _connect_payment_terminal(self):
        """Connect and initialize the payment terminal."""
        try:
            await self.esocket_client.connect()
            await self.esocket_client.initialize_terminal()
            self.esocket_connected = True
            return True
        except Exception as e:
            self.log(f"Payment terminal connection failed: {e}")
            self.esocket_connected = False
            return False
