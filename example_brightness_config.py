#!/usr/bin/env python3
"""
Example configuration for brightness threshold detection mode

This configuration demonstrates how to use brightness-based detection
instead of color-based detection for laser indicator monitoring.
"""

from config.config import LaserMonitorConfig, DetectionConfig

# Create base configuration
config = LaserMonitorConfig()

# Camera settings
config.camera.camera_id = 1
config.camera.resolution_width = 1920
config.camera.resolution_height = 1080

# Detection settings - brightness threshold mode
config.detection.mode = "bbox"  # Use bbox mode for heuristic detection
config.detection.confidence_threshold = 0.2

# Define regions of interest (normalized coordinates 0-1)
config.detection.visual_prompts = [
    [0.646875, 0.41388888888888886, 0.6598958333333333, 0.4703703703703704],  # machine_0 region
    [0.05572916666666667, 0.44814814814814813, 0.0625, 0.4759259259259259]    # machine_1 region  
]

# Disable color-based indicator mode
config.detection.indicator_mode = False

# Enable brightness threshold detection
config.detection.use_brightness_threshold = True

# Brightness threshold configuration - per-ROI, per-section ratios
# Format: [[top_ratio, mid_ratio], ...] for each visual_prompt
config.detection.brightness_threshold_ratios = [
    [1.5, 1.5],  # machine_0: top=1.5x, mid=1.5x
    [1.5, 1.5]   # machine_1: top=1.5x, mid=1.5x
]

# Display settings
config.display.display_video = True
config.display.show_fps = True

# Output settings
config.output.save_detections = True
config.output.save_screenshots = True

# Logging
config.logging.log_level = "INFO"
config.logging.log_to_file = True