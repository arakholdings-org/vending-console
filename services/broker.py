import json
import asyncio
from asyncio import Queue
import paho.mqtt.client as mqtt
import os


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

        # Subscribe to price update topic
        topic = f"vmc/{self.machine_id}/set_price"
        self.client.subscribe(topic)

    def _on_message(self, client, data, msg):
        """Queue incoming messages for async processing"""
        try:
            payload = json.loads(msg.payload.decode())
            # Put message in queue for async processing
            asyncio.run_coroutine_threadsafe(
                self.message_queue.put({"topic": msg.topic, "payload": payload}),
                self.loop
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

            except Exception as e:
                print(f"Error processing message from queue: {e}")
            finally:
                self.message_queue.task_done()

    async def _handle_price_update(self, payload):
        """Handle price update messages"""
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
                json.dumps({"success": False, "error": str(e)}),
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


# Usage example
if __name__ == "__main__":
    broker = MQTTBroker()
    if broker.connect():
        broker.publish("Terminal started")
        broker.start()
