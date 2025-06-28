#!/usr/bin/env python3
import time
from services import VendingMachine


def main():
    vm = VendingMachine(port="/dev/ttyUSB0", debug=True)

    try:
        print("Connecting to vending machine...")
        vm.connect()
        print("Ready to receive selection info...")

        # Keep running until interrupted
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        vm.close()


if __name__ == "__main__":
    main()
