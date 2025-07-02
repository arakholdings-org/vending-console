#!/usr/bin/env python3
import time
import signal
from services import VendingMachine


def main():
    print("🧃 Vending Machine Console")
    print("=========================")

    # Initialize the vending machine
    vm = VendingMachine(port="/dev/ttyUSB0", debug=True)

    def signal_handler(sig, frame):
        print("\n\nShutting down gracefully...")
        vm.close()
        exit(0)

    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)

    try:

        vm.connect()

        # Keep running until interrupted
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        vm.close()


if __name__ == "__main__":
    main()
