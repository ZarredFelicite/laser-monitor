#!/usr/bin/env bash

# Laser Monitor startup script for systemd
# This script uses system Python directly and starts the monitor

set -euo pipefail

# Change to project directory
cd /home/hilton/laser-monitor

# Set up environment
export PATH="/usr/bin:/bin:/usr/local/bin:/home/hilton/.local/bin"
#export PYTHONPATH="/home/hilton/laser-monitor"
export LIBCAMERA_LOG_LEVELS="*:ERROR"

# Log startup
echo "$(date): Starting Laser Monitor with system Python..."
echo "$(date): Working directory: $(pwd)"
echo "$(date): User: $(whoami)"
echo "$(date): PATH: $PATH"

# Use system python directly (uv run has numpy issues)
echo "$(date): Using system python directly..."
echo "$(date): Python version: $(python3 --version 2>/dev/null || echo 'python3 not found')"

# Check if python3 is available
if ! command -v python3 >/dev/null 2>&1; then
    echo "$(date): ERROR: python3 not found in PATH"
    exit 1
fi

echo "$(date): Starting laser monitor..."
exec python3 cli.py monitor --config config/test.config.py --detection-mode bbox -v --continuous

