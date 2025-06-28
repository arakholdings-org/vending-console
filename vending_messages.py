from commands import COMMANDS, HEADER_BYTES

class VendingMessages:
    @staticmethod
    def recieve_money(amount: int):
        # Example: build recieve_money message (amount in cents)
        data = HEADER_BYTES + [
            COMMANDS["recieve_money"],
            0x06,  # Length byte for recieve_money
            0x00,  # Placeholder for sequence or other
            0x03,  # Placeholder
            0, 20, 0, 0  # Example payload, adjust as needed
        ]
        data.append(VendingMessages.calculate_bcc(data))
        return bytes(data)

    @staticmethod
    def cancel_selection():
        data = HEADER_BYTES + [
            COMMANDS["cancel_selection"],
            0x03, 0x00, 0x00
        ]
        data.append(VendingMessages.calculate_bcc(data))
        return bytes(data)

    @staticmethod
    def calculate_bcc(data):
        # Simple XOR of all bytes for BCC (adjust if protocol differs)
        bcc = 0
        for b in data:
            bcc ^= b
        return bcc

    @staticmethod
    def send_message(serial, message: bytes):
        serial.write(message)
        serial.flush()

    @staticmethod
    def receive_response(serial, timeout=2):
        serial.timeout = timeout
        response = serial.readline()
        return response

    @staticmethod
    def send_and_receive(serial, message: bytes, timeout=2):
        VendingMessages.send_message(serial, message)
        return VendingMessages.receive_response(serial, timeout)

    @staticmethod
    def parse_status(response: bytes):
        # Assumes status code is at a fixed position, e.g., 5th byte
        if len(response) < 6:
            return "Invalid response"
        status_code = response[5]
        status_map = {
            0x01: "Normal status (operation in progress)",
            0x02: "Success status (decrement quantity)",
            0x03: "Jam error",
            0x04: "Motor doesn't stop error",
            0x06: "Motor doesn't exist error",
            0x07: "Elevator error",
        }
        return status_map.get(status_code, f"Unknown status: {status_code:#02x}")
