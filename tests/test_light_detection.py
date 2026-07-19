import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from config.config import ConfigManager
from laser_monitor import DetectionResult, LaserMonitor, MachineHistory
from light_detection import (
    AdaptiveLightClassifier,
    DriftLocalizer,
    TemporalStateTracker,
)


@pytest.fixture
def visual_config():
    return ConfigManager().load_config(str(Path("tests/test.config.py").resolve()))


def _translate_and_relight(image, dx, dy, gain=1.0, cool=False):
    transformed = image.astype(np.float32) * gain
    if cool:
        transformed[:, :, 0] *= 1.2
        transformed[:, :, 2] *= 0.8
    transformed = np.clip(transformed, 0, 255).astype(np.uint8)
    matrix = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(
        transformed,
        matrix,
        (image.shape[1], image.shape[0]),
        borderMode=cv2.BORDER_REFLECT,
    )


@pytest.mark.parametrize("image_name", ["test1", "test3", "test7", "test8"])
def test_tracking_and_classification_survive_drift_and_relighting(
    visual_config, image_name
):
    reference = cv2.imread("tests/test1.jpg")
    image = cv2.imread(f"tests/{image_name}.jpg")
    expected = json.loads(
        Path(f"tests/{image_name}.expected.json").read_text()
    )["machines"]
    transformed = _translate_and_relight(
        image, dx=15, dy=-10, gain=0.65, cool=True
    )

    localizer = DriftLocalizer(
        reference, visual_config.detection.visual_prompts
    )
    localization = localizer.locate(transformed)
    classifier = AdaptiveLightClassifier(
        visual_config.detection.brightness_threshold_ratios
    )
    observed = {
        f"machine_{index}": classifier.classify(
            transformed, box, index, valid
        ).class_name
        for index, (box, valid) in enumerate(
            zip(localization.boxes, localization.valid)
        )
    }

    assert localization.valid == [True, True]
    assert localization.shift == pytest.approx((15, -10), abs=2.5)
    assert observed == expected


def test_local_match_recovers_when_global_registration_is_ambiguous():
    reference = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.rectangle(reference, (45, 20), (75, 100), (180, 180, 180), 2)
    cv2.line(reference, (25, 60), (95, 60), (255, 255, 255), 2)
    localizer = DriftLocalizer(
        reference,
        [[40 / 160, 30 / 120, 80 / 160, 90 / 120]],
        min_global_response=2.0,
    )

    result = localizer.locate(reference.copy())

    assert result.source == "anchor"
    assert result.scores[0] >= localizer.min_local_score
    assert result.valid == [True]


def test_strong_amber_light_survives_daylight_depressed_ratio():
    frame = np.full((100, 100, 3), 100, dtype=np.uint8)
    box = (40, 20, 60, 80)
    frame[40:60, 40:60] = (0, 220, 255)
    classifier = AdaptiveLightClassifier([[1.7, 2.2]])

    observation = classifier.classify(frame, box, 0, localized=True)

    assert observation.extras["mid_ratio"] < 2.2
    assert observation.class_name == "machine_on_only"
    assert observation.known


def test_tracker_rejects_implausible_total_drift(visual_config):
    reference = cv2.imread("tests/test1.jpg")
    shifted = _translate_and_relight(reference, dx=100, dy=0)
    localizer = DriftLocalizer(
        reference,
        visual_config.detection.visual_prompts,
        max_total_shift=40,
        max_hold_frames=0,
    )

    result = localizer.locate(shifted)

    assert result.source == "anchor"
    assert result.valid == [False, False]


def test_unknown_history_does_not_mark_machine_inactive():
    history = MachineHistory(machine_id="machine_0")

    history.add_entry("unknown", "machine_unknown", 0.0)

    assert history.last_active_time is None
    assert history.last_inactive_time is None
    assert history.get_inactive_duration() is None


def test_burst_requires_majority_agreement(visual_config, tmp_path):
    visual_config.output.output_dir = str(tmp_path)
    visual_config.output.upload_images = False
    visual_config.logging.log_to_file = False
    visual_config.alerts.email_alerts = False
    visual_config.alerts.sms_alerts = False
    monitor = LaserMonitor(visual_config)

    def result(class_name, known=True):
        return DetectionResult(
            timestamp="now",
            confidence=0.9,
            bbox=[1, 2, 3, 4],
            class_name=class_name,
            laser_status="active" if class_name == "machine_active" else "inactive",
            zone_name="machine_0",
            extras={"vision_known": known},
        )

    aggregated = monitor._aggregate_detection_burst([
        [result("machine_active")],
        [result("machine_active")],
        [result("machine_off")],
    ])
    assert aggregated[0].class_name == "machine_active"
    assert aggregated[0].extras["burst_agreement"] == pytest.approx(2 / 3)

    unknown = monitor._aggregate_detection_burst([
        [result("machine_active")],
        [],
        [],
    ])
    assert unknown[0].class_name == "machine_unknown"
    assert not unknown[0].extras["vision_known"]

    all_missing = monitor._aggregate_detection_burst([[], [], []])
    assert len(all_missing) == len(visual_config.detection.visual_prompts)
    assert all(item.class_name == "machine_unknown" for item in all_missing)


def test_hot_reload_rejects_invalid_boxes_and_keeps_last_good(
    visual_config, tmp_path, monkeypatch
):
    visual_config.output.output_dir = str(tmp_path / "output")
    visual_config.output.upload_images = False
    visual_config.logging.log_to_file = False
    monitor = LaserMonitor(visual_config)
    original_prompts = [list(box) for box in visual_config.detection.visual_prompts]
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "web_ui.config.py"
    config_path.write_text(
        "refer_image = ''\nvisual_prompts = [[0.1, 0.1, 0.2, 0.2]]\n"
    )
    assert not monitor.reload_visual_prompts()

    modified = config_path.stat().st_mtime + 2
    config_path.write_text(
        "refer_image = ''\nvisual_prompts = [['bad', 0.1, 0.2, 0.3]]\n"
    )
    os.utime(config_path, (modified, modified))

    assert not monitor.reload_visual_prompts()
    assert monitor.config.detection.visual_prompts == original_prompts


def test_temporal_tracker_confirms_transitions_and_holds_unknown():
    tracker = TemporalStateTracker(confirmations=2, unknown_hold_cycles=2)

    assert tracker.update("machine_0", "machine_off", True)[0] == "machine_off"
    assert tracker.update("machine_0", "machine_active", True) == (
        "machine_off", True, "transition_pending"
    )
    assert tracker.update("machine_0", "machine_active", True) == (
        "machine_active", True, "transition_confirmed"
    )
    assert tracker.update("machine_0", "machine_unknown", False) == (
        "machine_active", True, "held_unknown"
    )
    assert tracker.update("machine_0", "machine_unknown", False)[0] == "machine_active"
    assert tracker.update("machine_0", "machine_unknown", False) == (
        "machine_unknown", False, "unknown"
    )
