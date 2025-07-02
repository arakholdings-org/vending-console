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

        # Initialize command queue with retry tracking
        self.command_queue = Queue()
        self._command_retries = {}  # Track retries per command
        self.MAX_RETRIES = 5  # According to protocol spec
        self.last_command_time = 0  # Track last command time

        # Initialize eSocket client
        self.esocket_client = ESocketClient()
        self.esocket_connected = False

        # State management
        self.state = {
            "machine": "idle",
            "payment": "idle",
            "dispensing": False,
        }

        # Timeouts
        self.timeouts = {
            "poll": 0.05,  # 50ms for faster response
        }

        # Communication lock - lighter weight for better performance
        self._command_lock = asyncio.Lock()
        self.dispense_lock = asyncio.Lock()

        # Task management for cleanup
        self._background_tasks = set()
        self._comm_task = None
        self._shutdown_event = asyncio.Event()

    def _debug_print(self, *args):
        if self.debug:
            print(*args)

    async def connect(self):
        """Establish connection and initialize communication"""
        self.reader, self.writer = await serial_asyncio.open_serial_connection(
            url=self.port,
            baudrate=57600,
            parity="N",
            stopbits=1,
            bytesize=8,
        )
        self.running = True

        # Initialize eSocket connection
        await self._initialize_esocket()

        # Initial synchronization (Section 4.4.4)
        await self._send_command(VMC_COMMANDS["SYNC_INFO"]["code"])
        self._debug_print("Connection established and synchronized")

        # Start communication loop with task tracking
        self._comm_task = asyncio.create_task(self._communication_loop())
        self._background_tasks.add(self._comm_task)
        self._comm_task.add_done_callback(self._background_tasks.discard)

    async def _initialize_esocket(self):
        """Initialize eSocket connection asynchronously"""
        try:
            print("🔌 Connecting to payment terminal...")
            if await self.esocket_client.connect():
                print("✅ Connected to payment terminal")
                try:
                    # Add small delay to ensure connection is stable
                    await asyncio.sleep(0.5)
                    await self.esocket_client.initialize_terminal()
                    self.esocket_connected = True
                    print("✅ Payment terminal initialized successfully")
                    self._debug_print("eSocket connection established")
                except Exception as e:
                    print(f"❌ Failed to initialize payment terminal: {e}")
                    self.esocket_connected = False
                    # Try to disconnect cleanly on initialization failure
                    try:
                        await self.esocket_client.disconnect()
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
                await self.esocket_client.disconnect()
            except:
                pass

    async def close(self):
        """Clean shutdown with immediate task cleanup"""
        print("🔄 Initiating shutdown...")
        self.running = False
        self._shutdown_event.set()

        # Cancel and wait for communication task
        if self._comm_task and not self._comm_task.done():
            self._comm_task.cancel()
            try:
                await self._comm_task
            except asyncio.CancelledError:
                pass

        # Cancel all background tasks
        if self._background_tasks:
            for task in list(self._background_tasks):
                if not task.done():
                    task.cancel()

            # Wait for all tasks to complete with timeout
            if self._background_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*self._background_tasks, return_exceptions=True),
                        timeout=2.0,
                    )
                except asyncio.TimeoutError:
                    print("⚠️ Some tasks did not complete within timeout")

        # Close serial connection
        if self.writer:
            self.writer.close()
            try:
                await asyncio.wait_for(self.writer.wait_closed(), timeout=1.0)
            except asyncio.TimeoutError:
                print("⚠️ Serial connection close timeout")

        # Close eSocket connection
        if self.esocket_connected:
            try:
                await asyncio.wait_for(
                    self.esocket_client.close_terminal(), timeout=2.0
                )
                await asyncio.wait_for(self.esocket_client.disconnect(), timeout=1.0)
            except asyncio.TimeoutError:
                print("⚠️ eSocket close timeout")
            except Exception as e:
                print(f"⚠️ eSocket close error: {e}")

        print("✅ Shutdown complete")
        self._debug_print("Connection closed")

    def _calculate_xor(self, data):
        xor_value = 0
        for b in data:
            xor_value ^= b
        return xor_value

    async def _send_ack(self):
        return await self._send_command(VMC_COMMANDS["ACK"]["code"])

    def create_packet(self, command, data=None):
        """Create a protocol-compliant packet with XOR checksum"""
        packet = self.STX + bytes([command])

        if data:
            packet += bytes([len(data) + 1])  # +1 for packet number
            packet += bytes([self.packet_number]) + data
        else:
            packet += bytes([1]) + bytes([self.packet_number])  # Just packet number

        # Calculate XOR
        xor = self._calculate_xor(packet)
        packet += bytes([xor])

        # Increment packet number (1-255)
        self.packet_number = (self.packet_number % 255) + 1
        return packet

    async def _send_command(self, command, data=None):
        """Send a command"""
        async with self._command_lock:
            packet = self.create_packet(command, data)
            self.writer.write(packet)
            await self.writer.drain()
            self._debug_print(f"Sent: {packet.hex(' ').upper()}")
            return True

    async def _communication_loop(self):
        """Main communication handling loop with continuous polling"""
        last_poll_time = time.time()
        poll_missed_count = 0

        while self.running and not self._shutdown_event.is_set():
            try:
                # Check if we missed polls
                current_time = time.time()
                time_since_poll = current_time - last_poll_time

                if time_since_poll > 0.2:  # 200ms without poll
                    poll_missed_count += 1
                    if poll_missed_count > 2:
                        self._debug_print(
                            f"Warning: {poll_missed_count} consecutive missed POLLs"
                        )
                else:
                    poll_missed_count = 0

                # Read available data with shorter timeout for responsiveness
                try:
                    data = await asyncio.wait_for(
                        self.reader.read(1024), timeout=self.timeouts["poll"]
                    )
                    if data:
                        self.recv_buffer.extend(data)
                        await self._process_incoming_data()
                        last_poll_time = current_time
                        poll_missed_count = 0
                except asyncio.TimeoutError:
                    # No data available, continue polling
                    pass

                # Very short sleep to prevent CPU thrashing but maintain responsiveness
                await asyncio.sleep(0.005)  # 5ms sleep

            except asyncio.CancelledError:
                self._debug_print("Communication loop cancelled")
                break
            except Exception as e:
                self._debug_print(f"Communication error: {str(e)}")
                if not self.running:
                    break
                await asyncio.sleep(0.1)  # Brief pause on error

    async def _process_incoming_data(self):
        """Process all available incoming data"""
        while len(self.recv_buffer) >= 5:  # Minimum packet size
            packet, remaining = self._extract_packet(self.recv_buffer)
            if not packet:
                break

            await self._handle_packet(packet)
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
        if self._calculate_xor(packet[:-1]) != packet[-1]:
            self._debug_print(f"Invalid checksum in packet: {packet.hex(' ')}")
            # Remove STX and try to resync
            return None, data[2:]

        return packet, remaining

    async def _handle_packet(self, packet):
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
            await self._handle_poll(payload)
        elif cmd == VMC_COMMANDS["SELECTION_INFO"]["code"]:
            await self._handle_selection_info(payload)
        elif cmd == VMC_COMMANDS["DISPENSING_STATUS"]["code"]:
            await self._handle_dispensing_status(payload)
        elif cmd == VMC_COMMANDS["SELECT_CANCEL"]["code"]:
            await self._handle_selection_cancel(payload)
        elif cmd != VMC_COMMANDS["ACK"]["code"]:
            await self._send_ack()

    async def _handle_poll(self, payload):
        """Process POLL (0x41) packet and respond within 50ms for better responsiveness"""
        try:
            current_time = time.time()

            # Check if we have commands to process
            if not self.command_queue.empty():
                # Reduced delay for faster response
                if (
                    current_time - self.last_command_time < 0.1
                ):  # 100ms instead of 200ms
                    await self._send_ack()
                    return

                try:
                    next_cmd = self.command_queue.get_nowait()
                    cmd_id = id(next_cmd)  # Use command object id as unique identifier

                    # Check retry count
                    retries = self._command_retries.get(cmd_id, 0)
                    if retries >= self.MAX_RETRIES:
                        self._debug_print(
                            f"Maximum retries reached for command: {next_cmd}"
                        )
                        self._command_retries.pop(cmd_id, None)
                        await self._send_command(VMC_COMMANDS["ACK"]["code"])
                        return

                    # Send command
                    if isinstance(next_cmd, tuple):
                        cmd_code, data = next_cmd
                        success = await self._send_command(cmd_code, data)
                    else:
                        success = await self._send_command(next_cmd)

                    if not success:
                        # Put command back in queue for retry
                        self._command_retries[cmd_id] = retries + 1
                        await self.command_queue.put(next_cmd)
                    else:
                        # Command sent successfully, reset retry counter
                        self._command_retries.pop(cmd_id, None)
                        self.last_command_time = current_time
                except:
                    pass  # Queue was empty
            else:
                await self._send_command(VMC_COMMANDS["ACK"]["code"])
        except Exception as e:
            self._debug_print(f"Poll handling error: {e}")
            await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def _handle_selection_info(self, payload):
        """Process SELECTION_INFO (0x11) packet"""
        if len(payload) < 7:
            self._debug_print("Invalid SELECTION_INFO packet length")
            return

        # Acknowledge receipt of selection info
        await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def _handle_selection_cancel(self, payload):
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
                async with self.dispense_lock:
                    self.dispensing_active = False
        else:
            # Only process selection if we don't already have one
            if self.current_selection is None:
                self.current_selection = selection
                print(f"\n📦 Selection #{selection} received - processing payment...")
                # Handle payment without blocking poll loop
                task = asyncio.create_task(self._handle_payment(selection))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            else:
                self._debug_print(
                    f"Ignoring selection {selection}, already processing {self.current_selection}"
                )

    async def _handle_payment(self, selection):
        """Process payment asynchronously without blocking poll loop"""
        try:
            if not self.esocket_connected:
                print("⚠️ Payment terminal not connected, attempting to reconnect...")
                await self._initialize_esocket()

            # Generate transaction ID
            timestamp_mod = int(time.time()) % 900000
            transaction_id = str(100000 + timestamp_mod)[:6]

            amount = 100  # $2.00 in cents
            print(f"💰 Processing ${amount/100:.2f} payment... (TXN: {transaction_id})")

            # Use shorter timeout for payment processing to avoid blocking
            try:
                response = await asyncio.wait_for(
                    self.esocket_client.send_purchase_transaction(
                        transaction_id=transaction_id, amount=amount
                    ),
                    timeout=10.0,  # 10 second timeout
                )
            except asyncio.TimeoutError:
                print("❌ Payment timeout - transaction cancelled")
                await self._cancel_current_selection()
                return

            if self._is_payment_successful(response):
                print("✅ Payment approved!")
                async with self.dispense_lock:
                    if (
                        self.current_selection == selection
                    ):  # Verify selection hasn't changed
                        self.dispensing_active = True
                        await self.direct_drive_selection(selection, True, True)
                    else:
                        print("❌ Selection changed during payment processing")
                        await self._cancel_current_selection()
            else:
                print("❌ Payment declined")
                await self._cancel_current_selection()

        except Exception as e:
            print(f"❌ Payment error: {e}")
            await self._cancel_current_selection()

    async def _handle_dispensing_status(self, payload):
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
        async with self.dispense_lock:
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
        await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def _cancel_current_selection(self):
        """Cancel the current selection and send cancel command to VMC"""
        if self.current_selection:
            selection = self.current_selection
            self.current_selection = None
            print(f"🚫 Cancelling selection #{selection}")
            await self.cancel_selection()

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

    async def queue_command(self, command_name, data=None):
        """Queue a command to be sent when next POLL is received"""
        if command_name in VMC_COMMANDS:
            cmd_code = VMC_COMMANDS[command_name]["code"]
            if data:
                await self.command_queue.put((cmd_code, data))
            else:
                await self.command_queue.put(cmd_code)
            self._debug_print(f"Command {command_name} queued for next POLL")
            return True
        else:
            self._debug_print(f"Unknown command: {command_name}")
            return False

    async def check_selection(self, selection_number):
        """Queue a command to check selection status"""
        data = selection_number.to_bytes(2, byteorder="big")
        return await self.queue_command("CHECK_SELECTION", data)

    async def buy_selection(self, selection_number):
        """Queue a command to buy a selection"""
        data = selection_number.to_bytes(2, byteorder="big")
        return await self.queue_command("SELECT_TO_BUY", data)

    async def direct_drive_selection(
        self, selection_number, use_drop_sensor=True, use_elevator=True
    ):
        """Queue a command to directly drive a selection motor"""
        data = bytes([1 if use_drop_sensor else 0, 1 if use_elevator else 0])
        data += selection_number.to_bytes(2, byteorder="big")
        return await self.queue_command("DIRECT_DRIVE", data)

    async def cancel_selection(self):
        """Queue a command to cancel current selection"""
        data = (0).to_bytes(2, byteorder="big")
        return await self.queue_command("SELECT_CANCEL", data)

    async def request_machine_status(self):
        """Queue a command to request machine status"""
        return await self.queue_command("MACHINE_STATUS_REQ")
