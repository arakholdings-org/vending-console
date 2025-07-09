#!/usr/bin/env bash


# Exit on any error
set -e
cleanup() {
    echo "Cleaning up..."
    # Remove partially created files on failure
    if [ $? -ne 0 ]; then
        systemctl stop vending-console 2>/dev/null || true
        rm -f /etc/systemd/system/vending-console.service
        rm -f /etc/udev/rules.d/99-vending-console.rules
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
if [ -f "/etc/systemd/system/vending-console.service" ]; then
    read -p "Existing installation found. Do you want to remove it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        systemctl stop vending-console
        systemctl disable vending-console
        rm -f /etc/systemd/system/vending-console.service
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

# Install Python dependencies
echo "Installing Python packages..."
cd "$PROJECT_DIR"

# Get actual user's home directory
USER_HOME=$(getent passwd "$ACTUAL_USER" | cut -d: -f6)

# Source UV environment or use full path
if [ -f "$USER_HOME/.local/bin/uv" ]; then
    UV_CMD="$USER_HOME/.local/bin/uv"
elif [ -f "/usr/local/bin/uv" ]; then
    UV_CMD="/usr/local/bin/uv"
else
    echo -e "${RED}UV package manager not found. Please install it first.${NC}"
    exit 1
fi

# Execute UV with preserved PATH
sudo -E -u "$ACTUAL_USER" bash -c "export UV_CACHE_DIR=$USER_HOME/.cache/uv && export HOME=$USER_HOME && PATH=$PATH:$USER_HOME/.local/bin $UV_CMD sync"

# Create udev rule for USB serial device
echo "Setting up udev rules..."
cat > /etc/udev/rules.d/99-vending-console.rules << EOF
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="ttyVending", MODE="0666"
EOF

# Reload udev rules
udevadm control --reload-rules
udevadm trigger


# Create log directory
echo "Creating log directory..."
LOG_DIR="/var/log/vending-console"
mkdir -p $LOG_DIR
chown $ACTUAL_USER:$ACTUAL_USER $LOG_DIR

# Create systemd service
echo "Creating systemd service..."
cat > /etc/systemd/system/vending-console.service << EOF
[Unit]
Description=Vending Console Service
After=network.target

[Service]
Type=simple
User=$ACTUAL_USER
WorkingDirectory=$PROJECT_DIR
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$PROJECT_DIR
StandardOutput=append:$LOG_DIR/vending-console.log
StandardError=append:$LOG_DIR/vending-console.error.log
ExecStart=$PROJECT_DIR/.venv/bin/python $PROJECT_DIR/app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Set correct permissions
chmod 644 /etc/systemd/system/vending-console.service


# Add before systemd reload

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
# Reload systemd
systemctl daemon-reload

# Enable and start service
echo "Enabling and starting service..."
systemctl enable vending-console
systemctl start vending-console

# Make scripts executable
chmod +x "$PROJECT_DIR/scripts/install.sh"
chmod +x "$PROJECT_DIR/scripts/uninstall.sh"

echo -e "${GREEN}Setup completed successfully!${NC}"
echo "You can check the service status with: systemctl status vending-console"
echo "View logs with: journalctl -u vending-console -f"

echo -e "${GREEN}Setup completed successfully!${NC}"
echo "You can check the service status with: systemctl status vending-console"
echo "View logs with: journalctl -u vending-console -f"

echo -e "${GREEN}Setup completed successfully!${NC}"
echo "You can check the service status with: systemctl status vending-console"
echo "View logs with: journalctl -u vending-console -f"



