#!/usr/bin/env bash

# Laser Monitor Server startup script for systemd
# This script uses system Python directly and starts the web server

set -euo pipefail

# Change to project directory
cd /home/hilton/git-repo

# Set up environment
export PATH="/usr/bin:/bin:/usr/local/bin"
export PYTHONPATH="/home/hilton/git-repo"
export FLASK_ENV=production
export FLASK_DEBUG=false

# Log startup
echo "$(date): Starting Laser Monitor Server with system Python..."
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

echo "$(date): Starting web server..."
exec python3 server/app.py