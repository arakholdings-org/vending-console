import json
import os
from typing import Any, Dict, List

class POSConfig:
    def __init__(self, config_path: str = "pos_config.json"):
        self.config_path = config_path
        # Support multiple currencies from env or default to USD,ZiG
        currency_env = os.getenv("CURRENCY", "USD,ZiG")
        if isinstance(currency_env, str):
            currencies = [c.strip() for c in currency_env.split(",")]
        else:
            currencies = ["USD", "ZiG"]
        self.settings = {
            "port": os.getenv("SERIAL_PORT", "COM1"),  # Default to COM1 for RS232 MiniPC
            "baudrate": int(os.getenv("SERIAL_BAUDRATE", "9600")),  # 9600 for RS232
            "currency": currencies,
            "accepted_payments": ["card", "ecocash"],
            "esocket_host": os.getenv("ESOCKET_HOST", "127.0.0.1"),
            "esocket_port": int(os.getenv("ESOCKET_PORT", "23001")),
            "esocket_terminal_id": os.getenv("ESOCKET_TERMINAL_ID", "ARAVON10"),
            # Add more default settings as needed
        }
        self.load()

    def load(self):
        try:
            with open(self.config_path, "r") as f:
                loaded = json.load(f)
                # Ensure currency is always a list
                if "currency" in loaded and isinstance(loaded["currency"], str):
                    loaded["currency"] = [c.strip() for c in loaded["currency"].split(",")]
                self.settings.update(loaded)
        except FileNotFoundError:
            self.save()  # Save defaults if config doesn't exist

    def save(self):
        # Save currency as comma-separated string for compatibility
        to_save = self.settings.copy()
        if isinstance(to_save.get("currency"), list):
            to_save["currency"] = ",".join(to_save["currency"])
        with open(self.config_path, "w") as f:
            json.dump(to_save, f, indent=4)

    def update(self, key: str, value: Any):
        if key == "currency" and isinstance(value, str):
            value = [c.strip() for c in value.split(",")]
        self.settings[key] = value
        self.save()

    def get(self, key: str) -> Any:
        return self.settings.get(key)

    def display(self) -> Dict[str, Any]:
        return self.settings
