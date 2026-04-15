#!/usr/bin/env bash
# Launcher for Pi CM5 Monitor Widget
# Run with sudo so the OC button can write to /boot/firmware/config.txt

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$EUID" -ne 0 ]; then
    echo "Tip: run with 'sudo $0' to enable the overclock button."
fi

python3 "$SCRIPT_DIR/pi_widget.py"
