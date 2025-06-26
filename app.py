#!/usr/bin/env python3
import sys
import serial
import time
import traceback

from services.vending import VendingMachine


def handle_vmc_selection(selection_number):
    """Callback function to handle selections from VMC"""
    if selection_number == 0:
        print("Selection cancelled")
    else:
        # Let the VendingMachine class handle the selection automatically
        pass


def main():
    vending = None
    try:
        print("\n==== Vending Machine Console ====\n")
        print("Connecting to vending machine...")

        # Initialize vending machine with debug enabled for better error diagnosis
        vending = VendingMachine(debug=True)
        print("Successfully connected to vending machine")

        # Set up selection callback
        vending.set_selection_callback(handle_vmc_selection)

        print("\nStarting communication with vending machine...")
        # Start polling thread
        vending.start_polling()

        print("Ready - Waiting for customer selections")
        print("\nNOTE: Running in TEST MODE - No payment required!")
        print("Products will dispense automatically after selection")
        print("\n====================================")
        print("Press Ctrl+C to exit")

        # Keep the main thread running while handling exceptions in the background
        while True:
            time.sleep(0.1)

            # Check if poll thread is still alive, restart if needed
            if vending.poll_thread is not None and not vending.poll_thread.is_alive():
                print("\n⚠️ Polling thread died, restarting...")
                vending.start_polling()
                print("Polling thread restarted")

    except serial.SerialException as e:
        print(f"\nERROR: Failed to connect to vending machine:")
        print(f"  - {e}")
        print("\nPossible solutions:")
        print("  1. Check if the USB device is properly connected")
        print("  2. Verify you have correct permissions to access the serial port")
        print("  3. Try running with sudo if it's a permissions issue")
        print("  4. Modify the port in the VendingMachine constructor if needed")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nExiting...")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        traceback.print_exc()
    finally:
        if vending:
            print("Closing connection to vending machine...")
            vending.close()
            print("Done!")


if __name__ == "__main__":
    main()
