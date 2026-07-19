from config.config import ConfigManager, LaserMonitorConfig


def test_bbox_mode_can_anchor_to_first_frame_when_reference_is_missing(tmp_path):
    config = LaserMonitorConfig()
    config.detection.mode = "bbox"
    config.detection.refer_image = str(tmp_path / "missing.jpg")
    config.detection.visual_prompts = [[0.1, 0.1, 0.2, 0.2]]
    manager = ConfigManager()
    manager.config = config

    assert not any("Reference image not found" in error for error in manager.validate_config())


def test_robust_settings_reject_malformed_values():
    config = LaserMonitorConfig()
    config.detection.visual_prompts = [["bad", 0.1, 0.2, 0.3]]
    config.detection.brightness_threshold_ratios = [[1.7, float("nan")]]
    config.detection.capture_burst_interval_seconds = -1
    manager = ConfigManager()
    manager.config = config

    errors = manager.validate_config()

    assert any("coordinates must be finite numbers" in error for error in errors)
    assert any("positive finite numbers" in error for error in errors)
    assert any("interval must be finite and non-negative" in error for error in errors)

    config.detection.visual_prompts = 123
    config.detection.brightness_threshold_ratios = 456
    errors = manager.validate_config()
    assert "Visual prompts must be a list of bounding boxes" in errors
    assert "Brightness thresholds must be a list of pairs" in errors

    config.detection.visual_prompt_bbox = [0.5, 0.5, 0.4, 0.6]
    errors = manager.validate_config()
    assert "Visual prompt fallback must be normalized and ordered" in errors
