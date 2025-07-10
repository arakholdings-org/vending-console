import asyncio
import time
from asyncio import Queue
import subprocess

import serial_asyncio

from services.esocket import ESocketClient
from utils import VMC_COMMANDS
from utils.inventory import create_tray_data
from db import Prices, query


class VendingMachine:
    POLL_INTERVAL = 0.2
    RESPONSE_TIMEOUT = 0.1

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
        self.command_queue = Queue()
        self.MAX_RETRIES = 5
        self.last_command_time = 0
        self.esocket_client = ESocketClient()
        self.esocket_connected = False
        self.recv_buffer = bytearray()
        self.event_queue = asyncio.Queue()
        self._payment_lock = asyncio.Lock()
        self._command_semaphore = asyncio.Semaphore(5)
        self._current_transaction_task = None
        self.state = "idle"
        self._current_transaction_id = None
        # Connection monitoring
        self.serial_connected = False
        self._connection_monitor_task = None
        self._reconnect_delay = 5  # seconds
        self._max_reconnect_delay = 60  # seconds

    def log(self, *args):
        if self.debug:
            from datetime import datetime

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}]", *args)

    async def connect(self):
        """Establish connections with retries"""
        self.running = True

        # Start connection monitoring task
        if not self._connection_monitor_task:
            self._connection_monitor_task = asyncio.create_task(
                self._monitor_connections()
            )

        # Initial connection attempts
        await self._connect_serial()
        await self._connect_payment_terminal()

        # Start communication and event handling
        asyncio.create_task(self._communication_loop())
        asyncio.create_task(self._handle_events())

    async def _connect_serial(self):
        """Connect to serial port with retries"""
        delay = self._reconnect_delay
        while self.running and not self.serial_connected:
            try:
                self.reader, self.writer = await serial_asyncio.open_serial_connection(
                    url=self.port,
                    baudrate=57600,
                    parity="N",
                    stopbits=1,
                    bytesize=8,
                )
                self.serial_connected = True
                self.log(f"Serial connection established on {self.port}")
                delay = self._reconnect_delay  # Reset delay on success
                return True
            except Exception as e:
                self.log(f"Serial connection failed: {e}, retrying in {delay}s...")
                self.serial_connected = False
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)
        return False

    async def _connect_payment_terminal(self):
        """Connect to payment terminal with retries"""
        # Restart ESP service first (requires root)
        try:
            self.log("Restarting ESP service...")
            subprocess.run(["sudo", "systemctl", "restart", "esp.service"], check=True)
            self.log("ESP service restarted successfully")
        except subprocess.CalledProcessError as e:
            self.log(f"Failed to restart ESP service: {e}")
        except Exception as e:
            self.log(f"Error restarting ESP service: {e}")

        # Now attempt connection with retries
        delay = self._reconnect_delay
        while self.running and not self.esocket_connected:
            try:
                if await self.esocket_client.connect():
                    await self.esocket_client.initialize_terminal()
                    self.esocket_connected = True
                    self.log("Payment terminal connection established")
                    delay = self._reconnect_delay  # Reset delay on success
                    return True
                else:
                    raise Exception("Connection failed")
            except Exception as e:
                self.log(
                    f"Payment terminal connection failed: {e}, retrying in {delay}s..."
                )
                self.esocket_connected = False
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)
        return False

    async def _monitor_connections(self):
        """Monitor and reconnect when connections are lost"""
        while self.running:
            try:
                # Check serial connection
                serial_needs_reconnect = False
                if not self.serial_connected:
                    serial_needs_reconnect = True
                elif not self.reader or (
                    hasattr(self.reader, "at_eof") and self.reader.at_eof()
                ):
                    self.log("Serial connection lost, attempting reconnect...")
                    self.serial_connected = False
                    await self._cleanup_serial()
                    serial_needs_reconnect = True

                if serial_needs_reconnect:
                    # Try to reconnect serial port
                    result = await self._connect_serial()
                    if result:
                        self.log("Serial reconnected successfully.")
                    else:
                        self.log("Serial reconnection attempt failed.")

                # Check payment terminal connection
                if self.esocket_connected and not self.esocket_client.is_connected:
                    self.log(
                        "Payment terminal connection lost, attempting reconnect..."
                    )
                    self.esocket_connected = False
                    asyncio.create_task(self._connect_payment_terminal())

                await asyncio.sleep(5)  # Check every 5 seconds
            except Exception as e:
                self.log(f"Connection monitor error: {e}")
                await asyncio.sleep(5)

    async def _cleanup_serial(self):
        """Clean up serial connection"""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except:
                pass
        self.writer = None
        self.reader = None

    async def close(self):
        """Clean shutdown"""
        self.running = False

        # Cancel connection monitoring
        if self._connection_monitor_task:
            self._connection_monitor_task.cancel()
            try:
                await self._connection_monitor_task
            except asyncio.CancelledError:
                pass

        # Close serial connection
        await self._cleanup_serial()
        self.serial_connected = False

        # Close payment terminal
        if self.esocket_connected:
            try:
                await self.esocket_client.close_terminal()
                await self.esocket_client.disconnect()
            except:
                pass
            self.esocket_connected = False

        self.log("Shutdown complete")

    def _calculate_xor(self, data):
        xor_value = 0
        for b in data:
            xor_value ^= b
        return xor_value

    def create_packet(self, command, data=None):
        packet = self.STX + bytes([command])

        if data:
            packet += bytes([len(data) + 1])
            packet += bytes([self.packet_number]) + data
        else:
            packet += bytes([1]) + bytes([self.packet_number])

        packet += bytes([self._calculate_xor(packet)])
        self.packet_number = (self.packet_number % 255) + 1
        return packet

    async def _send_command(self, command, data=None):
        """Send a command to the machine with connection check"""
        if not self.serial_connected or not self.writer:
            self.log("Cannot send command: serial not connected")
            return False

        try:
            packet = self.create_packet(command, data)
            self.writer.write(packet)
            await self.writer.drain()

            self.last_command_time = time.time()
            return True
        except Exception as e:
            self.log(f"Failed to send command: {e}")
            self.serial_connected = False
            return False

    async def _communication_loop(self):
        """Optimized communication loop with connection handling"""
        while self.running:
            try:
                if not self.serial_connected or not self.reader:
                    await asyncio.sleep(1)
                    continue

                data = await asyncio.wait_for(self.reader.read(1024), timeout=1.0)
                if data:
                    self.recv_buffer.extend(data)
                    await self._process_incoming_data()

                # Only send ACKs when needed and connected
                if self.state == "dispensing" and self.serial_connected:
                    await self._send_command(VMC_COMMANDS["ACK"]["code"])

            except asyncio.TimeoutError:
                # Timeout is normal, continue
                pass
            except Exception as e:
                self.log(f"Communication error: {e}")
                self.serial_connected = False
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

        await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def _handle_selection_cancel(self, payload):
        """Handle selection cancel"""
        if len(payload) < 2:
            self.log("Invalid SELECT_CANCEL packet")
            return

        packet_number = payload[0]
        selection = int.from_bytes(payload[1:3], "big")

        # Log more detailed information about the cancel event
        self.log(f"Selection cancel event received: packet={packet_number}, selection={selection}")

        # Prevent duplicate processing of the same cancel packet
        if hasattr(self, "_last_cancel_packet") and self._last_cancel_packet == packet_number:
            self.log("Ignoring duplicate cancel packet")
            await self._send_command(VMC_COMMANDS["ACK"]["code"])
            return
        
        self._last_cancel_packet = packet_number

        # Reset after processing a cancel to prevent queueing issues
        self.command_queue = asyncio.Queue()  # Create a new queue to clear pending commands

        if selection == 0:
            # Cancel any running transaction
            if self._current_transaction_task and not self._current_transaction_task.done():
                self.log("Cancelling active transaction")
                self._current_transaction_task.cancel()
                try:
                    await self._current_transaction_task
                except asyncio.CancelledError:
                    self.log("Transaction cancelled successfully")
                except Exception as e:
                    self.log(f"Error cancelling transaction: {e}")
                finally:
                    self._current_transaction_task = None

            self.current_selection = None
            self.log("Selection cancelled")
        else:
            # Only process if no transaction is running
            if not self._current_transaction_task or self._current_transaction_task.done():
                self.current_selection = selection
                self.log(f"Selected product #{selection}")
                await self._process_payment(selection)
            else:
                self.log("Ignoring selection, transaction in progress")

        await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def _process_payment(self, selection):
        """Enhanced payment processing with connection checks"""
        if self._current_transaction_task:
            self.log("Payment attempted while transaction in progress")
            if self.serial_connected:
                await self._send_command(VMC_COMMANDS["ACK"]["code"])
            return

        if not self.esocket_connected:
            self.log("✗ Error: Payment terminal not connected")
            await self.cancel_selection()
            return

        try:
            async with self._payment_lock:
                selection_data = Prices.get(query.selection == selection)

                if not selection_data:
                    self.log(f"✗ Error: Price not found for selection {selection}")
                    await self.cancel_selection()
                    return

                amount = selection_data.get("price", 0)
                if amount <= 0:
                    self.log(f"✗ Error: Invalid price for selection {selection}")
                    await self.cancel_selection()
                    return

                transaction_id = str(
                    (int(time.time()) % 900000) + 100000
                )  # Always 6 digits, never starts with 0
                self._current_transaction_id = transaction_id

                self.log(f"Initiating payment ${amount/100:.2f}")
                self.log(f"Transaction ID: {transaction_id}")

                def payment_callback(task):
                    try:
                        response = task.result()
                        if response.get(
                            "success", False
                        ) and 'ActionCode="APPROVE"' in response.get(
                            "raw_response", ""
                        ):
                            self.log("✓ Payment approved")

                            selection = self.current_selection
                            selection_data = Prices.get(query.selection == selection)

                            if selection_data and self.serial_connected:
                                # dispense product
                                asyncio.create_task(
                                    self.queue_command(
                                        "DIRECT_DRIVE",
                                        bytes([1, 1])
                                        + selection.to_bytes(2, byteorder="big"),
                                    )
                                )

                                # Update inventory in database after dispensing command
                                current_inventory = selection_data.get("inventory", 0)
                                new_inventory = max(0, current_inventory - 1)

                                # Update local database
                                Prices.update(
                                    {"inventory": new_inventory},
                                    query.selection == selection,
                                )

                                # Create and queue inventory update command for VMC
                                if self.serial_connected:
                                    inventory_data = selection.to_bytes(
                                        2, byteorder="big"
                                    ) + bytes([new_inventory])
                                    asyncio.create_task(
                                        self.queue_command(
                                            "SET_INVENTORY", inventory_data
                                        )
                                    )
                            else:
                                self.log(
                                    f"✗ Error: Could not dispense - serial disconnected or selection not found"
                                )
                                asyncio.create_task(self.cancel_selection())

                        else:
                            error_msg = (
                                self._extract_error_message(
                                    response.get("raw_response", "")
                                )
                                or "Transaction declined"
                            )
                            self.log(f"✗ Payment failed: {error_msg}")
                            asyncio.create_task(self.cancel_selection())
                    except Exception as e:
                        self.log(f"✗ Payment error: {str(e)}")
                        asyncio.create_task(self.cancel_selection())
                    finally:
                        self.current_selection = None
                        self._current_transaction_task = None

                self._current_transaction_task = asyncio.create_task(
                    self.esocket_client.send_purchase_transaction(
                        transaction_id=transaction_id, amount=amount
                    )
                )
                self._current_transaction_task.add_done_callback(payment_callback)

        except Exception as e:
            self.log(f"✗ System error: {str(e)}")
            self.current_selection = None
            self._current_transaction_task = None
            await self.cancel_selection()
        finally:
            if self.serial_connected:
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
        """Enhanced dispensing status handler with reversal support"""
        if len(payload) < 2:
            return

        status_code = payload[1]
        # Use the selection from the payload if available, else fallback to self.current_selection
        selection = self.current_selection
        if len(payload) >= 3:
            selection_from_payload = int.from_bytes(payload[2:4], "big")
            if selection_from_payload != 0:
                selection = selection_from_payload

        # Success codes
        if status_code in (0x00, 0x02):
            self.log(f"Product #{selection} dispensed successfully")
            self.current_selection = None

        # Error codes indicating jam/stuck product
        elif status_code in (0x03, 0x04, 0x06, 0x07, 0xFF):
            self.log(
                f"Product #{selection} - Error: Product may be stuck (code: {status_code:02X})"
            )

            # Create reversal transaction
            try:
                transaction_id = str(int(time.time()) % 1000000).zfill(6)

                # Construct reversal XML message
                reversal_message = {
                    "TerminalId": self.esocket_client.terminal_id,
                    "TransactionId": transaction_id,
                    "Type": "REVERSAL",
                    "OriginalTransactionId": self._current_transaction_id,
                    "ReasonCode": f"Product jam error {status_code:02X}",
                }

                self.log("Initiating payment reversal due to product jam...")

                # Send reversal to payment terminal
                response = await self.esocket_client.send_reversal_transaction(
                    **reversal_message
                )

                if response.get(
                    "success", False
                ) and 'ActionCode="APPROVE"' in response.get("raw_response", ""):
                    self.log("✓ Payment reversed successfully")
                else:
                    error_msg = self._extract_error_message(
                        response.get("raw_response", "")
                    )
                    self.log(f"✗ Reversal failed: {error_msg or 'Unknown error'}")

            except Exception as e:
                self.log(f"✗ Reversal error: {str(e)}")

            finally:
                # Reset machine state
                self.current_selection = None
                await self.cancel_selection()

        await self._send_command(VMC_COMMANDS["ACK"]["code"])

    async def queue_command(self, command_name, data=None):
        """Queue a command with connection check"""
        if not self.serial_connected:
            self.log(f"Cannot queue command {command_name}: serial not connected")
            return False

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

    async def set_product_price(self, tray_number: int, price: int):
        """Set price for an entire tray

        Args:
            tray_number: Tray number (0-9)
            price: Price in cents (0-9999)

        Returns:
            bool: True if successful, False if validation fails
        """
        if price is None or not (0 <= price <= 9999):
            self.log("Invalid price: must be between 0 and 9999 cents")
            return False

        if not (0 <= tray_number <= 9):
            self.log("Invalid tray number: must be between 0 and 9")
            return False

        # First selection in tray: tray_number * 10 + 1
        selection = tray_number * 10 + 1

        # Create data packet: selection number (2 bytes) + price (4 bytes)
        data = selection.to_bytes(2, byteorder="big") + price.to_bytes(
            4, byteorder="big"
        )

        # First set price in the vending machine
        if not await self.queue_command("SET_PRICE", data):
            return False

        try:
            # Generate selection data for the tray
            selections = create_tray_data(tray_number, price)

            # Update prices in database
            for selection_data in selections:
                Prices.upsert(
                    selection_data, query.selection == selection_data["selection"]
                )

            return True
        except Exception as e:
            self.log(f"Database update failed: {e}")
            return False

    async def cancel_selection(self):
        """Cancel current selection with proper state reset"""
        self.log("Cancelling selection")
        
        # First send the cancel command to the machine
        data = (0).to_bytes(2, byteorder="big")
        result = await self.queue_command("SELECT_CANCEL", data)
        
        # Then reset internal state
        await self.reset_machine_state()
        
        return result

    async def reset_machine_state(self):
        """Reset machine state after cancel or error"""
        self.log("Resetting machine state")
        
        # Clear current transaction
        self._current_transaction_id = None
        self.current_selection = None
        
        # Create a fresh command queue
        old_queue = self.command_queue
        self.command_queue = asyncio.Queue()
        
        # Drain the old queue to prevent any resource leaks
        try:
            while not old_queue.empty():
                old_queue.get_nowait()
                old_queue.task_done()
        except Exception:
            pass

        # Send a final ACK to ensure the machine is in a good state
        if self.serial_connected:
            await self._send_command(VMC_COMMANDS["ACK"]["code"])
        
        return True

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
        # Restart ESP service first (requires root)
        try:
            print("Restarting ESP service...")
            subprocess.run(["sudo", "systemctl", "restart", "esp.service"], check=True)
            print("ESP service restarted successfully")
        except subprocess.CalledProcessError as e:
            self.log(f"Failed to restart ESP service: {e}")
        except Exception as e:
            self.log(f"Error restarting ESP service: {e}")

        # Now attempt connection with retries
        delay = self._reconnect_delay
        while self.running and not self.esocket_connected:
            try:
                if await self.esocket_client.connect():
                    await self.esocket_client.initialize_terminal()
                    self.esocket_connected = True
                    self.log("Payment terminal connection established")
                    delay = self._reconnect_delay  # Reset delay on success
                    return True
                else:
                    raise Exception("Connection failed")
            except Exception as e:
                self.log(
                    f"Payment terminal connection failed: {e}, retrying in {delay}s..."
                )
                self.esocket_connected = False
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)
        return False
