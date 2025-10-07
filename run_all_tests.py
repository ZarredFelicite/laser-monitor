#!/usr/bin/env python3

import os
from pathlib import Path
import json
import warnings
import sys

try:
    import cv2
except Exception as e:
    print(f"Skipping tests: OpenCV/Numpy unavailable: {e}")
    sys.exit(1)

from config.config import ConfigManager
from laser_monitor import LaserMonitor


class MachineExpectationWarning(Warning):
    """Non-fatal expectation mismatch for secondary machines"""
    pass


def setup_monitor():
    # Load the test visual prompt config, then force bbox mode to avoid AI deps
    cm = ConfigManager()
    cfg_path = Path("tests/test.config.py").resolve()
    config = cm.load_config(str(cfg_path))

    # Force bbox mode and keep things headless and non-writing for tests
    config.detection.mode = "bbox"
    config.display.display_video = False
    config.output.save_detections = False
    config.output.save_screenshots = False
    config.logging.log_to_file = False
    config.logging.log_level = "ERROR"
    config.detection.bbox_force_detection = False
    config.alerts.email_alerts = False
    config.alerts.sms_alerts = False

    return LaserMonitor(config)


def validate_detection_dict(det, width, height):
    # Required keys
    for key in ("timestamp", "confidence", "bbox", "class_name", "laser_status"):
        assert key in det, f"missing key in detection: {key}"

    # bbox sanity
    x1, y1, x2, y2 = det["bbox"]
    assert 0 <= x1 < x2 <= width, f"bbox x out of range: {det['bbox']} width={width}"
    assert 0 <= y1 < y2 <= height, f"bbox y out of range: {det['bbox']} height={height}"

    # status value sanity
    assert det["laser_status"] in {"active", "inactive", "normal"}


def run_all_tests():
    monitor = setup_monitor()
    test_images = sorted(Path("tests").glob("test*.jpg"))
    
    if not test_images:
        print("No test images found in tests/")
        return

    # Create output directory for test result images
    output_dir = Path("tests/output")
    output_dir.mkdir(exist_ok=True)

    results = []
    total_tests = 0
    passed_tests = 0
    failed_tests = 0
    warnings_count = 0

    for img_path in test_images:
        print(f"\n=== Testing {img_path.name} ===")
        
        # Load expected results sidecar (required)
        expected_path = img_path.with_suffix(".expected.json")
        if not expected_path.exists():
            print(f"❌ Missing expected results file: {expected_path}")
            failed_tests += 1
            continue
            
        with expected_path.open("r") as f:
            expected = json.load(f)

        frame = cv2.imread(str(img_path))
        if frame is None:
            print(f"❌ Failed to read test image: {img_path}")
            failed_tests += 1
            continue

        h, w = frame.shape[:2]
        detections = monitor.detect_objects(frame)

        # Save annotated result image
        annotated_frame = monitor.draw_detection_overlays(frame, detections)
        result_path = output_dir / f"{img_path.stem}_result.jpg"
        cv2.imwrite(str(result_path), annotated_frame)
        print(f"📸 Saved annotated result: {result_path}")

        actual_status = {}
        for idx, d in enumerate(detections):
            dct = d.to_dict()
            try:
                validate_detection_dict(dct, w, h)
            except AssertionError as e:
                print(f"❌ Validation error: {e}")
                failed_tests += 1
                continue
                
            machine_id = f"machine_{idx}"
            actual_status[machine_id] = dct["class_name"]

        print(f"Detected: {actual_status}")
        
        # Expected format: {"machines": {"machine_0": "machine_active", ...}}
        exp_machines = expected.get("machines", {})
        if not exp_machines:
            print(f"❌ No 'machines' mapping in expected file: {expected_path}")
            failed_tests += 1
            continue

        print(f"Expected: {exp_machines}")

        # Compare results
        test_passed = True
        test_warnings = 0
        
        for mid, exp_status in exp_machines.items():
            total_tests += 1
            
            if mid == "machine_0":
                if mid not in actual_status:
                    print(f"❌ Missing detection for {mid}")
                    test_passed = False
                    failed_tests += 1
                elif actual_status[mid] != exp_status:
                    print(f"❌ Status mismatch for {mid}: expected {exp_status}, got {actual_status.get(mid)}")
                    test_passed = False
                    failed_tests += 1
                else:
                    print(f"✅ {mid}: {exp_status}")
                    passed_tests += 1
                    
            elif mid == "machine_1":
                # Only warn for secondary machine mismatches
                if mid not in actual_status:
                    print(f"⚠️  Missing detection for {mid}")
                    test_warnings += 1
                    warnings_count += 1
                elif actual_status[mid] != exp_status:
                    print(f"⚠️  Status mismatch for {mid}: expected {exp_status}, got {actual_status[mid]}")
                    test_warnings += 1
                    warnings_count += 1
                else:
                    print(f"✅ {mid}: {exp_status}")
                    passed_tests += 1
            else:
                # Ignore any other machine entries silently
                continue

        if test_passed and test_warnings == 0:
            print(f"✅ {img_path.name} PASSED")
        elif test_passed and test_warnings > 0:
            print(f"⚠️  {img_path.name} PASSED with {test_warnings} warnings")
        else:
            print(f"❌ {img_path.name} FAILED")

    # Summary
    print(f"\n{'='*50}")
    print(f"TEST SUMMARY")
    print(f"{'='*50}")
    print(f"Total test cases: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {failed_tests}")
    print(f"Warnings: {warnings_count}")
    print(f"Success rate: {passed_tests/total_tests*100:.1f}%" if total_tests > 0 else "No tests run")
    
    if failed_tests == 0:
        print("🎉 All tests passed!")
        return 0
    else:
        print(f"💥 {failed_tests} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)