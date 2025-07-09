#!/bin/bash

if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

echo "Uninstalling Vending Console..."

# Stop and disable service
systemctl stop vending-console
systemctl disable vending-console

# Remove service files
rm -f /etc/systemd/system/vending-console.service
rm -f /etc/udev/rules.d/99-vending-console.rules
rm -f /etc/logrotate.d/vending-console

# Remove logs
rm -rf /var/log/vending-console

# Reload configurations
systemctl daemon-reload
udevadm control --reload-rules

echo "Uninstallation complete"