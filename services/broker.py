import json
import asyncio
from asyncio import Queue
import paho.mqtt.client as mqtt
import os
from db import Prices, query


class MQTTBroker:
    def __init__(self, vending_machine=None):
        # Load config file
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config.json"
        )
        with open(config_path, "r") as config_file:
            config = json.load(config_file)

        self.broker = config["BROKER_IP"]
        self.port = config["BROKER_PORT"]
        self.machine_id = config["MACHINE_ID"]
        self.vending_machine = vending_machine
        self.message_queue = Queue()

        # Initialize MQTT client
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.running = False

        self.loop = asyncio.get_event_loop()

    def _on_connect(self, client, data, flags, rc):
        """Callback when connected to MQTT broker"""
        print(f"Connected to broker {self.broker} with result code {str(rc)}")

        # Subscribe to topics
        topics = [
            f"vmc/{self.machine_id}/set_price",
            f"vmc/{self.machine_id}/get_prices",
            f"vmc/{self.machine_id}/set_inventory",
            f"vmc/{self.machine_id}/set_capacity",
        ]
        for topic in topics:
            self.client.subscribe(topic)

    def _on_message(self, client, data, msg):
        """Queue incoming messages for async processing"""
        try:
            payload = json.loads(msg.payload.decode())
            # Put message in queue for async processing
            asyncio.run_coroutine_threadsafe(
                self.message_queue.put(
                    {
                        "topic": msg.topic,
                        "payload": payload,
                    }
                ),
                self.loop,
            )
        except json.JSONDecodeError:
            print(f"Invalid JSON payload received: {msg.payload}")
        except Exception as e:
            print(f"Error processing message: {e}")

    async def process_messages(self):
        """Process messages from queue"""
        while self.running:
            try:
                message = await self.message_queue.get()
                topic = message["topic"]
                payload = message["payload"]

                if topic == f"vmc/{self.machine_id}/set_price":
                    await self._handle_price_update(payload)
                elif topic == f"vmc/{self.machine_id}/get_prices":  # Add new condition
                    await self._handle_get_prices()
                elif topic == f"vmc/{self.machine_id}/set_inventory":
                    await self._handle_inventory_update(payload)
                elif topic == f"vmc/{self.machine_id}/set_capacity":
                    await self._handle_capacity_update(payload)

            except Exception as e:
                print(f"Error processing message from queue: {e}")
            finally:
                self.message_queue.task_done()

    async def _handle_price_update(self, payload):
        """Handle price update messages from MQTT"""
        try:
            if not self.vending_machine:
                print("No vending machine instance available")
                return

            tray_number = payload.get("tray")
            price = payload.get("price")

            if tray_number is None or price is None:
                print("Missing required fields in price update payload")
                return

            # Call the async set_product_price method
            success = await self.vending_machine.set_product_price(tray_number, price)

            # Publish response
            response = {
                "success": success,
                "tray": tray_number,
                "price": price,
            }
            self.client.publish(
                f"vmc/{self.machine_id}/price_update_status", json.dumps(response)
            )

        except Exception as e:
            print(f"Error handling price update: {e}")
            # Publish error response
            self.client.publish(
                f"vmc/{self.machine_id}/price_update_status",
                json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                    }
                ),
            )

    async def _handle_inventory_update(self, payload):
        """Handle inventory update messages"""
        try:
            if not self.vending_machine:
                print("No vending machine instance available")
                return

            selections = payload.get("selections", [])
            inventory = payload.get("inventory")

            # Convert single selection to list
            if isinstance(selections, int):
                selections = [selections]

            if not selections or inventory is None:
                print("Missing required fields in inventory update payload")
                return

            if not (0 <= inventory <= 255):
                print("Invalid inventory value: must be between 0 and 255")
                return

            results = []
            # Update each selection
            for selection in selections:
                # Update local database first
                selection_data = Prices.get(query.selection == selection)
                if selection_data:
                    Prices.update(
                        {
                            "inventory": inventory,
                        },
                        query.selection == selection,
                    )

                    # Create inventory update command for VMC
                    # Command 0x13: Set inventory
                    inventory_data = selection.to_bytes(2, byteorder="big") + bytes(
                        [inventory]
                    )
                    success = await self.vending_machine.queue_command(
                        "SET_INVENTORY", inventory_data
                    )

                    results.append(
                        {
                            "selection": selection,
                            "success": success,
                        }
                    )
                else:
                    results.append(
                        {
                            "selection": selection,
                            "success": False,
                            "error": "Selection not found in database",
                        }
                    )

            # Publish response
            response = {
                "success": any(r["success"] for r in results),
                "results": results,
            }
            self.client.publish(
                f"vmc/{self.machine_id}/inventory_update_status", json.dumps(response)
            )

        except Exception as e:
            print(f"Error handling inventory update: {e}")
            self.client.publish(
                f"vmc/{self.machine_id}/inventory_update_status",
                json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                    }
                ),
            )

    async def _handle_capacity_update(self, payload):
        """Handle capacity update messages for entire trays"""
        try:
            if not self.vending_machine:
                print("No vending machine instance available")
                return

            tray_number = payload.get("tray")
            capacity = payload.get("capacity")

            if tray_number is None or capacity is None:
                print("Missing required fields in capacity update payload")
                return

            if not (0 <= tray_number <= 9):
                print("Invalid tray number: must be between 0 and 9")
                return

            if not (0 <= capacity <= 255):
                print("Invalid capacity value: must be between 0 and 255")
                return

            # Special selection number for entire tray (1000 + tray_number)
            tray_selection = 1000 + tray_number

            # Create capacity update command for VMC
            # Command 0x14: Set capacity
            capacity_data = tray_selection.to_bytes(2, byteorder="big") + bytes(
                [capacity]
            )
            success = await self.vending_machine.queue_command(
                "SET_CAPACITY", capacity_data
            )

            if success:
                # Update local database for all selections in tray
                base_selection = tray_number * 10
                for i in range(10):  # 10 selections per tray
                    selection = base_selection + i
                    Prices.update(
                        {
                            "capacity": capacity,
                        },
                        query.selection == selection,
                    )

            # Publish response
            response = {
                "success": success,
                "tray": tray_number,
                "capacity": capacity,
            }
            self.client.publish(
                f"vmc/{self.machine_id}/capacity_update_status", json.dumps(response)
            )

        except Exception as e:
            print(f"Error handling capacity update: {e}")
            self.client.publish(
                f"vmc/{self.machine_id}/capacity_update_status",
                json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                    }
                ),
            )

    async def _handle_get_prices(self):
        """Handle get prices request"""
        try:
            # Query all price records from database
            all_prices = Prices.all()

            # Format the response
            prices_list = []
            for price in all_prices:
                prices_list.append(
                    {
                        "selection": price.selection,
                        "price": price.price,
                        "inventory": price.inventory,
                        "capacity": price.capacity,
                    }
                )

            # Publish response
            response = {
                "success": True,
                "prices": prices_list,
            }
            self.client.publish(f"vmc/{self.machine_id}/prices", json.dumps(response))

        except Exception as e:
            print(f"Error handling get prices request: {e}")
            self.client.publish(
                f"vmc/{self.machine_id}/prices",
                json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                    }
                ),
            )

    def connect(self):
        """Connect to MQTT broker"""
        try:
            self.client.connect(self.broker, self.port, 60)
            return True
        except Exception as e:
            print(f"Failed to connect to broker: {e}")
            return False

    async def start(self):
        """Start broker operations"""
        self.running = True
        self.client.loop_start()  # Start MQTT client in separate thread
        await self.process_messages()  # Start processing messages

    async def stop(self):
        """Stop broker operations"""
        self.running = False
        self.client.loop_stop()
        self.client.disconnect()
