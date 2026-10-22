#!/usr/bin/env bash
# ==============================================================================
# Automatic Attendance System - Raspberry Pi 4 Automated Setup Script
# ==============================================================================
# Usage:
#   chmod +x tools/setup_rpi.sh
#   ./tools/setup_rpi.sh
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURRENT_USER="$(whoami)"

echo "=========================================================="
echo "   AutoAttendance System - Raspberry Pi 4 Setup Wizard    "
echo "=========================================================="
echo "Project Directory: $SCRIPT_DIR"
echo "Running User:      $CURRENT_USER"
echo "=========================================================="

# 1. Update and install OS dependencies
echo "[1/5] Installing Linux system packages & camera dependencies..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv git libgl1 libglib2.0-0 v4l-utils

# 2. Setup Python virtual environment
echo "[2/5] Creating Python virtual environment (venv)..."
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    python3 -m venv "$SCRIPT_DIR/venv"
fi

# 3. Upgrade pip and install requirements
echo "[3/5] Installing Python requirements..."
"$SCRIPT_DIR/venv/bin/pip" install --upgrade pip setuptools wheel
"$SCRIPT_DIR/venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

# 4. Configure .env file if missing
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "[INFO] Creating .env file from template..."
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    else
        touch "$SCRIPT_DIR/.env"
    fi
    echo "Remember to update SUPABASE_URL and SUPABASE_KEY in $SCRIPT_DIR/.env if needed."
fi

# 5. Configure Bus ID & systemd Auto-Start Service
BUS_ID="Bus01"
read -p "Enter Bus ID for this device [default: Bus01]: " INPUT_BUS
if [ -n "$INPUT_BUS" ]; then
    BUS_ID="$INPUT_BUS"
fi

SERVICE_FILE="/etc/systemd/system/bus-attendance.service"

echo "[4/5] Creating headless autostart service ($SERVICE_FILE)..."
sudo bash -c "cat <<EOF > $SERVICE_FILE
[Unit]
Description=Bus Attendance Camera Engine (Headless)
After=network-online.target time-sync.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/venv/bin/python3 -m fleet_system.device_app.main --headless --bus-id $BUS_ID
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF"

echo "[5/5] Enabling and starting bus-attendance service..."
sudo systemctl daemon-reload
sudo systemctl enable bus-attendance.service

read -p "Do you want to start the attendance engine now? (y/n) [default: y]: " START_NOW
START_NOW=${START_NOW:-y}
if [[ "$START_NOW" =~ ^[Yy]$ ]]; then
    sudo systemctl restart bus-attendance.service
    echo "Service started successfully!"
fi

echo "=========================================================="
echo " Setup Completed Successfully! "
echo "=========================================================="
echo "Useful Commands:"
echo " - View live camera logs:    journalctl -u bus-attendance -f"
echo " - Check service status:     sudo systemctl status bus-attendance"
echo " - Stop camera service:      sudo systemctl stop bus-attendance"
echo " - Restart camera service:   sudo systemctl restart bus-attendance"
echo "=========================================================="
