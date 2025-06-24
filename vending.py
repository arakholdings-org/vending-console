from serial import Serial


class VendingMachine:
    def __init__(self, port: str = "/dev/USBtty0", baudrate: int = 57600):
        self.serial = Serial(port, baudrate, timeout=1)
        self.serial.flush()

    # send command to the vending machine

    def send_command(self, command: str) -> str:
        self.serial.write(command.encode("utf-8") + b"\n")
        response = self.serial.readline().decode("utf-8").strip()
        return response

    def get_status(self) -> str:
        return self.send_command("STATUS")

    def select_item(self, item_code: str) -> str:
        return self.send_command(f"SELECT {item_code}")

    def insert_money(self, amount: float) -> str:
        return self.send_command(f"INSERT {amount:.2f}")

    def dispense_item(self) -> str:
        return self.send_command("DISPENSE")
