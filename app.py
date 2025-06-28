#!/usr/bin/env python3
import asyncio
from services import VendingMachine


async def main():
    vm = VendingMachine(port="/dev/ttyUSB0", debug=True)

    try:
        print("Connecting to vending machine...")
        await vm.connect()
        print("Ready to receive selection info...")

        # Keep running until interrupted
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await vm.close()


if __name__ == "__main__":
    asyncio.run(main())
