#!/usr/bin/env python3
import asyncio
import signal

from services import VendingMachine, MQTTBroker


async def shutdown(signal, vm, broker):
    """Handle shutdown gracefully"""
    print(f"\nReceived {signal.name}, shutting down...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]

    # Close both vending machine and broker
    await vm.close()
    await broker.stop()

    await asyncio.gather(*tasks, return_exceptions=True)
    loop = asyncio.get_running_loop()
    loop.stop()


async def main():
    # Initialize the vending machine
    vm = VendingMachine(port="/dev/ttyVending", debug=True)

    # Initialize the MQTT broker with vending machine instance
    broker = MQTTBroker(vending_machine=vm)

    # Set up signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, lambda s=sig: asyncio.create_task(shutdown(s, vm, broker))
        )

    try:
        print("Starting vending machine services...")

        # Connect vending machine (will auto-retry)
        await vm.connect()
        print("Vending machine connection initiated")

        # Connect and start broker (will auto-retry)
        if broker.connect():
            print("MQTT Broker initial connection successful")
        else:
            print("MQTT Broker initial connection failed, will retry automatically")

        asyncio.create_task(broker.start())

        print("All services started. Connections will be automatically maintained.")
        print("Press Ctrl+C to shutdown...")

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
        print("Cleaning up...")
        if vm.running:
            await vm.close()
        if broker.running:
            await broker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown by user")
