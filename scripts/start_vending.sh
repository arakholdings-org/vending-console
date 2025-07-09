#!/bin/bash

# Redirect output to log files
exec >> "/var/log/vending-console/vending-console.log" 2>> "/var/log/vending-console/vending-console.error.log"

echo "Starting Vending Console at $(date)"
cd "/home/kupa/Desktop/projects/vending-console"
"/home/kupa/Desktop/projects/vending-console/.venv/bin/python" "/home/kupa/Desktop/projects/vending-console/app.py"
