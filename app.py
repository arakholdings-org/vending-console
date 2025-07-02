#!/usr/bin/env python3
import asyncio
import signal
from services import VendingMachine


async def main():
    print("🧃 Vending Machine Console")
    print("=========================")

    # Initialize the vending machine
    vm = VendingMachine(port="/dev/ttyUSB0", debug=True)

    def signal_handler():
        print("\n\nShutting down gracefully...")
        asyncio.create_task(vm.close())

    # Set up signal handler for graceful shutdown
    loop = asyncio.get_event_loop()
    for signame in {"SIGINT", "SIGTERM"}:
        loop.add_signal_handler(getattr(signal, signame), signal_handler)

    try:
        await vm.connect()

        # Keep running until interrupted
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await vm.close()


if __name__ == "__main__":
    asyncio.run(main())
