#!/usr/bin/env python3
import asyncio
import signal

from services import MQTTBroker, VendingMachine
from utils import app_logger


async def shutdown(signal, vm, broker):
    """Handle shutdown gracefully"""
    app_logger.info(f"Received {signal.name}, shutting down...")
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
        app_logger.info("Starting vending machine services...")

        # Connect vending machine (will auto-retry)
        await vm.connect()
        app_logger.info("Vending machine connection initiated")

        # Connect and start broker (will auto-retry)
        if broker.connect():
            app_logger.info("MQTT Broker initial connection successful")
        else:
            app_logger.warning(
                "MQTT Broker initial connection failed, will retry automatically"
            )

        asyncio.create_task(broker.start())

        app_logger.info(
            "All services started. Connections will be automatically maintained."
        )
        app_logger.info("Press Ctrl+C to shutdown...")

        # Keep running until shutdown
        while True:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break

    except asyncio.CancelledError:
        app_logger.info("Shutdown completed")
    except Exception as e:
        app_logger.error(f"Error: {e}")
    finally:
        app_logger.info("Cleaning up...")
        if vm.running:
            await vm.close()
        if broker.running:
            await broker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        app_logger.info("Shutdown by user")
