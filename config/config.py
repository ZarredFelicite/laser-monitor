#!/usr/bin/env python3
"""
Laser Monitor Configuration

Unified configuration system with loading, validation, and management capabilities.
Supports Python, JSON, and YAML config files with visual prompt integration.
"""

import importlib.util
import sys
import logging
import copy
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, field


@dataclass
class CameraConfig:
    camera_id: int = 1
    camera_type: Optional[str] = "pi"  # "usb", "pi", or None for auto-detect
    resolution_width: int = 1920
    resolution_height: int = 1080
    fps: int = 30
    auto_exposure: bool = True
    exposure_value: int = -1
    brightness: float = 0.5
    contrast: float = 1.0
    saturation: float = 1.0


@dataclass
class DetectionConfig:
    confidence_threshold: float = 0.2
    nms_threshold: float = 0.5
    max_detections: int = 100
    mode: str = "text"  # "text", "visual", "bbox"

    # Text mode
    laser_keywords: List[str] = field(default_factory=lambda: [
        "light", "indicator", "led", "laser", "red light", "green light",
        "warning light", "status light", "power light", "ready light"
    ])

    # Visual mode
    visual_prompt_path: Optional[str] = None
    refer_image: Optional[str] = None
    visual_prompt_bbox: Optional[List[float]] = None
    visual_prompts: Optional[List[List[float]]] = None

    # Bbox mode behavior
    bbox_force_detection: bool = True  # If True, always produce a detection per bbox even if heuristics fail

    # Indicator light composite mode (splits bbox into subregions for red/orange detection)
    indicator_mode: bool = True  # Enable specialized top-third red / middle-third orange logic
    red_activation_ratio: float = 0.5  # Minimum fraction of top-third pixels matching red to activate
    orange_activation_ratio: float = 0.53  # Minimum fraction of middle-third pixels matching orange to activate
    # Hue range configurables (HSV H channel 0-179) for fine tuning
    red_hue_low_max: int = 10     # Inclusive upper bound for low-end red wrap
    red_hue_high_min: int = 170   # Inclusive lower bound for high-end red wrap
    orange_hue_min: int = 8       # Inclusive lower bound for orange
    orange_hue_max: int = 30      # Inclusive upper bound for orange

    indicator_min_saturation: int = 90  # Minimum saturation for a pixel to be considered colored
    indicator_min_value: int = 90  # Minimum value (brightness) for a pixel to be considered
    indicator_blur_ksize: int = 3  # Median blur kernel size to denoise before analysis

    # Brightness threshold mode (alternative to color-based detection)
    use_brightness_threshold: bool = True  # Enable brightness-based detection instead of color analysis
    brightness_threshold_ratios: List[List[float]] = field(default_factory=lambda: [[1.7, 2.2]])  # Per-ROI, per-section ratios [[top_ratio, mid_ratio], ...] for each visual_prompt (optimized: 92.9% accuracy)


@dataclass
class AlertConfig:
    enabled: bool = False
    error_threshold: float = 0.7
    warning_threshold: float = 0.5
    sound_alerts: bool = False
    sound_file: Optional[str] = None

    # Email alert settings
    email_alerts: bool = True
    # Email recipients moved to .env (LASER_MONITOR_EMAIL_RECIPIENTS)
    email_recipients: List[str] = field(default_factory=list)
    email_smtp_server: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_username: str = ""  # Set via environment variable
    email_password: str = ""  # Set via environment variable
    email_from: str = "laser.monitor@hiltonmfg.com.au"
    email_subject: str = "Laser Monitor Alert - Machine Inactive"

    # SMS alert settings
    sms_alerts: bool = True
    # SMS recipients moved to .env (LASER_MONITOR_SMS_RECIPIENTS); numbers must be E.164 format
    sms_recipients: List[str] = field(default_factory=list)
    twilio_account_sid: str = ""  # Set via environment variable
    twilio_auth_token: str = ""  # Set via environment variable
    twilio_from_number: str = ""  # Your Twilio phone number

    # Machine-specific alert settings
    alert_machines: List[str] = field(default_factory=lambda: ['machine_0'])  # Only alert for machine_0

    webhook_url: Optional[str] = None
    alert_cooldown: int = 600  # 10 minutes cooldown between alerts


@dataclass
class LoggingConfig:
    log_level: str = "INFO"
    log_to_file: bool = True
    log_file: str = "laser_monitor.log"
    max_log_size: int = 10485760
    backup_count: int = 5
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass
class OutputConfig:
    output_dir: str = "output"
    save_detections: bool = True
    save_screenshots: bool = True
    save_video: bool = False
    video_codec: str = "mp4v"
    video_fps: int = 10
    detection_history_limit: int = 1000
    upload_images: bool = True
    upload_url: str = "https://temp.sh/upload"
    # Cleanup settings
    max_detection_images: int = 20
    max_detection_logs: int = 20
    enable_auto_cleanup: bool = True


@dataclass
class DisplayConfig:
    # Display settings
    display_video: bool = True
    show_fps: bool = True
    # Annotation settings for saved images
    bbox_thickness: int = 2
    font_scale: float = 0.6


@dataclass
class PerformanceConfig:
    gpu_acceleration: bool = True
    model_precision: str = "fp16"


@dataclass
class Zone:
    name: str
    bbox: List[Union[int, float]]
    enabled: bool = True
    alert_on_detection: bool = True


@dataclass
class MonitoringConfig:
    enabled_zones: List[Zone] = field(default_factory=list)
    ignore_zones: List[Zone] = field(default_factory=list)

    # Continuous monitoring settings
    monitoring_interval_seconds: int = 120  # 2 minutes
    inactive_alert_threshold_minutes: int = 15  # Alert after 15 minutes inactive


@dataclass
class LaserMonitorConfig:
    model_path: str = "pretrain/yoloe-11s-seg.pt"
    camera: CameraConfig = field(default_factory=CameraConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for backward compatibility"""
        def convert_dataclass(obj):
            if hasattr(obj, '__dataclass_fields__'):
                result = {}
                for field_name, field_def in obj.__dataclass_fields__.items():
                    value = getattr(obj, field_name)
                    if isinstance(value, list):
                        result[field_name] = [convert_dataclass(item) if hasattr(item, '__dataclass_fields__') else item for item in value]
                    elif hasattr(value, '__dataclass_fields__'):
                        result[field_name] = convert_dataclass(value)
                    else:
                        result[field_name] = value
                return result
            return obj

        return convert_dataclass(self)


# Default configuration instance
default_config = LaserMonitorConfig()


def load_visual_prompts(visual_config_path: str) -> Dict[str, Any]:
    """Load visual prompts from a Python config file"""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("visual_config", visual_config_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load visual config from {visual_config_path}")

    visual_module = importlib.util.module_from_spec(spec)
    sys.modules["visual_config"] = visual_module
    spec.loader.exec_module(visual_module)

    return {
        'refer_image': visual_module.refer_image,
        'visual_prompts': visual_module.visual_prompts,
        'image_dimensions': getattr(visual_module, 'image_dimensions', None)
    }


def create_config_with_visual_prompts(base_config: LaserMonitorConfig, visual_config_path: str) -> LaserMonitorConfig:
    """Create a config with visual prompts loaded from a Python file.

    This function will deepcopy the provided base_config before modifying it so the
    original object isn't mutated (avoids surprising reuse of default_config).
    It also tolerates visual configs that may only define a single visual_prompts
    entry or omit image_dimensions.
    """
    visual_data = load_visual_prompts(visual_config_path)

    # Work on a copy so callers' default_config isn't mutated
    config = copy.deepcopy(base_config)

    # Update detection config
    config.detection.mode = "visual"
    config.detection.refer_image = visual_data.get('refer_image')

    visual_prompts = visual_data.get('visual_prompts') or []

    if len(visual_prompts) == 1:
        # Store both single bbox and list form for downstream compatibility
        config.detection.visual_prompt_bbox = visual_prompts[0]
        config.detection.visual_prompts = visual_prompts
    elif len(visual_prompts) > 1:
        config.detection.visual_prompts = visual_prompts

    return config


class ConfigManager:
    """Simple configuration manager for Python configs only"""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else None
        self.config = LaserMonitorConfig()
        self.logger = logging.getLogger(__name__)

    def load_config(self, config_path: Optional[str] = None) -> LaserMonitorConfig:
        """Load configuration from Python file, auto-detecting visual prompt configs"""
        if config_path:
            self.config_path = Path(config_path)
        elif self.config_path is None:
            # Auto-detect visual prompt config if it exists
            visual_config = self._find_visual_prompt_config()
            if visual_config:
                self.config_path = visual_config
                self.logger.info(f"Auto-detected visual prompt config: {visual_config}")
            else:
                # No config specified and none auto-detected, use built-in defaults
                self.logger.info("No config file specified, using built-in defaults")
                return self.config

        if not self.config_path.exists():
            self.logger.warning(f"Config file not found: {self.config_path}, using built-in defaults")
            return self.config

        try:
            self.config = self._load_python_config(self.config_path)
            self.logger.info(f"Configuration loaded from {self.config_path}")

        except Exception as e:
            self.logger.error(f"Failed to load config: {e}, using built-in defaults")

        return self.config

    def _load_python_config(self, config_path: Path) -> LaserMonitorConfig:
        """Load configuration from a Python module"""
        spec = importlib.util.spec_from_file_location("user_config", config_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load config from {config_path}")

        config_module = importlib.util.module_from_spec(spec)
        sys.modules["user_config"] = config_module
        spec.loader.exec_module(config_module)

        # Check if it's a visual prompt config that needs to be merged
        if hasattr(config_module, 'visual_prompts') and hasattr(config_module, 'refer_image'):
            return create_config_with_visual_prompts(default_config, str(config_path))

        # Check if it has a config object
        if hasattr(config_module, 'config'):
            return config_module.config

        # Try to construct config from module attributes
        config = LaserMonitorConfig()

        # Update config with module attributes
        for attr_name in dir(config_module):
            if not attr_name.startswith('_'):
                attr_value = getattr(config_module, attr_name)
                if hasattr(config, attr_name):
                    setattr(config, attr_name, attr_value)

        return config

    def _find_visual_prompt_config(self) -> Optional[Path]:
        """Find automatically generated visual prompt config files"""
        # Look for common patterns of generated visual prompt configs
        search_patterns = [
            "*.config.py",  # Generated by visual_prompt_selector.py
            "*_visual_prompt.py",
            "test*.config.py"  # Common test image configs
        ]

        for pattern in search_patterns:
            for config_file in Path(".").glob(pattern):
                if config_file.is_file():
                    try:
                        # Quick check if it's a visual prompt config
                        content = config_file.read_text()
                        if 'visual_prompts' in content and 'refer_image' in content:
                            return config_file
                    except Exception:
                        continue

        return None

    def save_config(self, config_path: Optional[str] = None) -> bool:
        """Save configuration to Python file"""
        if config_path:
            self.config_path = Path(config_path)

        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_python_config()
            self.logger.info(f"Configuration saved to {self.config_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")
            return False

    def _save_python_config(self):
        """Save configuration as Python module"""
        config_content = f'''#!/usr/bin/env python3
"""
Laser Monitor Configuration
Generated automatically
"""

from .config import LaserMonitorConfig, CameraConfig, DetectionConfig, AlertConfig
from .config import LoggingConfig, OutputConfig, DisplayConfig, PerformanceConfig
from .config import MonitoringConfig, Zone

config = {repr(self.config)}
'''
        with open(self.config_path, 'w') as f:
            f.write(config_content)

    def validate_config(self) -> List[str]:
        """Validate configuration and return list of errors"""
        errors = []

        # Validate camera settings
        if self.config.camera.camera_id < 0:
            errors.append("Camera ID must be non-negative")

        if self.config.camera.resolution_width <= 0 or self.config.camera.resolution_height <= 0:
            errors.append("Camera resolution must be positive")

        # Validate detection settings
        if not (0.0 <= self.config.detection.confidence_threshold <= 1.0):
            errors.append("Confidence threshold must be between 0.0 and 1.0")

        if not (0.0 <= self.config.detection.nms_threshold <= 1.0):
            errors.append("NMS threshold must be between 0.0 and 1.0")

        # Validate visual prompt path if specified
        if (self.config.detection.visual_prompt_path and
            not Path(self.config.detection.visual_prompt_path).exists()):
            errors.append(f"Visual prompt file not found: {self.config.detection.visual_prompt_path}")

        # Validate refer image if specified
        if (self.config.detection.refer_image and
            not Path(self.config.detection.refer_image).exists()):
            errors.append(f"Reference image not found: {self.config.detection.refer_image}")

        # Validate output directory
        try:
            Path(self.config.output.output_dir).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Cannot create output directory: {e}")

        # Validate zones
        for zone in self.config.monitoring.enabled_zones + self.config.monitoring.ignore_zones:
            if len(zone.bbox) != 4:
                errors.append(f"Zone '{zone.name}' bbox must have 4 coordinates")
            elif any(coord < 0 for coord in zone.bbox):
                errors.append(f"Zone '{zone.name}' bbox coordinates must be non-negative")

        return errors

    def get_config_summary(self) -> Dict[str, Any]:
        """Get a summary of the current configuration"""
        return {
            "model_path": self.config.model_path,
            "camera_id": self.config.camera.camera_id,
            "detection_mode": self.config.detection.mode,
            "confidence_threshold": self.config.detection.confidence_threshold,
            "output_dir": self.config.output.output_dir,
            "display_enabled": self.config.display.display_video,
            "alerts_enabled": self.config.alerts.enabled,
            "zones_count": len(self.config.monitoring.enabled_zones),
            "log_level": self.config.logging.log_level
        }

    def update_config(self, updates: Dict[str, Any]) -> bool:
        """Update configuration with new values"""
        try:
            for key, value in updates.items():
                if '.' in key:
                    # Handle nested keys like "camera.camera_id"
                    parts = key.split('.')
                    obj = self.config
                    for part in parts[:-1]:
                        obj = getattr(obj, part)
                    setattr(obj, parts[-1], value)
                else:
                    setattr(self.config, key, value)

            return True

        except Exception as e:
            self.logger.error(f"Failed to update config: {e}")
            return False

    def create_default_config(self) -> LaserMonitorConfig:
        """Create a default configuration with sample zones"""
        config = LaserMonitorConfig()

        # Add some default zones
        config.monitoring.enabled_zones = [
            Zone(
                name="control_panel",
                bbox=[0, 0, 200, 200],
                enabled=False,
                alert_on_detection=True
            ),
            Zone(
                name="laser_head",
                bbox=[400, 300, 640, 480],
                enabled=False,
                alert_on_detection=True
            )
        ]

        self.config = config
        return config

    def export_template(self, template_path: str) -> bool:
        """Export a Python configuration template"""
        template_config = self.create_default_config()

        try:
            template_path = Path(template_path)
            template_path.parent.mkdir(parents=True, exist_ok=True)

            # Save as Python template
            old_config = self.config
            old_path = self.config_path
            self.config = template_config
            self.config_path = template_path
            self._save_python_config()
            self.config = old_config
            self.config_path = old_path

            self.logger.info(f"Configuration template exported to {template_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to export template: {e}")
            return False


def main():
    """CLI for configuration management"""
    import argparse

    parser = argparse.ArgumentParser(description="Configuration Manager for Laser Monitor")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--create-template", help="Create configuration template")
    parser.add_argument("--validate", action="store_true", help="Validate configuration")
    parser.add_argument("--summary", action="store_true", help="Show configuration summary")

    args = parser.parse_args()

    manager = ConfigManager(args.config)

    if args.create_template:
        manager.create_default_config()
        if manager.save_config(args.create_template):
            print(f"Configuration template created: {args.create_template}")
        else:
            print("Failed to create template")

    elif args.validate:
        manager.load_config()
        errors = manager.validate_config()
        if errors:
            print("Configuration validation failed:")
            for error in errors:
                print(f"  - {error}")
        else:
            print("Configuration is valid")

    elif args.summary:
        manager.load_config()
        summary = manager.get_config_summary()
        print("Configuration Summary:")
        for key, value in summary.items():
            print(f"  {key}: {value}")

    else:
        print("Use --help for available options")


if __name__ == "__main__":
    main()
