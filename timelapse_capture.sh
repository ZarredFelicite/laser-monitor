#!/usr/bin/env bash

# Timelapse photo capture script using rpicam-still
# Takes a photo every 30 minutes with timestamped filename

# Configuration
PHOTO_DIR="$HOME/photos/timelapse"
INTERVAL=1800  # 30 minutes in seconds

# Create photo directory if it doesn't exist
mkdir -p "$PHOTO_DIR"

# Check if rpicam-still is available
if ! command -v rpicam-still >/dev/null 2>&1; then
    echo "Error: rpicam-still not found. Please install libcamera-apps."
    exit 1
fi

echo "Starting timelapse capture - taking photos every 30 minutes"
echo "Photos will be saved to: $PHOTO_DIR"
echo "Press Ctrl+C to stop"

# Main capture loop
while true; do
    # Generate timestamp for filename
    timestamp=$(date +"%Y%m%d_%H%M%S")
    filename="photo_${timestamp}.jpg"
    filepath="$PHOTO_DIR/$filename"
    
    echo "$(date): Capturing $filename"
    
    # Take photo with rpicam-still
    if rpicam-still -o "$filepath" --immediate; then
        echo "$(date): Successfully saved $filename"
    else
        echo "$(date): Error capturing photo"
    fi
    
    # Wait for next interval
    sleep "$INTERVAL"
done