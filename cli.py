#!/usr/bin/env python3

# Suppress common warnings
import warnings
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")
import os
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import argparse
import sys
import json
from pathlib import Path
from typing import Dict, Any, List
import logging

try:
    from config.config import ConfigManager
    from setup_yoloe import YoloESetup
    MODULES_AVAILABLE = True
except ImportError as e:
    print(f"Required modules not found: {e}")
    print("Please ensure all required files are in the same directory.")
    MODULES_AVAILABLE = False


class LaserMonitorCLI:
    def __init__(self):
        self.config_manager = ConfigManager()
        
    def setup_logging(self, level: str = "INFO"):
        logging.basicConfig(
            level=getattr(logging, level.upper()),
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        
    def cmd_setup(self, args):
        """Setup YoloE laser monitor"""
        setup = YoloESetup(args.output_dir)
        
        if args.interactive:
            success = setup.interactive_setup()
            return 0 if success else 1
        elif args.validate:
            success = setup.validate_installation()
            return 0 if success else 1
        else:
            setup.create_directories()
            if args.models:
                setup.download_models(args.models)
            else:
                setup.download_models(["s"])
            setup.test_camera(args.camera or 0)
            setup.test_model_loading()
            setup.create_default_config(args.camera or 0)
            print("Setup complete!")
            return 0
            
    def cmd_monitor(self, args):
        """Run single-shot laser detection"""
        try:
            from laser_monitor import LaserMonitor
        except ImportError as e:
            print(f"LaserMonitor not available: {e}")
            print("AI modes unavailable: install 'ultralytics' (and opencv-python) or run with --detection-mode bbox")
            return 1
            
        config = self.config_manager.load_config(args.config)
        
        # Apply command line overrides
        if args.model:
            config.model_path = args.model
        if args.camera is not None:
            config.camera.camera_id = args.camera
        if args.confidence is not None:
            config.detection.confidence_threshold = args.confidence
        if args.visual_prompt:
            config.detection.visual_prompt_path = args.visual_prompt
            config.detection.mode = "visual"
        if args.detection_mode:
            config.detection.mode = args.detection_mode
        if args.output_dir:
            config.output.output_dir = args.output_dir
        if getattr(args, 'verbose', False):
            config.logging.log_level = "DEBUG"
        
        # Validate configuration
        errors = self.config_manager.validate_config()
        if errors:
            print("Configuration validation failed:")
            for error in errors:
                print(f"  - {error}")
            return 1
            
        monitor = LaserMonitor(config)
        
        # Handle test email flag
        if getattr(args, 'test_email', False):
            success = monitor.test_email_alert()
            return 0 if success else 1
        
        # Handle test SMS flag
        if getattr(args, 'test_sms', False):
            success = monitor.test_sms_alert()
            return 0 if success else 1
        
        continuous = getattr(args, 'continuous', False)
        success = monitor.run(continuous=continuous)
        return 0 if success else 1
        
    def cmd_config(self, args):
        """Manage configuration"""
        if args.create:
            config = self.config_manager.create_default_config()
            if self.config_manager.save_config(args.create):
                print(f"Default configuration created: {args.create}")
                return 0
            else:
                print("Failed to create configuration")
                return 1
                
        elif args.validate:
            config = self.config_manager.load_config(args.validate)
            errors = self.config_manager.validate_config()
            if errors:
                print("Configuration validation failed:")
                for error in errors:
                    print(f"  - {error}")
                return 1
            else:
                print("Configuration is valid")
                return 0
                
        elif args.summary:
            config = self.config_manager.load_config(args.summary)
            summary = self.config_manager.get_config_summary()
            print("Configuration Summary:")
            for key, value in summary.items():
                print(f"  {key}: {value}")
            return 0
            
        elif args.template:
            if self.config_manager.export_template(args.template):
                print(f"Configuration template exported: {args.template}")
                return 0
            else:
                print("Failed to export template")
                return 1
                
        else:
            print("No configuration action specified. Use --help for options.")
            return 1

    def cmd_visual_prompt(self, args):
        """Create visual prompt configuration"""
        try:
            import subprocess
            import sys
            
            cmd = [sys.executable, "visual_prompt_selector.py", args.image]
            if args.output:
                cmd.extend(["-o", args.output])
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"Visual prompt configuration created successfully!")
                print(result.stdout)
                return 0
            else:
                print(f"Failed to create visual prompt configuration:")
                print(result.stderr)
                return 1
                
        except Exception as e:
            print(f"Error running visual prompt selector: {e}")
            return 1

    def _test_image_detection(self, args):
        """Test detection on a single image (supports bbox mode).

        This implementation uses LaserMonitor.detect_objects and LaserMonitor.save_frame
        to run detection and save annotated outputs. It accepts the same CLI overrides
        as the monitor command (model, confidence, visual_prompt, detection_mode, output_dir, verbose).
        """
        from pathlib import Path
        import cv2
        import json
        from datetime import datetime

        # Check if image exists
        if not getattr(args, 'image', None):
            print("Error: --image is required for image testing")
            return 1

        image_path = Path(args.image)
        if not image_path.exists():
            print(f"Error: Image file not found: {image_path}")
            return 1

        try:
            from laser_monitor import LaserMonitor
        except ImportError as e:
            print(f"LaserMonitor not available: {e}")
            print("AI modes unavailable: install 'ultralytics' (and opencv-python) or run with --detection-mode bbox")
            return 1

        # Load configuration
        config = self.config_manager.load_config(getattr(args, 'config', None))

        # Apply command line overrides
        if getattr(args, 'model', None):
            config.model_path = args.model
        if getattr(args, 'confidence', None) is not None:
            config.detection.confidence_threshold = args.confidence
        if getattr(args, 'visual_prompt', None):
            config.detection.visual_prompt_path = args.visual_prompt
            config.detection.mode = "visual"
        if getattr(args, 'detection_mode', None):
            config.detection.mode = args.detection_mode
        if getattr(args, 'output_dir', None):
            config.output.output_dir = args.output_dir
        if getattr(args, 'verbose', False):
            config.logging.log_level = "DEBUG"

        # Disable video display for image testing
        config.display.display_video = False

        print(f"Testing detection on image: {image_path}")
        print(f"Detection mode: {config.detection.mode}")
        print(f"Confidence threshold: {config.detection.confidence_threshold}")

        # Load and resize image
        image = cv2.imread(str(image_path))
        if image is None:
            print(f"Error: Could not load image: {image_path}")
            return 1

        # Resize to match config resolution
        target_size = (config.camera.resolution_width, config.camera.resolution_height)
        if image.shape[1] != target_size[0] or image.shape[0] != target_size[1]:
            image = cv2.resize(image, target_size)
            print(f"Image resized to: {target_size}")

        # Initialize monitor
        monitor = LaserMonitor(config)
        if getattr(args, 'verbose', False):
            monitor.logger.setLevel(logging.DEBUG)
            for h in monitor.logger.handlers:
                h.setLevel(logging.DEBUG)

        # Load model if needed (text/visual); load_model returns True for bbox
        if config.detection.mode in ["text", "visual"]:
            if not monitor.load_model():
                print("Failed to load model required for AI detection mode")
                return 1

        # Run detection on the image
        print("Running detection...")
        detections = monitor.detect_objects(image)

        # Print results (supports DetectionResult objects and dicts)
        print(f"\nDetection Results:")
        print(f"Number of detections: {len(detections)}")

        if detections:
            for i, det in enumerate(detections):
                print(f"  Detection {i+1}:")
                if isinstance(det, dict):
                    cls = det.get('class', det.get('class_name', 'unknown'))
                    conf = det.get('confidence', 0.0)
                    bbox = det.get('bbox', [])
                else:
                    cls = getattr(det, 'class_name', 'unknown')
                    conf = getattr(det, 'confidence', 0.0)
                    bbox = getattr(det, 'bbox', [])
                print(f"    Class: {cls}")
                print(f"    Confidence: {conf:.3f}")
                print(f"    Bbox: {bbox}")
        else:
            print("  No detections found")

        # Ensure output directory exists
        output_dir = Path(config.output.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save annotated image using monitor.save_frame
        try:
            annotated_path, image_url = monitor.save_frame(image, detections)
            print(f"\nAnnotated image saved: {annotated_path}")
            if image_url:
                print(f"Image URL: {image_url}")
        except Exception as e:
            print(f"Failed to save annotated image: {e}")

        # Save detection results as JSON
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_json_path = output_dir / f"test_results_{timestamp}.json"
        try:
            # Convert detections to serializable form
            serial_dets = []
            for det in detections:
                if isinstance(det, dict):
                    serial_dets.append(det)
                else:
                    serial_dets.append(det.to_dict())

            results = {
                "image_path": str(image_path),
                "timestamp": timestamp,
                "config": {
                    "model": config.model_path,
                    "mode": config.detection.mode,
                    "confidence_threshold": config.detection.confidence_threshold
                },
                "detections": serial_dets
            }

            with open(output_json_path, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"Detection results saved: {output_json_path}")
        except Exception as e:
            print(f"Failed to save detection results: {e}")

        # Exit status
        if detections:
            print(f"\n✓ Test completed successfully - {len(detections)} detection(s) found")
            return 0
        else:
            print(f"\n⚠ Test completed - no detections found (try lowering confidence threshold)")
            return 0
            
    def cmd_test(self, args):
        """Test system components"""
        if args.image:
            return self._test_image_detection(args)
        elif args.camera is not None:
            from camera_manager import CameraManager
            manager = CameraManager()
            
            camera_type = getattr(args, 'camera_type', None)
            print(f"Testing camera {args.camera} (type: {camera_type or 'auto'})")
            
            if manager.open_camera(args.camera, camera_type):
                info = manager.get_camera_info()
                print(f"Camera opened successfully: {info}")
                
                # Test frame capture
                ret, frame = manager.read_frame()
                if ret:
                    print(f"Frame captured: {frame.shape}")
                    
                    # Save test frame
                    import cv2
                    test_path = f"test_camera_{args.camera}_{info['type']}.jpg"
                    cv2.imwrite(test_path, frame)
                    print(f"Test frame saved as {test_path}")
                else:
                    print("Failed to capture frame")
                    
                manager.close_camera()
                return 0
            else:
                print("Failed to open camera")
                return 1
            
        elif args.model:
            setup = YoloESetup()
            success = setup.test_model_loading(args.model)
            return 0 if success else 1
            
        elif args.config:
            config_manager = ConfigManager(args.config)
            config = config_manager.load_config()
            errors = config_manager.validate_config()
            if errors:
                print("Configuration test failed:")
                for error in errors:
                    print(f"  - {error}")
                return 1
            else:
                print("Configuration test passed")
                return 0
                
        else:
            print("No test specified. Use --help for options.")
            return 1
            
    def cmd_info(self, args):
        """Show system information"""
        print("Laser Monitor System Information")
        print("=" * 40)
        
        # Check dependencies
        print("\nDependencies:")
        try:
            import cv2
            print(f"  OpenCV: {cv2.__version__}")
        except ImportError:
            print("  OpenCV: NOT INSTALLED")
            
        try:
            import numpy as np
            print(f"  NumPy: {np.__version__}")
        except ImportError:
            print("  NumPy: NOT INSTALLED")
            
        try:
            from ultralytics import YOLOE
            print("  YoloE: Available")
        except ImportError:
            print("  YoloE: NOT INSTALLED (text/visual modes disabled; bbox mode still works)")
            
        try:
            from huggingface_hub import hf_hub_download
            print("  Hugging Face Hub: Available")
        except ImportError:
            print("  Hugging Face Hub: NOT INSTALLED")
            
        # Check models
        print("\nAvailable Models:")
        pretrain_dir = Path("pretrain")
        if pretrain_dir.exists():
            models = list(pretrain_dir.glob("*.pt"))
            if models:
                for model in models:
                    size = model.stat().st_size / (1024 * 1024)  # MB
                    print(f"  {model.name}: {size:.1f} MB")
            else:
                print("  No models found")
        else:
            print("  Pretrain directory not found")
            
        # Check configurations
        print("\nConfigurations:")
        config_files = list(Path(".").glob("*.py"))
        config_files = [f for f in config_files if "config" in f.name.lower()]
        if config_files:
            for config_file in config_files:
                print(f"  {config_file}")
        else:
            print("  No configuration files found")
            
        # Check cameras
        print("\nAvailable Cameras:")
        try:
            from camera_manager import CameraManager
            manager = CameraManager()
            cameras = manager.detect_cameras()
            if cameras:
                for cam in cameras:
                    print(f"  {cam['name']} (ID: {cam['id']}, Type: {cam['type']})")
            else:
                print("  No cameras detected")
        except Exception as e:
            print(f"  Camera detection failed: {e}")
        
        # Check output directory
        print("\nOutput Directory:")
        output_dir = Path("output")
        if output_dir.exists():
            subdirs = [d for d in output_dir.iterdir() if d.is_dir()]
            print(f"  {output_dir}: {len(subdirs)} subdirectories")
            for subdir in subdirs:
                files = list(subdir.glob("*"))
                print(f"    {subdir.name}: {len(files)} files")
        else:
            print("  Output directory not found")
            
        return 0


def create_parser():
    parser = argparse.ArgumentParser(
        description="Laser Cutter Monitor CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initial setup
  python cli.py setup --interactive
  
  # Run with built-in defaults
  python cli.py monitor
  
  # Run detection with custom config
  python cli.py monitor --config my_config.py
  
  # Run with visual prompts
  python cli.py monitor --visual-prompt prompt.jpg
  
  # Test camera
  python cli.py test --camera 0
  
  # Show system info
  python cli.py info
        """
    )
    
    parser.add_argument("--log-level", default="INFO", 
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level")
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Setup YoloE laser monitor")
    setup_parser.add_argument("--interactive", action="store_true", 
                             help="Run interactive setup")
    setup_parser.add_argument("--validate", action="store_true",
                             help="Validate installation")
    setup_parser.add_argument("--models", nargs="+", choices=["s", "m", "l"],
                             help="Model sizes to download")
    setup_parser.add_argument("--camera", type=int, help="Camera ID to test")
    setup_parser.add_argument("--output-dir", default="output", help="Output directory")
    
    # Monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Start laser monitoring")
    monitor_parser.add_argument("--config", help="Configuration file")
    monitor_parser.add_argument("--model", help="Override model path")
    monitor_parser.add_argument("--camera", type=int, help="Override camera ID")
    monitor_parser.add_argument("--confidence", type=float, help="Override confidence threshold")
    monitor_parser.add_argument("--visual-prompt", help="Visual prompt image path")
    monitor_parser.add_argument("--detection-mode", choices=["text", "visual", "bbox"],
                               help="Detection mode")

    monitor_parser.add_argument("--output-dir", help="Override output directory")
    monitor_parser.add_argument("--continuous", action="store_true", help="Enable continuous monitoring with 2-minute intervals")
    monitor_parser.add_argument("--test-email", action="store_true", help="Send a test email alert immediately and exit")
    monitor_parser.add_argument("--test-sms", action="store_true", help="Send a test SMS alert immediately and exit")
    monitor_parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging (includes visual prompt selection details)")
    
    # Config command
    config_parser = subparsers.add_parser("config", help="Manage configuration")
    config_group = config_parser.add_mutually_exclusive_group(required=True)
    config_group.add_argument("--create", help="Create default configuration file")
    config_group.add_argument("--validate", help="Validate configuration file")
    config_group.add_argument("--summary", help="Show configuration summary")
    config_group.add_argument("--template", help="Export configuration template")
    
    # Visual prompt command
    visual_parser = subparsers.add_parser("visual-prompt", help="Create visual prompt configuration")
    visual_parser.add_argument("image", help="Input image path")
    visual_parser.add_argument("-o", "--output", help="Output config file path")
    
    # Test command
    test_parser = subparsers.add_parser("test", help="Test system components")
    # Keep camera and model mutually exclusive, but allow --config and --image to be used together
    test_group = test_parser.add_mutually_exclusive_group()
    test_group.add_argument("--camera", type=int, help="Test camera ID")
    test_group.add_argument("--model", help="Test model loading")
    # Allow config and image to be specified independently (so you can pass --image with --config)
    test_parser.add_argument("--config", help="Test configuration file")
    test_parser.add_argument("--image", help="Test detection on a single image (provide path to image)")
    test_parser.add_argument("--detection-mode", choices=["text", "visual", "bbox"], help="Override detection mode for image testing")
    test_parser.add_argument("--visual-prompt", help="Visual prompt image or config path for visual mode")
    test_parser.add_argument("--confidence", type=float, help="Override confidence threshold for testing")
    test_parser.add_argument("--output-dir", help="Override output directory for testing")
    test_parser.add_argument("--camera-type", choices=["usb", "pi"], help="Force camera type for testing")
    test_parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging for test run")
    
    # Info command
    info_parser = subparsers.add_parser("info", help="Show system information")
    
    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
        
    cli = LaserMonitorCLI()
    cli.setup_logging(args.log_level)
    
    # Route to appropriate command handler
    command_handlers = {
        "setup": cli.cmd_setup,
        "monitor": cli.cmd_monitor,
        "config": cli.cmd_config,
        "visual-prompt": cli.cmd_visual_prompt,
        "test": cli.cmd_test,
        "info": cli.cmd_info
    }
    
    handler = command_handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())