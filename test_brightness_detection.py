#!/usr/bin/env python3

import os
from pathlib import Path
import json
import sys

try:
    import cv2
    import numpy as np
except Exception as e:
    print(f"Skipping tests: OpenCV/Numpy unavailable: {e}")
    sys.exit(1)

from config.config import ConfigManager
from laser_monitor import LaserMonitor


def test_brightness_detection():
    """Test brightness threshold detection on sample images"""
    
    # Load brightness threshold config
    cm = ConfigManager()
    cfg_path = Path("tests/test_brightness.config.py").resolve()
    config = cm.load_config(str(cfg_path))

    # Force settings for testing
    config.detection.mode = "bbox"  # Ensure bbox mode is set
    config.detection.indicator_mode = False  # Disable color-based indicator mode
    config.detection.use_brightness_threshold = True  # Enable brightness threshold mode
    config.display.display_video = False
    config.output.save_detections = False
    config.output.save_screenshots = False
    config.logging.log_to_file = False
    config.logging.log_level = "INFO"
    config.alerts.email_alerts = False
    config.alerts.sms_alerts = False

    monitor = LaserMonitor(config)
    test_images = sorted(Path("tests").glob("test*.jpg"))
    
    if not test_images:
        print("No test images found in tests/")
        return

    # Create output directory for test result images
    output_dir = Path("tests/output")
    output_dir.mkdir(exist_ok=True)

    print("Testing brightness threshold detection mode:")
    print(f"- Brightness threshold ratio: {config.detection.brightness_threshold_ratio}")
    print(f"- Brightness active ratio: {config.detection.brightness_active_ratio}")
    print()

    for img_path in test_images:
        print(f"=== Testing {img_path.name} ===")
        
        frame = cv2.imread(str(img_path))
        if frame is None:
            print(f"❌ Failed to read test image: {img_path}")
            continue

        h, w = frame.shape[:2]
        detections = monitor.detect_objects(frame)

        # Save annotated result image
        annotated_frame = monitor.draw_detection_overlays(frame, detections)
        result_path = output_dir / f"{img_path.stem}_brightness_result.jpg"
        cv2.imwrite(str(result_path), annotated_frame)
        print(f"📸 Saved result: {result_path}")

        # Show detection results
        for idx, d in enumerate(detections):
            dct = d.to_dict()
            machine_id = f"machine_{idx}"
            
            print(f"  {machine_id}:")
            print(f"    Class: {dct['class_name']}")
            print(f"    Status: {dct['laser_status']}")
            print(f"    Confidence: {dct['confidence']:.3f}")
            
            if 'extras' in dct:
                extras = dct['extras']
                if 'top_brightness' in extras:
                    print(f"    Top brightness: {extras['top_brightness']:.1f} (ratio: {extras.get('top_bright_ratio', 0):.3f})")
                if 'mid_brightness' in extras:
                    print(f"    Mid brightness: {extras['mid_brightness']:.1f} (ratio: {extras.get('mid_bright_ratio', 0):.3f})")
                if 'bottom_brightness' in extras:
                    print(f"    Bottom brightness: {extras['bottom_brightness']:.1f}")
                if 'top_threshold' in extras:
                    print(f"    Thresholds: Top={extras['top_threshold']:.1f}, Mid={extras.get('mid_threshold', 0):.1f}")
                if 'decision_path' in extras:
                    print(f"    Decision: {extras['decision_path']}")
        print()


def compare_modes():
    """Compare brightness threshold vs color-based detection"""
    
    print("=== Comparison: Color vs Brightness Detection ===")
    
    # Test with color-based detection
    cm = ConfigManager()
    color_config = cm.load_config("tests/test.config.py")
    color_config.detection.mode = "bbox"
    color_config.display.display_video = False
    color_config.logging.log_level = "ERROR"
    color_config.alerts.email_alerts = False
    color_config.alerts.sms_alerts = False
    color_monitor = LaserMonitor(color_config)
    
    # Test with brightness-based detection  
    brightness_config = cm.load_config("tests/test_brightness.config.py")
    brightness_config.detection.mode = "bbox"
    brightness_config.detection.indicator_mode = False
    brightness_config.detection.use_brightness_threshold = True
    brightness_config.display.display_video = False
    brightness_config.logging.log_level = "ERROR"
    brightness_config.alerts.email_alerts = False
    brightness_config.alerts.sms_alerts = False
    brightness_monitor = LaserMonitor(brightness_config)
    
    test_images = sorted(Path("tests").glob("test*.jpg"))[:3]  # Test first 3 images
    
    for img_path in test_images:
        print(f"\n--- {img_path.name} ---")
        
        frame = cv2.imread(str(img_path))
        if frame is None:
            continue
            
        # Color-based detection
        color_detections = color_monitor.detect_objects(frame)
        print("Color-based:")
        for idx, d in enumerate(color_detections):
            dct = d.to_dict()
            print(f"  machine_{idx}: {dct['class_name']} ({dct['confidence']:.3f})")
            
        # Brightness-based detection
        brightness_detections = brightness_monitor.detect_objects(frame)
        print("Brightness-based:")
        for idx, d in enumerate(brightness_detections):
            dct = d.to_dict()
            extras = dct.get('extras', {})
            top_ratio = extras.get('top_bright_ratio', 0)
            mid_ratio = extras.get('mid_bright_ratio', 0)
            print(f"  machine_{idx}: {dct['class_name']} ({dct['confidence']:.3f}, top={top_ratio:.3f}, mid={mid_ratio:.3f})")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        compare_modes()
    else:
        test_brightness_detection()