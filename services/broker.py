import json
import paho.mqtt.client as mqtt
import os


class MQTTBroker:
    def __init__(self):
        # Load config file
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config.json"
        )
        with open(config_path, "r") as config_file:
            config = json.load(config_file)

        self.broker = config["BROKER_IP"]
        self.port = config["BROKER_PORT"]
        self.terminal_id = config["TERMINAL_ID"]

        # Initialize MQTT client
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, data, flags, rc):
        """Callback when connected to MQTT broker"""
        print(f"Connected to broker {self.broker} with result code {str(rc)}")

        # Subscribe to multiple topics with their QoS levels
        topics = [("kups", 0), ("kups/status", 0), ("kups/commands", 0)]
        self.client.subscribe(topics)

    def _on_message(self, client, data, msg):
        """Callback when a message is received"""
        print(f"Message received on {msg.topic}: {msg.payload.decode()}")

    def connect(self):
        """Connect to MQTT broker"""
        try:
            self.client.connect(self.broker, self.port, 60)
            return True
        except Exception as e:
            print(f"Failed to connect to broker: {e}")
            return False

    def publish(self, message):
        """Publish a message to the topic"""
        self.client.publish(self.topic, message)

    def start(self):
        """Start listening for messages"""
        self.client.loop_forever()

    def stop(self):
        """Stop the MQTT client"""
        self.client.loop_stop()
        self.client.disconnect()


# Usage example
if __name__ == "__main__":
    broker = MQTTBroker()
    if broker.connect():
        broker.publish("Terminal started")
        broker.start()
