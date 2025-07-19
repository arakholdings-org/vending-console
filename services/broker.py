import asyncio
import json
import os
import time
from asyncio import Queue

import paho.mqtt.client as mqtt

from db import Prices, query ,Sales
from utils import broker_logger as logger


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
        self.client.on_disconnect = self._on_disconnect
        self.running = False
        self.connected = False

        self.loop = asyncio.get_event_loop()

        # Connection monitoring
        self._connection_monitor_task = None
        self._reconnect_delay = 5  # seconds
        self._max_reconnect_delay = 60  # seconds

    def _on_connect(self, client, data, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            self.connected = True
            logger.info(
                f"Connected to MQTT broker {self.broker} with result code {str(rc)}"
            )

            # Subscribe to topics
            topics = [
                f"vmc/{self.machine_id}/set_price",
                f"vmc/{self.machine_id}/get_prices",
                f"vmc/{self.machine_id}/set_inventory",
                f"vmc/{self.machine_id}/set_capacity",
                f"vmc/{self.machine_id}/ping",
                f"vmc/{self.machine_id}/get_sales"
            ]
            for topic in topics:
                self.client.subscribe(topic)
        else:
            self.connected = False
            logger.error(f"Failed to connect to MQTT broker, return code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT broker"""
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected disconnection from MQTT broker, code: {rc}")
        else:
            logger.info("Disconnected from MQTT broker")

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
                    },
                ),
                self.loop,
            )
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON payload received: {msg.payload}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def process_messages(self):
        """Process messages from queue"""
        while self.running:
            try:
                message = await asyncio.wait_for(self.message_queue.get(), timeout=1.0)

                # Only process messages if connected
                if not self.connected:
                    logger.warning("Skipping message processing - MQTT not connected")
                    continue

                topic = message["topic"]
                payload = message["payload"]

                if topic == f"vmc/{self.machine_id}/set_price":
                    await self._handle_price_update(payload)
                elif topic == f"vmc/{self.machine_id}/get_prices":
                    await self._handle_get_prices()
                elif topic == f"vmc/{self.machine_id}/set_inventory":
                    await self._handle_inventory_update(payload)
                elif topic == f"vmc/{self.machine_id}/set_capacity":
                    await self._handle_capacity_update(payload)
                elif topic == f"vmc/{self.machine_id}/ping":
                    await self._handle_ping(payload)
                elif topic == f"vmc/{self.machine_id}/get_inventory_by_tray":
                    await self._handle_get_inventory_by_tray(payload)
                elif topic == f"vmc/{self.machine_id}/get_sales":
                    await self._handle_get_sales()
                   

            except asyncio.TimeoutError:
                # Timeout is normal, continue
                continue
            except Exception as e:
                logger.error(f"Error processing message from queue: {e}")
            finally:
                try:
                    self.message_queue.task_done()
                except:
                    pass

    async def _monitor_connection(self):
        """Monitor MQTT connection and reconnect if needed"""
        delay = self._reconnect_delay

        while self.running:
            try:
                if not self.connected:
                    logger.info(
                        f"MQTT not connected, attempting reconnect in {delay}s..."
                    )
                    await asyncio.sleep(delay)

                    if self.running:  # Check if still running after sleep
                        if self._connect_internal():
                            delay = self._reconnect_delay  # Reset delay on success
                        else:
                            delay = min(delay * 2, self._max_reconnect_delay)
                else:
                    delay = self._reconnect_delay  # Reset delay when connected
                    await asyncio.sleep(5)  # Check every 5 seconds when connected

            except Exception as e:
                logger.error(f"Connection monitor error: {e}")
                await asyncio.sleep(delay)

    def _connect_internal(self):
        """Internal connection method"""
        try:
            self.client.connect(self.broker, self.port, 60)
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False

    async def _handle_get_sales(self):
        """Handle get sales request"""
        sales_data = Sales.all()
        response = {
            "success": True,
            "sales": sales_data,
                    }
        self.client.publish(
                    f"vmc/{self.machine_id}/sales_update_status", json.dumps(response)
                )
        return response

    async def _handle_price_update(self, payload):
        """Handle price update messages from MQTT with connection checks"""
        try:
            if not self.vending_machine:
                logger.error("No vending machine instance available")
                return

            if not self.connected:
                logger.warning("Cannot handle price update - MQTT not connected")
                return

            tray_number = payload.get("tray")
            price = payload.get("price")
            selection = payload.get("selection")
            set_all = payload.get("all", False)

            if price is None and not set_all:
                logger.error("Missing required fields in price update payload")
                return

            results = []
            success = False

            if selection is not None:
                if not (1 <= selection <= 100):
                    logger.error("Invalid selection: must be between 1 and 100")
                    return
                # Use upsert instead of update
                Prices.upsert(
                    {
                        "selection": selection,
                        "price": price,
                    },
                    query.selection == selection,
                )
                data = selection.to_bytes(2, byteorder="big") + price.to_bytes(
                    4, byteorder="big"
                )
                # Send command to vending machine (protocol: 0x12, selection(2), price(4))
                vm_result = await self.vending_machine.queue_command("SET_PRICE", data)
                results.append({"selection": selection, "success": vm_result})
                success = vm_result

            elif tray_number is not None:
                special_sel = 1000 + tray_number
                start_selection = tray_number * 10 + 1
                for i in range(10):
                    sel = start_selection + i
                    # Use upsert for each selection in tray
                    Prices.upsert(
                        {
                            "selection": sel,
                            "price": price,
                        },
                        query.selection == sel,
                    )
                # Send one command to vending machine for the tray
                data = special_sel.to_bytes(2, byteorder="big") + price.to_bytes(
                    4, byteorder="big"
                )
                vm_result = await self.vending_machine.queue_command("SET_PRICE", data)
                results.append(
                    {
                        "tray": tray_number,
                        "special_selection": special_sel,
                        "success": vm_result,
                    }
                )
                success = vm_result

            elif set_all:
                special_sel = 0000
                # Update local database first
                for sel in range(1, 101):
                    Prices.upsert(
                        {
                            "selection": sel,
                            "price": price,
                        },
                        query.selection == sel,
                    )

                # Format command for all selections (0000)
                # Protocol: Command 0x12, special selection (2 bytes) + price (4 bytes)
                data = (special_sel).to_bytes(2, byteorder="big") + price.to_bytes(
                    4, byteorder="big", signed=False
                )
                vm_result = await self.vending_machine.queue_command("SET_PRICE", data)

                if not vm_result:
                    logger.error("Failed to send SET_PRICE command to VMC")
                    # Optionally revert database changes here
            else:
                logger.error(
                    "No valid selection, tray, or all flag provided for price update"
                )
                return

            # Publish response only if connected
            if self.connected:
                response = {
                    "success": success,
                    "tray": tray_number if tray_number is not None else None,
                    "selection": selection if selection is not None else None,
                    "price": price,
                    "results": results,
                }
                self.client.publish(
                    f"vmc/{self.machine_id}/price_update_status", json.dumps(response)
                )

        except Exception as e:
            logger.error(f"Error handling price update: {e}")
            # Publish error response only if connected
            if self.connected:
                self.client.publish(
                    f"vmc/{self.machine_id}/price_update_status",
                    json.dumps({"success": False, "error": str(e)}),
                )

    async def _handle_inventory_update(self, payload):
        """Handle inventory update messages from MQTT"""
        try:
            if not self.vending_machine:
                logger.error("No vending machine instance available")
                return

            if not self.connected:
                logger.warning("Cannot handle inventory update - MQTT not connected")
                return

            tray_number = payload.get("tray")
            inventory = payload.get("inventory")
            selection = payload.get("selection")
            set_all = payload.get("all", False)

            if inventory is None and not set_all:
                logger.error("Missing inventory value in payload")
                return

            if not (0 <= inventory <= 255):
                logger.error("Invalid inventory value: must be between 0 and 255")
                return

            results = []
            success = False

            if selection is not None:
                if not (1 <= selection <= 100):
                    logger.error("Invalid selection: must be between 1 and 100")
                    return
                # Use upsert instead of update
                Prices.upsert(
                    {
                        "selection": selection,
                        "inventory": inventory,
                    },
                    query.selection == selection,
                )
                # Send command to vending machine
                data = selection.to_bytes(2, byteorder="big") + inventory.to_bytes(
                    1, byteorder="big", signed=False
                )
                vm_result = await self.vending_machine.queue_command(
                    "SET_INVENTORY", data
                )
                results.append({"selection": selection, "success": vm_result})
                success = vm_result

            elif tray_number is not None:
                # Use special selection number for tray: 1000 + tray_number
                special_sel = 1000 + tray_number
                # Update all selections in local DB for this tray
                start_selection = tray_number * 10 + 1
                for i in range(10):
                    sel = start_selection + i
                    Prices.upsert(
                        {
                            "inventory": inventory,
                        },
                        query.selection == sel,
                    )
                # Send one command to vending machine for the tray
                data = special_sel.to_bytes(2, byteorder="big") + inventory.to_bytes(
                    1, byteorder="big", signed=False
                )
                vm_result = await self.vending_machine.queue_command(
                    "SET_INVENTORY", data
                )
                results.append(
                    {
                        "tray": tray_number,
                        "special_selection": special_sel,
                        "success": vm_result,
                    }
                )
                success = vm_result

            elif set_all:
                # Use special selection 0000 for all selections
                for sel in range(1, 101):
                    Prices.upsert(
                        {
                            "inventory": inventory,
                        },
                        query.selection == sel,
                    )
                # Send command with special selection 0000
                data = (0).to_bytes(2, byteorder="big") + inventory.to_bytes(
                    1, byteorder="big", signed=False
                )
                vm_result = await self.vending_machine.queue_command(
                    "SET_INVENTORY", data
                )
                results.append(
                    {"all": True, "special_selection": 0, "success": vm_result}
                )
                success = vm_result

            else:
                logger.error(
                    "No valid selection, tray, or all flag provided for inventory update"
                )
                return

            # Publish response only if connected
            if self.connected:
                response = {
                    "success": success,
                    "tray": tray_number if tray_number is not None else None,
                    "selection": selection if selection is not None else None,
                    "inventory": inventory,
                    "results": results,
                }
                self.client.publish(
                    f"vmc/{self.machine_id}/inventory_update_status",
                    json.dumps(response),
                )

        except Exception as e:
            logger.error(f"Error handling inventory update: {e}")
            if self.connected:
                self.client.publish(
                    f"vmc/{self.machine_id}/inventory_update_status",
                    json.dumps({"success": False, "error": str(e)}),
                )

    async def _handle_capacity_update(self, payload):
        """Handle capacity update messages from MQTT"""
        try:
            if not self.vending_machine:
                logger.error("No vending machine instance available")
                return

            if not self.connected:
                logger.warning("Cannot handle capacity update - MQTT not connected")
                return

            tray_number = payload.get("tray")
            capacity = payload.get("capacity")
            selection = payload.get("selection")
            set_all = payload.get("all", False)

            if capacity is None and not set_all:
                logger.error("Missing capacity value in payload")
                return

            if not (0 <= capacity <= 255):
                logger.error("Invalid capacity value: must be between 0 and 255")
                return

            results = []
            success = False

            if selection is not None:
                # Update single selection
                if not (1 <= selection <= 100):
                    logger.error("Invalid selection: must be between 1 and 100")
                    return
                # Update local DB
                Prices.update({"capacity": capacity}, query.selection == selection)
                # Send command to vending machine
                data = selection.to_bytes(2, byteorder="big") + capacity.to_bytes(
                    1, byteorder="big", signed=False
                )
                vm_result = await self.vending_machine.queue_command(
                    "SET_CAPACITY", data
                )
                results.append({"selection": selection, "success": vm_result})
                success = vm_result

            elif tray_number is not None:
                # Use special selection number for tray: 1000 + tray_number
                special_sel = 1000 + tray_number
                # Update all selections in local DB for this tray
                start_selection = tray_number * 10 + 1
                for i in range(10):
                    sel = start_selection + i
                    Prices.update({"capacity": capacity}, query.selection == sel)
                # Send one command to vending machine for the tray
                data = special_sel.to_bytes(2, byteorder="big") + capacity.to_bytes(
                    1, byteorder="big", signed=False
                )
                vm_result = await self.vending_machine.queue_command(
                    "SET_CAPACITY", data
                )
                results.append(
                    {
                        "tray": tray_number,
                        "special_selection": special_sel,
                        "success": vm_result,
                    }
                )
                success = vm_result

            elif set_all:
                # Use special selection 0000 for all selections
                for sel in range(1, 101):
                    Prices.update({"capacity": capacity}, query.selection == sel)
                # Send command with special selection 0000
                data = (0).to_bytes(2, byteorder="big") + capacity.to_bytes(
                    1, byteorder="big", signed=False
                )
                vm_result = await self.vending_machine.queue_command(
                    "SET_CAPACITY", data
                )
                results.append(
                    {
                        "all": True,
                        "special_selection": 0,
                        "success": vm_result,
                    }
                )
                success = vm_result

            else:
                logger.error(
                    "No valid selection, tray, or all flag provided for capacity update"
                )
                return

            # Publish response only if connected
            if self.connected:
                response = {
                    "success": success,
                    "tray": tray_number if tray_number is not None else None,
                    "selection": selection if selection is not None else None,
                    "capacity": capacity,
                    "results": results,
                }
                self.client.publish(
                    f"vmc/{self.machine_id}/capacity_update_status",
                    json.dumps(response),
                )

        except Exception as e:
            logger.error(f"Error handling capacity update: {e}")
            if self.connected:
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
                        "selection": price.get("selection"),
                        "price": price.get("price"),
                        "inventory": price.get("inventory"),
                        "capacity": price.get("capacity"),
                    },
                )

            # Publish response
            response = {
                "success": True,
                "prices": prices_list,
            }
            self.client.publish(f"vmc/{self.machine_id}/prices", json.dumps(response))

        except Exception as e:
            logger.error(f"Error handling get prices request: {e}")
            self.client.publish(
                f"vmc/{self.machine_id}/prices",
                json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                    }
                ),
            )

    async def _handle_ping(self, payload):
        """Handle ping messages and respond with pong"""
        try:
            # Create response with timestamp and any additional info from payload
            response = {
                "status": "pong",
                "timestamp": int(time.time()),
                "machine_id": self.machine_id,
            }

            # Add any fields from the original payload to the response
            if isinstance(payload, dict):
                for key, value in payload.items():
                    if key not in response:
                        response[key] = value

            # Publish the response
            self.client.publish(f"vmc/{self.machine_id}/pong", json.dumps(response))

        except Exception as e:
            logger.error(f"Error handling ping: {e}")
            self.client.publish(
                f"vmc/{self.machine_id}/pong",
                json.dumps(
                    {
                        "status": "error",
                        "error": str(e),
                    }
                ),
            )

    async def _handle_get_inventory_by_tray(self, payload):
        """Handle get inventory by tray request"""
        try:
            tray_number = payload.get("tray")
            if tray_number is None:
                logger.error("Tray number not provided in payload")
                response = {"success": False, "error": "Tray number not provided"}
            else:
                inventory_list = self.get_inventory_by_tray(tray_number)
                response = {
                    "success": True,
                    "tray": tray_number,
                    "data": inventory_list,
                }
            self.client.publish(
                f"vmc/{self.machine_id}/inventory_by_tray_status", json.dumps(response)
            )
        except Exception as e:
            logger.error(f"Error handling get inventory by tray: {e}")
            self.client.publish(
                f"vmc/{self.machine_id}/inventory_by_tray",
                json.dumps({"success": False, "error": str(e)}),
            )

    def connect(self):
        """Connect to MQTT broker"""
        return self._connect_internal()

    async def start(self):
        """Start broker operations"""
        self.running = True

        # Start connection monitoring
        self._connection_monitor_task = asyncio.create_task(self._monitor_connection())

        # Start MQTT client
        self.client.loop_start()

        # Start processing messages
        await self.process_messages()

    async def stop(self):
        """Stop broker operations"""
        self.running = False
        self.connected = False

        # Cancel connection monitoring
        if self._connection_monitor_task:
            self._connection_monitor_task.cancel()
            try:
                await self._connection_monitor_task
            except asyncio.CancelledError:
                pass

        # Stop MQTT client
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("MQTT broker stopped")

    def get_inventory_by_tray(self, tray_number):
        """
        Returns a list of inventory values for all selections in the given tray.
        Tray 0: selections 1-10, Tray 1: 11-20, etc.
        """
        start_selection = tray_number * 10 + 1
        end_selection = start_selection + 9
        selections = Prices.search(
            (query.selection >= start_selection) & (query.selection <= end_selection)
        )
        return [
            {"selection": item["selection"], "inventory": item.get("inventory", 0)}
            for item in selections
        ]
