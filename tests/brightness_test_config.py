#!/usr/bin/env python3
"""
Test configuration for brightness threshold detection mode
"""

# Visual prompts configuration (same as test.config.py but with brightness mode enabled)
refer_image = "tests/test1.jpg"

# Define visual prompt regions (normalized bounding boxes 0-1)
visual_prompts = [
    [0.646875, 0.41388888888888886, 0.6598958333333333, 0.4703703703703704],  # machine_0 region
    [0.05572916666666667, 0.44814814814814813, 0.0625, 0.4759259259259259]    # machine_1 region  
]

# Image dimensions for reference
image_dimensions = (1920, 1080)

# Override detection config to use brightness threshold mode
from config.config import LaserMonitorConfig, DetectionConfig

config = LaserMonitorConfig()

# Enable brightness threshold mode instead of color-based detection
config.detection.mode = "bbox"
config.detection.visual_prompts = visual_prompts
config.detection.refer_image = refer_image
config.detection.indicator_mode = False  # Disable color-based indicator mode
config.detection.use_brightness_threshold = True  # Enable brightness threshold mode

# Brightness threshold configuration - per-ROI, per-section ratios
config.detection.brightness_threshold_ratios = [
    [1.5, 1.5],  # machine_0: top=1.5x, mid=1.5x
    [1.5, 1.5]   # machine_1: top=1.5x, mid=1.5x
]

# Other settings
config.detection.confidence_threshold = 0.1
config.detection.bbox_force_detection = False