#!/bin/bash

# Redirect output to log files
exec >> "/var/log/vending-console/vending-console.log" 2>> "/var/log/vending-console/vending-console.error.log"

echo "Starting Vending Console at $(date)"
cd "/home/tayiya/vending-console"
"/home/tayiya/vending-console/.venv/bin/python" "/home/tayiya/vending-console/app.py"
