import serial
import time
import threading
from queue import Queue, Empty
import operator
from functools import reduce

# --- Constants based on the VMC Communication Protocol Document ---

# Serial Port Configuration
# NOTE: Change 'COM3' to the actual serial port connected to your VMC
# On Linux/macOS, it might be '/dev/ttyUSB0' or '/dev/tty.usbserial-XXXX'
SERIAL_PORT = "/dev/ttyUSB0"  # Example for Linux; change as needed
BAUD_RATE = 57600
# Per document: 8 data bits, 1 stop bit, no parity

# VMC Protocol Definitions
STX = b"\xfa\xfb"
CMD_POLL = 0x41
CMD_ACK = 0x42
CMD_UPPER_COMPUTER_SELECTS_TO_BUY = 0x03
CMD_VMC_DISPENSING_STATUS = 0x04
CMD_UPPER_COMPUTER_RECEIVES_MONEY = 0x27

# Pre-built ACK response for convenience
ACK_PACKET = STX + bytes([CMD_ACK, 0x00, 0x43])

# A simple menu of products managed by the Upper Computer
# In a real application, this might be loaded from a config file or API
PRODUCT_MENU = {
    10: {"name": "Cola", "price": 1.50},
    11: {"name": "Chips", "price": 1.25},
    12: {"name": "Candy Bar", "price": 1.00},
    24: {"name": "Water", "price": 1.75},
    25: {"name": "Iced Tea", "price": 2.00},
}

# Dispensing status codes from the VMC document
DISPENSE_STATUS_CODES = {
    0x01: "Dispensing in progress...",
    0x02: "Dispensing successful!",
    0x03: "Selection jammed.",
    0x04: "Motor did not stop normally.",
    0x06: "Motor for selection does not exist.",
    0x07: "Elevator error.",
    0x1F: "Purchase terminated.",
    # Add other status codes from the document as needed
}


class VendingMachineClient:
    """
    Manages communication with the Vending Machine Controller (VMC)
    by acting as the 'Upper Computer' slave device.
    """

    def __init__(self, port):
        """
        Initializes the client, serial port, and communication state.
        Args:
            port (str): The serial port to connect to (e.g., 'COM3').
        """
        self.serial_port = None
        self.port_name = port
        self.is_running = False
        self.reader_thread = None
        self.command_to_send = None
        self.comm_packet_no = 1
        # Queues for thread-safe message passing
        self.incoming_data_q = Queue()
        self.log_q = Queue()

    def connect(self):
        """Establishes the serial connection to the VMC."""
        try:
            self.serial_port = serial.Serial(
                port=self.port_name,
                baudrate=BAUD_RATE,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1,  # Read timeout
            )
            self.log_q.put(
                f"Successfully connected to {self.port_name} at {BAUD_RATE} baud."
            )
            return True
        except serial.SerialException as e:
            self.log_q.put(
                f"Error: Could not open serial port {self.port_name}. Details: {e}"
            )
            return False

    def start_communication(self):
        """Starts the background thread to listen for VMC messages."""
        if self.serial_port and self.serial_port.is_open:
            self.is_running = True
            self.reader_thread = threading.Thread(target=self._read_from_port)
            self.reader_thread.daemon = True
            self.reader_thread.start()
            self.log_q.put("Communication listener started.")
        else:
            self.log_q.put("Cannot start communication: Serial port is not open.")

    def stop_communication(self):
        """Stops the communication thread and closes the serial port."""
        self.is_running = False
        if self.reader_thread:
            self.reader_thread.join()  # Wait for the thread to finish
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            self.log_q.put("Communication stopped and port closed.")

    def _calculate_xor_checksum(self, data: bytes) -> int:
        """Calculates the XOR checksum for a given byte string."""
        return reduce(operator.xor, data)

    def _build_packet(self, command: int, text: bytes) -> bytes:
        """
        Constructs a complete data packet according to the VMC protocol.
        Args:
            command (int): The command byte.
            text (bytes): The payload (PackNO + Text).
        Returns:
            bytes: The fully formed packet to be sent.
        """
        length = len(text)
        packet_header = STX + bytes([command, length])
        full_packet_data = packet_header + text
        checksum = self._calculate_xor_checksum(full_packet_data)
        return full_packet_data + bytes([checksum])

    def queue_command(self, command: int, data: bytes):
        """
        Prepares a command to be sent upon the next VMC POLL.
        Args:
            command (int): The command code.
            data (bytes): The data payload for the command.
        """
        # PackNO is the first byte of the 'text' field
        text_payload = self.comm_packet_no.to_bytes(1, "big") + data
        self.command_to_send = self._build_packet(command, text_payload)
        self.log_q.put(f"Queued command: {self.command_to_send.hex().upper()}")

    def _read_from_port(self):
        """
        Worker method that runs in a separate thread to read data from the VMC.
        It handles the POLL/ACK cycle and parses incoming data packets.
        """
        buffer = b""
        while self.is_running:
            try:
                # Read any available data from the serial port
                buffer += self.serial_port.read(self.serial_port.in_waiting or 1)

                # Look for the start of a packet
                stx_index = buffer.find(STX)
                if stx_index != -1:
                    buffer = buffer[stx_index:]  # Discard any noise before STX

                    if len(buffer) >= 5:  # Minimum packet size (STX+Cmd+Len+XOR)
                        command = buffer[2]
                        length = buffer[3]

                        if (
                            len(buffer) >= 4 + length + 1
                        ):  # Check if full packet is received
                            packet_data = buffer[: 4 + length]
                            received_checksum = buffer[4 + length]
                            calculated_checksum = self._calculate_xor_checksum(
                                packet_data
                            )

                            if received_checksum == calculated_checksum:
                                # Packet is valid, process it
                                self._process_incoming_packet(buffer[: 4 + length + 1])
                            else:
                                self.log_q.put(
                                    f"Checksum error! Got {received_checksum:02X}, expected {calculated_checksum:02X}"
                                )

                            # Move buffer past the processed packet
                            buffer = buffer[5 + length :]
            except Exception as e:
                self.log_q.put(f"Error in reader thread: {e}")
                self.is_running = False

    def _process_incoming_packet(self, packet: bytes):
        """Processes a single, validated packet from the VMC."""
        command = packet[2]
        self.log_q.put(f"VMC -> ME: {packet.hex().upper()}")

        if command == CMD_POLL:
            # VMC is polling us. Send a queued command or an ACK.
            if self.command_to_send:
                self.serial_port.write(self.command_to_send)
                self.log_q.put(
                    f"ME -> VMC: {self.command_to_send.hex().upper()} (In response to POLL)"
                )
                self.command_to_send = None  # Clear after sending
            else:
                self.serial_port.write(ACK_PACKET)
                self.log_q.put(f"ME -> VMC: {ACK_PACKET.hex().upper()} (ACKing POLL)")

        elif command == CMD_ACK:
            # VMC acknowledged our last command
            self.log_q.put("VMC acknowledged our command. Incrementing packet number.")
            self.comm_packet_no = (self.comm_packet_no % 255) + 1
            self.incoming_data_q.put({"type": "ACK"})

        elif command == CMD_VMC_DISPENSING_STATUS:
            # VMC sent a dispensing status update
            status_code = packet[5]
            selection_no = int.from_bytes(packet[6:8], "big")
            self.incoming_data_q.put(
                {
                    "type": "DISPENSE_STATUS",
                    "status_code": status_code,
                    "selection": selection_no,
                }
            )

        # Add other command handlers here (e.g., for CMD_VMC_REPORTS_PRICE)


def main_vending_flow():
    """Main function to run the vending machine simulation."""

    # --- 1. Initialization ---
    vmc_client = VendingMachineClient(SERIAL_PORT)
    if not vmc_client.connect():
        # Print logs if connection failed
        while not vmc_client.log_q.empty():
            print(f"[LOG] {vmc_client.log_q.get_nowait()}")
        return

    vmc_client.start_communication()

    try:
        while True:
            # --- Print any new logs from the background thread ---
            while not vmc_client.log_q.empty():
                print(f"[LOG] {vmc_client.log_q.get_nowait()}")

            # --- 2. Get Selection Number ---
            print("\n--- VENDING MACHINE MENU ---")
            for key, item in PRODUCT_MENU.items():
                print(f"  [{key}] {item['name']:<12} - ${item['price']:.2f}")
            print("----------------------------")

            selection_str = input("Enter the selection number (or 'quit' to exit): ")
            if selection_str.lower() == "quit":
                break

            try:
                selection_id = int(selection_str)
                selected_item = PRODUCT_MENU.get(selection_id)
                if not selected_item:
                    print("! Invalid selection. Please try again.")
                    continue
            except ValueError:
                print("! Invalid input. Please enter a number.")
                continue

            # --- 3. Simulate Cashless Payment ---
            item_price = selected_item["price"]
            print(f"You selected '{selected_item['name']}' for ${item_price:.2f}.")
            print("Simulating cashless payment...")

            # Convert price from float ($1.50) to integer cents (150) for the protocol
            price_in_cents = int(item_price * 100)

            # Per protocol 4.1.5: Mode (1 byte) + Amount (4 bytes)
            # We'll use Mode 6 (Alipay) as an example
            payment_mode = 6
            payment_data = payment_mode.to_bytes(1, "big") + price_in_cents.to_bytes(
                4, "big"
            )

            vmc_client.queue_command(CMD_UPPER_COMPUTER_RECEIVES_MONEY, payment_data)
            print("Waiting for payment confirmation from VMC...")

            # Wait for the VMC to ACK our payment command
            try:
                ack_response = vmc_client.incoming_data_q.get(timeout=5.0)
                if ack_response.get("type") != "ACK":
                    print("! Did not receive expected ACK for payment. Aborting.")
                    continue
                print("Payment confirmed by VMC.")
            except Empty:
                print("! Timeout: VMC did not respond to payment command. Aborting.")
                continue

            # --- 4. Handle Dispensing ---
            print(f"Requesting dispense for selection {selection_id}...")
            # Per protocol 4.3.2: selection number (2 bytes)
            selection_data = selection_id.to_bytes(2, "big")
            vmc_client.queue_command(CMD_UPPER_COMPUTER_SELECTS_TO_BUY, selection_data)

            # Wait for the VMC to send a final dispensing status
            print("Waiting for final dispensing status from VMC...")
            try:
                status_response = vmc_client.incoming_data_q.get(
                    timeout=15.0
                )  # Longer timeout for dispensing
                if status_response.get("type") == "DISPENSE_STATUS":
                    code = status_response["status_code"]
                    status_message = DISPENSE_STATUS_CODES.get(
                        code, f"Unknown status code: {code:02X}"
                    )
                    print(f"\n--- DISPENSE RESULT ---")
                    print(f"  Selection: {status_response['selection']}")
                    print(f"  Status: {status_message}")
                    print(f"-----------------------\n")
                else:
                    print(
                        "! Received unexpected message while waiting for dispense status."
                    )
            except Empty:
                print("! Timeout: VMC did not send a dispense status update.")

    except KeyboardInterrupt:
        print("\nUser requested exit.")
    finally:
        # --- Clean Shutdown ---
        print("Shutting down client...")
        vmc_client.stop_communication()
        # Print any final logs
        while not vmc_client.log_q.empty():
            print(f"[LOG] {vmc_client.log_q.get_nowait()}")
        print("Shutdown complete.")


if __name__ == "__main__":
    main_vending_flow()
