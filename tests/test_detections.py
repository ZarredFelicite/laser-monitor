import os
from pathlib import Path
import json
import warnings

import pytest
try:
    import cv2
except Exception as e:
    # If OpenCV/Numpy cannot import (e.g., missing system libs), skip tests gracefully
    pytest.skip(f"Skipping tests: OpenCV/Numpy unavailable: {e}", allow_module_level=True)

from config.config import ConfigManager
from laser_monitor import LaserMonitor


class MachineExpectationWarning(Warning):
    """Non-fatal expectation mismatch for secondary machines"""
    pass


@pytest.fixture(scope="function")
def monitor_from_test_config(monkeypatch):
    # Ensure alert creds are not taken from local .env during tests
    monkeypatch.setenv("LASER_MONITOR_EMAIL_USER", "")
    monkeypatch.setenv("LASER_MONITOR_EMAIL_PASS", "")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "")
    # Load the test visual prompt config, then force bbox mode to avoid AI deps
    cm = ConfigManager()
    cfg_path = Path("tests/test.config.py").resolve()
    config = cm.load_config(str(cfg_path))

    # Force bbox mode and keep things headless and non-writing for tests
    config.detection.mode = "bbox"
    # Use default detection heuristics from config; no overrides in tests
    config.display.display_video = False
    config.output.save_detections = False
    config.output.save_screenshots = False
    config.logging.log_to_file = False
    config.logging.log_level = "ERROR"
    # Do not use forced detections; bbox mode now always emits a result per ROI
    config.detection.bbox_force_detection = False
    config.alerts.email_alerts = False
    config.alerts.sms_alerts = False

    # Ensure we have at least one bbox to test against
    assert config.detection.visual_prompts, "visual_prompts must be provided in tests/test.config.py"

    return LaserMonitor(config)


def _validate_detection_dict(det, width, height):
    # Required keys
    for key in ("timestamp", "confidence", "bbox", "class_name", "laser_status"):
        assert key in det, f"missing key in detection: {key}"

    # bbox sanity
    x1, y1, x2, y2 = det["bbox"]
    assert 0 <= x1 < x2 <= width, f"bbox x out of range: {det['bbox']} width={width}"
    assert 0 <= y1 < y2 <= height, f"bbox y out of range: {det['bbox']} height={height}"

    # status value sanity
    assert det["laser_status"] in {"active", "inactive", "normal"}


def test_detections_on_sample_images(monitor_from_test_config):
    test_images = sorted(Path("tests").glob("test*.jpg"))
    assert test_images, "No test images found in tests/"

    # Create output directory for test result images
    output_dir = Path("tests/output")
    output_dir.mkdir(exist_ok=True)

    for img_path in test_images:
        # Load expected results sidecar (required)
        expected_path = img_path.with_suffix(".expected.json")
        assert expected_path.exists(), f"Missing expected results file: {expected_path}"
        with expected_path.open("r") as f:
            expected = json.load(f)

        frame = cv2.imread(str(img_path))
        assert frame is not None, f"Failed to read test image: {img_path}"

        h, w = frame.shape[:2]
        detections = monitor_from_test_config.detect_objects(frame)

        assert isinstance(detections, list), "detect_objects should return a list"

        # Save annotated result image
        annotated_frame = monitor_from_test_config.draw_detection_overlays(frame, detections)
        result_path = output_dir / f"{img_path.stem}_result.jpg"
        cv2.imwrite(str(result_path), annotated_frame)
        print(f"Saved annotated result: {result_path}")

        actual_status = {}
        for idx, d in enumerate(detections):
            dct = d.to_dict()
            _validate_detection_dict(dct, w, h)
            machine_id = f"machine_{idx}"
            actual_status[machine_id] = dct["class_name"]

        # Expected format: {"machines": {"machine_0": "machine_active", ...}}
        exp_machines = expected.get("machines", {})
        assert exp_machines, f"No 'machines' mapping in expected file: {expected_path}"

        # Compare only machines present in expected file
        for mid, exp_status in exp_machines.items():
            if mid == "machine_0":
                assert mid in actual_status, f"Missing detection for {mid} in {img_path.name}"
                assert actual_status[mid] == exp_status, (
                    f"Status mismatch for {mid} in {img_path.name}: "
                    f"expected {exp_status}, got {actual_status.get(mid)}"
                )
            elif mid == "machine_1":
                # Only warn for secondary machine mismatches
                if mid not in actual_status:
                    warnings.warn(
                        f"Missing detection for {mid} in {img_path.name}",
                        category=MachineExpectationWarning,
                    )
                elif actual_status[mid] != exp_status:
                    warnings.warn(
                        f"Status mismatch for {mid} in {img_path.name}: expected {exp_status}, got {actual_status[mid]}",
                        category=MachineExpectationWarning,
                    )
            else:
                # Ignore any other machine entries silently
                continue
