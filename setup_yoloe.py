#!/usr/bin/env python3

import os
import sys
import json
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import argparse
import logging

# Optional AI dependencies (ultralytics, huggingface-hub) are imported lazily so that
# non-AI workflows (e.g. bbox mode) do not require heavy packages installed.
# Functions that need these packages will raise informative errors if missing.
try:
    # Lightweight optional check (do not fail entire script if missing)
    import importlib
    _ultralytics_spec = importlib.util.find_spec("ultralytics")
    _hf_spec = importlib.util.find_spec("huggingface_hub")
except Exception:
    _ultralytics_spec = None
    _hf_spec = None

# Placeholders for type hints / linters
if False:  # pragma: no cover
    from ultralytics import YOLOE  # type: ignore
    from huggingface_hub import hf_hub_download  # type: ignore


class YoloESetup:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.pretrain_dir = Path("pretrain")
        self.config_file = self.output_dir / "monitor_config.json"
        self.setup_logging()
        
    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
    def create_directories(self):
        self.logger.info("Creating necessary directories...")
        directories = [
            self.output_dir,
            self.output_dir / "detections",
            self.output_dir / "screenshots",
            self.pretrain_dir
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Created directory: {directory}")
            
    def download_models(self, model_sizes: List[str] = None):
        if model_sizes is None:
            model_sizes = ["s"]  # Start with small model
            
        self.logger.info("Downloading YoloE models from Ultralytics...")
        
        # Official Ultralytics YoloE model URLs
        model_mapping = {
            "s": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-11s-seg.pt",
            "m": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-11m-seg.pt", 
            "l": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-11l-seg.pt",
            "v8s": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-v8s-seg.pt",
            "v8m": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-v8m-seg.pt",
            "v8l": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-v8l-seg.pt"
        }
        
        for size in model_sizes:
            if size not in model_mapping:
                self.logger.warning(f"Unknown model size: {size}")
                continue
                
            model_url = model_mapping[size]
            model_file = model_url.split("/")[-1]
            model_path = self.pretrain_dir / model_file
            
            if model_path.exists():
                self.logger.info(f"Model {model_file} already exists, skipping download")
                continue
                
            try:
                self.logger.info(f"Downloading {model_file}...")
                import requests
                response = requests.get(model_url, stream=True)
                response.raise_for_status()
                
                with open(model_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        
                self.logger.info(f"Successfully downloaded {model_file}")
            except Exception as e:
                self.logger.error(f"Failed to download {model_file}: {e}")
                
    def test_camera(self, camera_id: int = 0) -> bool:
        self.logger.info(f"Testing camera {camera_id}...")
        
        try:
            cap = cv2.VideoCapture(camera_id)
            if not cap.isOpened():
                self.logger.error(f"Cannot open camera {camera_id}")
                return False
                
            ret, frame = cap.read()
            if not ret:
                self.logger.error(f"Cannot read from camera {camera_id}")
                cap.release()
                return False
                
            height, width = frame.shape[:2]
            self.logger.info(f"Camera {camera_id} working - Resolution: {width}x{height}")
            
            # Save test frame
            test_frame_path = self.output_dir / "test_frame.jpg"
            cv2.imwrite(str(test_frame_path), frame)
            self.logger.info(f"Test frame saved to {test_frame_path}")
            
            cap.release()
            return True
            
        except Exception as e:
            self.logger.error(f"Camera test failed: {e}")
            return False
            
    def test_model_loading(self, model_path: str = None) -> bool:
        if model_path is None:
            # Try to find any available model
            model_files = list(self.pretrain_dir.glob("yoloe-*.pt"))
            if model_files:
                model_path = str(model_files[0])
            else:
                model_path = "yoloe-11s-seg.pt"  # Will auto-download
            
        self.logger.info(f"Testing model loading from {model_path}...")
        
        try:
            import importlib
            if importlib.util.find_spec("ultralytics") is None:
                self.logger.error("ultralytics not installed. Skip model loading test (install 'ultralytics' to enable AI modes).")
                return False
            from ultralytics import YOLOE  # type: ignore

            model = YOLOE(model_path)
            self.logger.info("Model loaded successfully")
            
            # Test prediction on a dummy image
            dummy_image = np.zeros((480, 640, 3), dtype=np.uint8)
            
            # Basic prediction call (avoid API changes) guarded in try
            try:
                names = ["light", "indicator"]
                if hasattr(model, "set_classes") and hasattr(model, "get_text_pe"):
                    model.set_classes(names, model.get_text_pe(names))
                model.predict(dummy_image, conf=0.5, verbose=False)
                self.logger.info("Model prediction test successful")
            except Exception as inner:
                self.logger.warning(f"Model prediction test encountered an issue (continuing): {inner}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Model loading test failed: {e}")
            return False
            

    def create_default_config(self, camera_id: int = 0, model_size: str = "s"):
        self.logger.info("Creating default configuration...")
        
        model_file = f"yoloe-v8{model_size}-seg.pt"
        
        config = {
            "model_path": f"pretrain/{model_file}",
            "camera_id": camera_id,
            "confidence_threshold": 0.3,
            "laser_keywords": [
                "light", "indicator", "led", "laser", 
                "red light", "green light", "warning light",
                "status light", "power light", "ready light"
            ],
            "output_dir": str(self.output_dir),
            "log_level": "INFO",
            "save_detections": True,
            "display_video": True,
            "frame_skip": 0,
            "detection_zones": {
                "enabled": False,
                "zones": [
                    {"name": "control_panel", "bbox": [0, 0, 200, 200]},
                    {"name": "laser_head", "bbox": [400, 300, 640, 480]}
                ]
            },
            "alerts": {
                "enabled": True,
                "error_threshold": 0.7,
                "sound_alerts": False,
                "email_alerts": False
            }
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)
            
        self.logger.info(f"Default configuration saved to {self.config_file}")
        return config
        
    def interactive_setup(self):
        self.logger.info("Starting interactive setup...")
        
        print("\n=== YoloE Laser Monitor Setup ===\n")
        
        # Camera selection
        print("Testing available cameras...")
        working_cameras = []
        for i in range(5):  # Test first 5 camera IDs
            if self.test_camera(i):
                working_cameras.append(i)
                
        if not working_cameras:
            print("No working cameras found!")
            return False
            
        print(f"Working cameras found: {working_cameras}")
        camera_id = working_cameras[0]
        if len(working_cameras) > 1:
            try:
                camera_id = int(input(f"Select camera ID {working_cameras}: "))
                if camera_id not in working_cameras:
                    camera_id = working_cameras[0]
            except ValueError:
                pass
                
        # Model size selection
        print("\nAvailable model sizes:")
        print("s - Small (fastest, lower accuracy)")
        print("m - Medium (balanced)")
        print("l - Large (slowest, highest accuracy)")
        
        model_size = input("Select model size [s]: ").strip().lower()
        if model_size not in ["s", "m", "l"]:
            model_size = "s"
            
        # Download selected model
        self.download_models([model_size])
        
        # Test model loading
        if not self.test_model_loading():
            print("Model loading test failed!")
            return False
            
        # Create configuration
        config = self.create_default_config(camera_id, model_size)
        
        print(f"\nSetup complete!")
        print(f"Configuration saved to: {self.config_file}")
        print(f"\nTo start monitoring, run:")
        print(f"python cli.py monitor --config {self.config_file}")
        
        return True
        
    def validate_installation(self):
        self.logger.info("Validating installation...")
        
        issues = []
        
        # Check Python packages
        try:
            import cv2  # noqa: F401
            import numpy as np  # noqa: F401
        except ImportError as e:
            issues.append(f"Missing core Python package (required even for bbox mode): {e}")
        import importlib
        if importlib.util.find_spec("ultralytics") is None:
            issues.append("ultralytics not installed (required only for text/visual AI detection modes)")
        if importlib.util.find_spec("huggingface_hub") is None:
            issues.append("huggingface-hub not installed (optional, used for model hub interactions)")
            
        # Check directories
        if not self.pretrain_dir.exists():
            issues.append(f"Pretrain directory missing: {self.pretrain_dir}")
            
        # Check for at least one model
        model_files = list(self.pretrain_dir.glob("yoloe-*.pt"))
        if not model_files:
            issues.append("No YoloE model files found in pretrain directory")
            
        # Check camera access
        if not self.test_camera():
            issues.append("No working camera found")
            
        if issues:
            self.logger.error("Installation validation failed:")
            for issue in issues:
                self.logger.error(f"  - {issue}")
            return False
        else:
            self.logger.info("Installation validation passed!")
            return True


def main():
    parser = argparse.ArgumentParser(description="Setup YoloE Laser Monitor")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    parser.add_argument("--models", nargs="+", choices=["s", "m", "l"], 
                       help="Model sizes to download")
    parser.add_argument("--camera", type=int, help="Camera ID to test")
    parser.add_argument("--interactive", action="store_true", 
                       help="Run interactive setup")
    parser.add_argument("--validate", action="store_true",
                       help="Validate installation")
    parser.add_argument("--config-only", action="store_true",
                       help="Only create configuration file")
    
    args = parser.parse_args()
    
    setup = YoloESetup(args.output_dir)
    setup.create_directories()
    
    if args.validate:
        success = setup.validate_installation()
        sys.exit(0 if success else 1)
        
    if args.interactive:
        success = setup.interactive_setup()
        sys.exit(0 if success else 1)
        
    if args.config_only:
        camera_id = args.camera if args.camera is not None else 0
        setup.create_default_config(camera_id)
        return
        
    # Default setup
    if args.models:
        setup.download_models(args.models)
    else:
        setup.download_models(["s"])
        
    if args.camera is not None:
        setup.test_camera(args.camera)
    else:
        setup.test_camera()
        
    setup.test_model_loading()
    setup.create_default_config()
    
    print("\nSetup complete! Run with --interactive for guided setup.")


if __name__ == "__main__":
    main()