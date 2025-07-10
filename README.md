# Vending Console

A Python-based application for interfacing with vending machine control boards (VMC) through RS232 serial communication.

## Overview

This project provides a communication layer and control interface for vending machines, allowing for:

- Basic VMC communication via serial connection
- Command sending and handling for product dispensing
- Machine state monitoring
- Inventory management
- Payment using EFT , and Esocket Software

The application is designed to run on Linux systems with a serial connection to a vending machine control board.

## System Architecture

The application is built around several core components:

- **Serial Communication Manager**: Handles low-level RS232 communication with the VMC
- **Command Handler**: Processes and creates command packets
- **State Manager**: Tracks the current state of the vending machine
- **Message Builder**: Constructs properly formatted packets
- **Main Loop Handler**: Coordinates the communication flow

### Communication Flow

```
[Main Loop] -> [Serial Manager] -> [VMC]
     ↑              ↑               |
     |              |               |
     └──────────────┴───────────────┘
```

## Features

- **Asynchronous Communication**: Built with asyncio for efficient I/O operations
- **MQTT Integration**: Provides remote control capabilities
- **Payment System Support**: Integration with EFT payment terminal through eSocket
- **Automatic Recovery**: Handles connection disruptions and service failures
- **Comprehensive Logging**: Detailed operational and error logging
- **Database Storage**: TinyDB-based inventory and pricing management

## Key Components

### Services

- **VendingMachine**: Core class handling VMC communication
- **MQTTBroker**: Handles external communication via MQTT
- **ESocketClient**: Interfaces with payment terminals

### Utils

- **Command Definitions**: Centralized registry of VMC commands
- **Message Building**: Utilities for packet construction
- **Inventory Management**: Product and stock tracking
- **Logging**: Comprehensive logging system

## Setup and Installation

Installation scripts are provided in the `scripts` directory:

- **install.sh**: Sets up the service, configures udev rules, and installs dependencies
- **start_vending.sh**: Runs the vending console application
- **uninstall.sh**: Removes the service and configuration

### Prerequisites

- Python 3.12 or higher
- Linux system with serial port
- USB-to-Serial adapter (if connecting to VMC via USB)

### Installation Steps

1. Clone the repository:

   ```bash
   git clone https://github.com/yourusername/vending-console.git
   cd vending-console
   ```

2. Run the installation script:

   ```bash
   sudo ./scripts/install.sh
   ```

3. The script will:
   - Configure udev rules for serial port access
   - Create necessary directories and permissions
   - Set up auto-start service
   - Install required dependencies

## Configuration

The system uses several configuration files:

- **config.json**: Main configuration file with broker settings and machine ID
- **config/99-vending-usb.rules**: udev rules for USB-serial device permissions

## Documentation

Detailed documentation is available in the `docs` directory:

- **vending.md**: VMC communication protocol specifications
- **payment.md**: eSocket XML API documentation for payment integration
- **hexcodes.txt**: Reference for command hex codes
- **work_plan.md**: Project roadmap and implementation plan

## Dependencies

- **pyserial-asyncio**: Asynchronous serial communication
- **paho-mqtt**: MQTT client for remote control
- **tinydb**: Lightweight document-oriented database

## Development

### Project Structure

```
vending-console/
├── app.py                # Main application entry point
├── config.json           # Configuration file
├── db.json               # TinyDB database file
├── config/               # System configuration files
├── db/                   # Database modules
├── docs/                 # Documentation
├── logs/                 # Log files directory
├── scripts/              # Installation and utility scripts
├── services/             # Core service modules
└── utils/                # Utility functions and helpers
```

## License

[Your License]

## Contributing

[Your Contribution Guidelines]
