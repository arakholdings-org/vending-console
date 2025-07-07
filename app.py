#!/usr/bin/env python3
import asyncio
import signal

from services.vending import VendingMachine


async def shutdown(signal, vm):
    """Handle shutdown gracefully"""
    print(f"\nReceived {signal.name}, shutting down...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    await vm.close()
    await asyncio.gather(*tasks, return_exceptions=True)
    loop = asyncio.get_running_loop()
    loop.stop()


async def main():

    # Initialize the vending machine
    vm = VendingMachine(port="/dev/ttyUSB0", debug=True)

    # Set up signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s, vm)))

    try:
        await vm.connect()

        # Keep running until shutdown
        while True:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break

    except asyncio.CancelledError:
        print("\nShutdown completed")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if vm.running:
            await vm.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown by user")
