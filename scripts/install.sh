#!/usr/bin/env bash


# Exit on any error
set -e
cleanup() {
    echo "Cleaning up..."
    # Remove partially created files on failure
    if [ $? -ne 0 ]; then
        rm -f /etc/udev/rules.d/99-vending-console.rules
        rm -f /etc/cron.d/vending-console
    fi
}

trap cleanup EXIT

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo "Starting Vending Console setup..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

# Check for existing installation
if [ -f "/etc/cron.d/vending-console" ]; then
    read -p "Existing cron installation found. Do you want to remove it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -f /etc/cron.d/vending-console
        rm -f /etc/udev/rules.d/99-vending-console.rules
        rm -rf "$LOG_DIR"
    else
        echo "Installation aborted"
        exit 1
    fi
fi

# Get the actual user who ran sudo
ACTUAL_USER=$SUDO_USER
if [ -z "$ACTUAL_USER" ]; then
    echo -e "${RED}Could not determine the actual user${NC}"
    exit 1
fi

# Get the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Install system dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv

# Create udev rule for USB serial device
echo "Setting up udev rules..."
cat > /etc/udev/rules.d/99-vending-console.rules << EOF
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="ttyVending", MODE="0666"
SUBSYSTEM=="tty", ATTRS{idVendor}=="067b", ATTRS{idProduct}=="2303", SYMLINK+="ttyVending", MODE="0666"
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", SYMLINK+="ttyVending", MODE="0666"
EOF

# Reload udev rules
udevadm control --reload-rules
udevadm trigger

# Install Python dependencies
echo "Installing Python packages..."
cd "$PROJECT_DIR"

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv "$PROJECT_DIR/.venv"
source "$PROJECT_DIR/.venv/bin/activate"

# Get actual user's home directory
USER_HOME=$(getent passwd "$ACTUAL_USER" | cut -d: -f6)

# Try to use UV if available, otherwise use pip directly
if [ -f "$USER_HOME/.local/bin/uv" ] || [ -f "/usr/local/bin/uv" ]; then
    echo "Using UV package manager..."
    if [ -f "$USER_HOME/.local/bin/uv" ]; then
        UV_CMD="$USER_HOME/.local/bin/uv"
    else
        UV_CMD="/usr/local/bin/uv"
    fi
    sudo -E -u "$ACTUAL_USER" bash -c "export UV_CACHE_DIR=$USER_HOME/.cache/uv && export HOME=$USER_HOME && PATH=$PATH:$USER_HOME/.local/bin $UV_CMD sync"
else
    echo "Installing with pip..."
    pip install paho-mqtt pyserial pyserial-asyncio tinydb
fi

# Deactivate virtual environment
deactivate

# Create log directory
echo "Creating log directory..."
LOG_DIR="/var/log/vending-console"
mkdir -p $LOG_DIR
chown $ACTUAL_USER:$ACTUAL_USER $LOG_DIR

# Create startup script
echo "Creating startup script..."
STARTUP_SCRIPT="$PROJECT_DIR/scripts/start_vending.sh"

cat > "$STARTUP_SCRIPT" << EOF
#!/bin/bash

# Redirect output to log files
exec >> "$LOG_DIR/vending-console.log" 2>> "$LOG_DIR/vending-console.error.log"

echo "Starting Vending Console at \$(date)"
cd "$PROJECT_DIR"
"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/app.py"
EOF

chmod +x "$STARTUP_SCRIPT"

# Create cron job entry
echo "Setting up cron job to run on reboot..."
cat > /etc/cron.d/vending-console << EOF
# Vending Console application - runs at system startup
@reboot $ACTUAL_USER $STARTUP_SCRIPT
EOF

chmod 644 /etc/cron.d/vending-console

echo "Setting up log rotation..."
cat > /etc/logrotate.d/vending-console << EOF
$LOG_DIR/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 640 $ACTUAL_USER $ACTUAL_USER
}
EOF

# Make scripts executable
chmod +x "$PROJECT_DIR/scripts/install.sh"
chmod +x "$PROJECT_DIR/scripts/uninstall.sh"

# Copy initial database file
cp "$(dirname "$0")/db.json" "$PROJECT_DIR/db.json"

# Update app.py to use ttyVending instead of ttyUSB0
echo "Updating configuration to use ttyVending..."
if [ -f "$PROJECT_DIR/app.py" ]; then
    sed -i 's|"/dev/ttyUSB0"|"/dev/ttyVending"|g' "$PROJECT_DIR/app.py"
fi

echo -e "${GREEN}Setup completed successfully!${NC}"
echo "A cron job has been set up to run the application at system startup."
echo "The application will run with the following command:"
echo "  $STARTUP_SCRIPT"
echo "Log files will be stored in: $LOG_DIR"
echo "To test the script without rebooting, run:"
echo "  $STARTUP_SCRIPT"
echo "You may need to reboot the system for the udev rules to take effect."
