#!/usr/bin/env bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

echo "Uninstalling Vending Console..."

# Get the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Check if cron job exists and remove it
if [ -f "/etc/cron.d/vending-console" ]; then
    echo "Removing cron job..."
    rm -f /etc/cron.d/vending-console
fi

# Remove udev rules
echo "Removing udev rules..."
rm -f /etc/udev/rules.d/99-vending-console.rules

# Remove log rotation config
echo "Removing log rotation configuration..."
rm -f /etc/logrotate.d/vending-console

# Remove log directory
echo "Removing log files..."
rm -rf /var/log/vending-console

# Ask if virtual environment should be removed
read -p "Do you want to remove the Python virtual environment? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Removing Python virtual environment..."
    rm -rf "$PROJECT_DIR/.venv"
fi

# Reload configurations
echo "Reloading system configurations..."
udevadm control --reload-rules
udevadm trigger

echo -e "${GREEN}Uninstallation complete${NC}"
echo "The Vending Console has been uninstalled from your system."
echo "Note: This script did not remove the project files themselves."