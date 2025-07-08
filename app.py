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
    vm = VendingMachine(port="/dev/ttyUSB0", debug=True)

    # Initialize the MQTT broker with vending machine instance
    broker = MQTTBroker(vending_machine=vm)

    # Set up signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, lambda s=sig: asyncio.create_task(shutdown(s, vm, broker))
        )

    try:
        # Connect vending machine
        await vm.connect()

        # Connect and start broker
        if broker.connect():
            print("MQTT Broker connected successfully")
            broker_task = asyncio.create_task(broker.start())
        else:
            print("Failed to connect MQTT Broker")
            return

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
        if broker.running:
            await broker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown by user")
