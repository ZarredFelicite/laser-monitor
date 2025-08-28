#!/usr/bin/env python3
"""
Camera Manager - Unified camera interface for USB and Pi camera modules

Supports:
- USB/Webcam cameras via OpenCV
- Raspberry Pi camera modules via picamera2/libcamera
- Auto-detection of available camera types
- Unified interface for both camera types
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple, Dict, Any, List
from pathlib import Path
import platform

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
    # Create dummy numpy for type hints
    class np:
        ndarray = object


class CameraInterface(ABC):
    """Abstract base class for camera implementations"""
    
    @abstractmethod
    def open(self) -> bool:
        """Open camera connection"""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close camera connection"""
        pass
    
    @abstractmethod
    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read a frame from camera"""
        pass
    
    @abstractmethod
    def set_property(self, prop: str, value: Any) -> bool:
        """Set camera property"""
        pass
    
    @abstractmethod
    def get_property(self, prop: str) -> Any:
        """Get camera property"""
        pass
    
    @abstractmethod
    def is_opened(self) -> bool:
        """Check if camera is opened"""
        pass
    
    @abstractmethod
    def get_info(self) -> Dict[str, Any]:
        """Get camera information"""
        pass


class USBCamera(CameraInterface):
    """USB/Webcam camera implementation using OpenCV"""
    
    def __init__(self, camera_id: int = 0):
        self.camera_id = camera_id
        self.cap = None
        self.logger = logging.getLogger(__name__)
        
    def open(self) -> bool:
        """Open USB camera"""
        if not OPENCV_AVAILABLE:
            self.logger.error("OpenCV not available for USB camera")
            return False
            
        try:
            self.cap = cv2.VideoCapture(self.camera_id)
            if not self.cap.isOpened():
                self.logger.error(f"Failed to open USB camera {self.camera_id}")
                return False
            
            # Set some default properties
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer lag
            self.logger.info(f"USB camera {self.camera_id} opened successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error opening USB camera: {e}")
            return False
    
    def close(self) -> None:
        """Close USB camera"""
        if self.cap:
            self.cap.release()
            self.cap = None
            self.logger.info(f"USB camera {self.camera_id} closed")
    
    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read frame from USB camera"""
        if not self.cap:
            return False, None
        
        ret, frame = self.cap.read()
        return ret, frame if ret else None
    
    def set_property(self, prop: str, value: Any) -> bool:
        """Set USB camera property"""
        if not self.cap:
            return False
        
        prop_map = {
            'width': cv2.CAP_PROP_FRAME_WIDTH,
            'height': cv2.CAP_PROP_FRAME_HEIGHT,
            'fps': cv2.CAP_PROP_FPS,
            'brightness': cv2.CAP_PROP_BRIGHTNESS,
            'contrast': cv2.CAP_PROP_CONTRAST,
            'saturation': cv2.CAP_PROP_SATURATION,
            'exposure': cv2.CAP_PROP_EXPOSURE,
            'auto_exposure': cv2.CAP_PROP_AUTO_EXPOSURE,
        }
        
        if prop in prop_map:
            return self.cap.set(prop_map[prop], value)
        return False
    
    def get_property(self, prop: str) -> Any:
        """Get USB camera property"""
        if not self.cap:
            return None
        
        prop_map = {
            'width': cv2.CAP_PROP_FRAME_WIDTH,
            'height': cv2.CAP_PROP_FRAME_HEIGHT,
            'fps': cv2.CAP_PROP_FPS,
            'brightness': cv2.CAP_PROP_BRIGHTNESS,
            'contrast': cv2.CAP_PROP_CONTRAST,
            'saturation': cv2.CAP_PROP_SATURATION,
            'exposure': cv2.CAP_PROP_EXPOSURE,
            'auto_exposure': cv2.CAP_PROP_AUTO_EXPOSURE,
        }
        
        if prop in prop_map:
            return self.cap.get(prop_map[prop])
        return None
    
    def is_opened(self) -> bool:
        """Check if USB camera is opened"""
        return self.cap is not None and self.cap.isOpened()
    
    def get_info(self) -> Dict[str, Any]:
        """Get USB camera information"""
        if not self.is_opened():
            return {"type": "usb", "status": "closed"}
        
        return {
            "type": "usb",
            "camera_id": self.camera_id,
            "width": self.get_property('width'),
            "height": self.get_property('height'),
            "fps": self.get_property('fps'),
            "backend": self.cap.getBackendName() if hasattr(self.cap, 'getBackendName') else "unknown"
        }


class PiCamera(CameraInterface):
    """Raspberry Pi camera implementation that shells out to rpicam-still.

    This implementation captures a single still image on each read by invoking:
    env -i PATH="/usr/bin:/bin:/usr/sbin:/sbin" rpicam-still --output <file> [options]

    It detects rpicam-still presence and available flags at init time and
    supports a whitelist of common camera properties mapped to rpicam-still flags.
    """

    def __init__(self, camera_id: int = 0):
        self.camera_id = camera_id
        self.logger = logging.getLogger(__name__)
        self._config = {}
        self._is_open = False
        self._rpicam_path = None
        self._help_text = ""

        # Lazy import/check for rpicam-still in PATH
        try:
            import shutil
            self._rpicam_path = shutil.which("rpicam-still")
        except Exception:
            self._rpicam_path = None

        if self._rpicam_path:
            # Probe --help to discover supported long flags
            try:
                import subprocess
                p = subprocess.run([
                    "env", "-i", "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
                    self._rpicam_path, "--help"
                ], capture_output=True, text=True, timeout=5)
                self._help_text = p.stdout + "\n" + p.stderr
                self.available = True
            except Exception:
                self.logger.warning("rpicam-still found but --help probe failed; continuing with conservative defaults")
                self.available = True
        else:
            self.logger.warning("rpicam-still not found in PATH; Pi camera support disabled")
            self.available = False

        # Whitelist mapping from camera property names to rpicam-still flags.
        # We map common config field names to long-form rpicam-still flags. At capture time
        # we will only include flags that actually appear in the probed --help text (or if
        # probing failed, we fall back to optimistic inclusion).
        self._flag_map = {
            # Basic image geometry / encoding
            'width': '--width',
            'height': '--height',
            'quality': '--quality',
            'encoding': '--encoding',
            'exif': '--exif',
            'thumb': '--thumb',
            'rotation': '--rotation',
            'hflip': '--hflip',
            'vflip': '--vflip',
            'roi': '--roi',

            # Exposure / gain / metering
            'shutter': '--shutter',            # shutter speed in us
            'iso': '--iso',                    # ISO value
            'exposure': '--exposure',          # exposure mode or numeric
            'analoggain': '--analoggain',      # analogue gain (name varies across tools)
            'gain': '--gain',                  # digital gain
            'auto_exposure': '--exposure',     # we map boolean auto_exposure -> exposure=auto
            'aelock': '--aelock',
            'metering': '--metering',
            'ev': '--ev',                      # exposure compensation

            # White balance
            'awb': '--awb',                    # auto white balance mode
            'awbgains': '--awbgains',          # explicit red,blue gains

            # Colour / image tuning (removed most to prevent over-bright images)
            # 'brightness': '--brightness',    # removed - can cause over-bright images
            # 'contrast': '--contrast',        # removed - let camera use defaults
            # 'saturation': '--saturation',    # removed - let camera use defaults
            # 'sharpness': '--sharpness',      # removed - let camera use defaults

            # Capture / performance
            'timeout': '--timeout',
            'framerate': '--framerate',
            'denoise': '--denoise',
            'buffer_count': '--buffer-count',
            'viewfinder_width': '--viewfinder-width',
            'viewfinder_height': '--viewfinder-height',
            'viewfinder_mode': '--viewfinder-mode',
            'viewfinder_buffer_count': '--viewfinder-buffer-count',

            # Other useful flags
            'raw': '--raw',                    # boolean-style flag
            'immediate': '--immediate',        # boolean-style flag
            'nopreview': '--nopreview',
        }

        # Flags that are recognized but not directly translated to a rpicam-still flag
        # (we may still store them or handle them specially later)
        self._recognized_props = {
            'fps',                 # framerate not directly used for stills
            'auto_exposure',       # handled specially (maps to exposure=auto)
            'autofocus_mode',
            'autofocus_range',
            'autofocus_speed',
            'autofocus_window'
        }

        # Set of flags that don't take an explicit value when present (standalone toggles)
        # For these we only emit the flag name if the value is truthy.
        self._flags_no_value = {'--nopreview', '--raw', '--immediate'}

    def open(self) -> bool:
        """Open Pi camera (no persistent device connection required).

        We simply mark the camera as available/opened. Each read will invoke
        rpicam-still to capture a fresh image with the configured options.
        """
        if not self.available:
            return False
        self._is_open = True
        # Small warm-up sleep to allow any external lighting to stabilize
        time.sleep(0.5)
        self.logger.info(f"Pi camera (rpicam-still) ready: {self._rpicam_path}")
        return True

    def close(self) -> None:
        """Close Pi camera (no-op for rpicam-still)."""
        self._is_open = False

    def _build_rpicam_cmd(self, tmp_path: str) -> list:
        """Build the rpicam-still command for the current _config and tmp_path.

        This helper exists to allow testing command construction without executing
        rpicam-still. It mirrors the logic used in read().
        """
        cmd = [
            'env', '-i', 'PATH=/usr/bin:/bin:/usr/sbin:/sbin',
            self._rpicam_path, '--output', tmp_path, '--nopreview'
        ]

        # Compute effective exposure semantics first to avoid emitting --exposure multiple times
        if 'exposure' in self._config:
            exp_val = self._config.get('exposure')
            if isinstance(exp_val, (int, float)) and int(exp_val) == -1:
                exp_effective = 'normal'  # rpicam-still uses 'normal' for auto exposure
            else:
                exp_effective = str(exp_val)
        elif self._config.get('auto_exposure'):
            exp_effective = 'normal'  # rpicam-still uses 'normal' for auto exposure
        else:
            exp_effective = None

        if exp_effective is not None:
            flag = self._flag_map.get('exposure')
            if flag and (not self._help_text or flag in self._help_text):
                cmd.extend([flag, exp_effective])

        for prop, val in self._config.items():
            if prop in ('exposure', 'auto_exposure'):
                continue

            # Handle flags that require no value (boolean toggles)
            if prop in self._flag_map and self._flag_map[prop] in self._flags_no_value:
                flag = self._flag_map[prop]
                if val:
                    if not self._help_text or flag in self._help_text:
                        cmd.append(flag)
                continue

            if prop in self._flag_map:
                flag = self._flag_map[prop]
                if not self._help_text or flag in self._help_text:
                    if isinstance(val, (list, tuple)):
                        val_str = ','.join([str(x) for x in val])
                        cmd.extend([flag, val_str])
                    elif isinstance(val, bool):
                        cmd.extend([flag, 'on' if val else 'off'])
                    else:
                        cmd.extend([flag, str(val)])
                continue

            if prop in self._recognized_props:
                self.logger.debug(f"Recognized property {prop} stored but not passed to rpicam-still")
                continue

        return cmd

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Capture a still image via rpicam-still and return it as a numpy array.

        Returns (True, frame) on success, (False, None) on failure.
        """
        if not self._is_open or not self.available:
            return False, None

        # Ensure OpenCV is available for image decoding
        if not OPENCV_AVAILABLE:
            self.logger.error("OpenCV required to read images captured by rpicam-still")
            return False, None

        import subprocess, tempfile, os, shutil

        # Create a temporary output file
        fd, tmp_path = tempfile.mkstemp(suffix='.jpg', prefix='rpicam_')
        os.close(fd)

        cmd = [
            'env', '-i', 'PATH=/usr/bin:/bin:/usr/sbin:/sbin',
            self._rpicam_path, '--output', tmp_path, '--nopreview'
        ]

        # Append flags from current config if supported
        # Compute effective exposure semantics first to avoid emitting --exposure multiple times
        effective_exposure_emitted = False
        # Determine if an explicit exposure value exists and what it should be
        if 'exposure' in self._config:
            exp_val = self._config.get('exposure')
            if isinstance(exp_val, (int, float)) and int(exp_val) == -1:
                exp_effective = 'normal'  # rpicam-still uses 'normal' for auto exposure
            else:
                exp_effective = str(exp_val)
        elif self._config.get('auto_exposure'):
            # No explicit exposure provided but auto_exposure requested
            exp_effective = 'normal'  # rpicam-still uses 'normal' for auto exposure
        else:
            exp_effective = None

        # If we have an effective exposure, and rpicam-still supports it, add it once
        if exp_effective is not None:
            flag = self._flag_map.get('exposure')
            if flag and (not self._help_text or flag in self._help_text):
                cmd.extend([flag, exp_effective])
                effective_exposure_emitted = True

        for prop, val in self._config.items():
            # Skip exposure/auto_exposure as we've handled them above
            if prop in ('exposure', 'auto_exposure'):
                continue

            # Handle flags that require no value (boolean toggles)
            if prop in self._flag_map and self._flag_map[prop] in self._flags_no_value:
                flag = self._flag_map[prop]
                if val:
                    # Only include the flag (no explicit value)
                    if not self._help_text or flag in self._help_text:
                        cmd.append(flag)
                continue

            if prop in self._flag_map:
                flag = self._flag_map[prop]
                # Only include flag if help text indicates support or if we couldn't probe
                if not self._help_text or flag in self._help_text:
                    # Special formatting for list/tuple values (e.g., awbgains, roi, thumb)
                    if isinstance(val, (list, tuple)):
                        # Join numeric values with commas (rpicam-still expects 'r,b' or 'x,y,w,h')
                        val_str = ','.join([str(x) for x in val])
                        cmd.extend([flag, val_str])
                    elif isinstance(val, bool):
                        # map True -> 'on'/'off' for boolean-valued flags that expect a value
                        cmd.extend([flag, 'on' if val else 'off'])
                    else:
                        cmd.extend([flag, str(val)])
                continue

            # Recognized but unmapped props: log a debug message
            if prop in self._recognized_props:
                # we handle fps/auto_exposure differently (fps is not relevant for still capture)
                self.logger.debug(f"Recognized property {prop} stored but not passed to rpicam-still")
                continue

        try:
            # Use helper to build command (keeps read() logic minimal)
            cmd = self._build_rpicam_cmd(tmp_path)
            self.logger.debug(f"Running rpicam-still command: {' '.join(cmd)}")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode != 0:
                self.logger.error(f"rpicam-still failed: {proc.returncode} stderr={proc.stderr}")
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                return False, None

            # Read image with OpenCV
            frame = cv2.imread(tmp_path)
            if frame is None:
                self.logger.error(f"Failed to load image saved by rpicam-still: {tmp_path}")
                os.remove(tmp_path)
                return False, None

            # Clean up temp file
            try:
                os.remove(tmp_path)
            except Exception:
                pass

            return True, frame

        except subprocess.TimeoutExpired:
            self.logger.error("rpicam-still timed out")
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return False, None
        except Exception as e:
            self.logger.error(f"Error invoking rpicam-still: {e}")
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return False, None

    def set_property(self, prop: str, value: Any) -> bool:
        """Set camera property for future captures.

        We store requested properties in self._config and they will be translated
        to rpicam-still flags at capture time if supported. Accepts common aliases
        used by the rest of the codebase (e.g. 'fps' -> 'framerate').
        """
        # Normalize common aliases to our internal keys
        alias_map = {
            'fps': 'framerate',
            'quality': 'quality',
            'resolution_width': 'width',
            'resolution_height': 'height',
            'exposure_value': 'exposure',
            'auto_exposure': 'auto_exposure',
            'awb_gains': 'awbgains',
            'awbgains': 'awbgains'
        }

        key = alias_map.get(prop, prop)

        # Accept if key is in flag map or recognized props
        if key in self._flag_map or key in self._recognized_props or key in ('width', 'height'):
            # For boolean/no-value flags, store the boolean directly
            self._config[key] = value
            return True

        # Legacy names mapping (ensure backwards compatibility)
        legacy_map = {
            'width': 'width', 'height': 'height', 'exposure': 'exposure'
            # Removed color tuning props: brightness, contrast, saturation
        }
        if prop in legacy_map:
            self._config[legacy_map[prop]] = value
            return True

        self.logger.debug(f"Attempted to set unsupported Pi camera property: {prop}")
        return False

    def get_property(self, prop: str) -> Any:
        """Get stored property value (no live device queries)."""
        # Resolve aliases as in set_property
        alias_map = {
            'fps': 'framerate',
            'resolution_width': 'width',
            'resolution_height': 'height',
            'exposure_value': 'exposure'
        }
        key = alias_map.get(prop, prop)
        return self._config.get(key)

    def is_opened(self) -> bool:
        return self._is_open and self.available

    def get_info(self) -> Dict[str, Any]:
        info = {"type": "pi", "camera_id": self.camera_id, "available": self.available}
        info.update({k: v for k, v in self._config.items() if k in ('width', 'height')})
        return info


class CameraManager:
    """Unified camera manager with auto-detection"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.camera = None
        self.camera_type = None
        
    def detect_cameras(self) -> List[Dict[str, Any]]:
        """Detect available cameras"""
        cameras = []
        
        # Check for Pi cameras
        if self._is_raspberry_pi():
            # Prefer picamera2/libcamera if available
            found_any = False
            try:
                from picamera2 import Picamera2
                for i in range(2):
                    try:
                        picam2 = Picamera2(i)
                        cameras.append({
                            "id": i,
                            "type": "pi",
                            "name": f"Pi Camera {i}",
                            "available": True
                        })
                        picam2.close()
                        found_any = True
                    except Exception:
                        break
            except ImportError:
                self.logger.info("picamera2 not available")

            # If picamera2 not available, fall back to checking for rpicam-still
            if not found_any:
                try:
                    import shutil
                    if shutil.which("rpicam-still"):
                        cameras.append({
                            "id": 0,
                            "type": "pi",
                            "name": "Pi Camera (rpicam-still)",
                            "available": True
                        })
                except Exception:
                    pass
        
        # Check for USB cameras
        if OPENCV_AVAILABLE:
            for i in range(5):  # Check first 5 USB camera IDs
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    cameras.append({
                        "id": i,
                        "type": "usb",
                        "name": f"USB Camera {i}",
                        "available": True
                    })
                    cap.release()
        else:
            self.logger.warning("OpenCV not available - USB camera detection disabled")
        
        return cameras
    
    def _is_raspberry_pi(self) -> bool:
        """Check if running on Raspberry Pi"""
        try:
            with open('/proc/cpuinfo', 'r') as f:
                cpuinfo = f.read()
                return 'Raspberry Pi' in cpuinfo or 'BCM' in cpuinfo
        except:
            return False
    
    def auto_select_camera(self, preferred_id: int = 0, preferred_type: Optional[str] = None) -> Optional[CameraInterface]:
        """Auto-select best available camera"""
        cameras = self.detect_cameras()
        
        if not cameras:
            self.logger.error("No cameras detected")
            return None
        
        # If preferred type specified, try that first
        if preferred_type:
            for cam in cameras:
                if cam['type'] == preferred_type and cam['id'] == preferred_id:
                    return self._create_camera(cam['type'], cam['id'])
        
        # Try preferred ID with any type
        for cam in cameras:
            if cam['id'] == preferred_id:
                return self._create_camera(cam['type'], cam['id'])
        
        # Fall back to first available camera
        first_cam = cameras[0]
        self.logger.info(f"Using first available camera: {first_cam['name']}")
        return self._create_camera(first_cam['type'], first_cam['id'])
    
    def _create_camera(self, camera_type: str, camera_id: int) -> Optional[CameraInterface]:
        """Create camera instance of specified type"""
        try:
            if camera_type == "pi":
                camera = PiCamera(camera_id)
                if camera.available:
                    return camera
                else:
                    self.logger.warning("Pi camera not available, falling back to USB")
                    return USBCamera(camera_id)
            else:
                return USBCamera(camera_id)
        except Exception as e:
            self.logger.error(f"Error creating {camera_type} camera: {e}")
            return None
    
    def open_camera(self, camera_id: int = 0, camera_type: Optional[str] = None) -> bool:
        """Open camera with auto-detection"""
        self.camera = self.auto_select_camera(camera_id, camera_type)
        
        if not self.camera:
            return False
        
        success = self.camera.open()
        if success:
            self.camera_type = self.camera.get_info()['type']
            self.logger.info(f"Opened {self.camera_type} camera {camera_id}")
        else:
            self.camera = None
            
        return success
    
    def close_camera(self) -> None:
        """Close current camera"""
        if self.camera:
            self.camera.close()
            self.camera = None
            self.camera_type = None
    
    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read frame from current camera"""
        if not self.camera:
            return False, None
        return self.camera.read()
    
    def configure_camera(self, config: Dict[str, Any]) -> bool:
        """Configure camera with settings"""
        if not self.camera:
            return False
        
        success = True
        for prop, value in config.items():
            if not self.camera.set_property(prop, value):
                self.logger.warning(f"Failed to set camera property {prop}={value}")
                success = False
        
        return success
    
    def get_camera_info(self) -> Dict[str, Any]:
        """Get current camera information"""
        if not self.camera:
            return {"status": "no_camera"}
        
        return self.camera.get_info()
    
    def is_opened(self) -> bool:
        """Check if camera is opened"""
        return self.camera is not None and self.camera.is_opened()


def main():
    """Test camera detection and functionality"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Camera Manager Test")
    parser.add_argument("--detect", action="store_true", help="Detect available cameras")
    parser.add_argument("--test", type=int, help="Test camera ID")
    parser.add_argument("--type", choices=["usb", "pi"], help="Force camera type")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    manager = CameraManager()
    
    if args.detect:
        cameras = manager.detect_cameras()
        print("Available cameras:")
        for cam in cameras:
            print(f"  {cam['name']} (ID: {cam['id']}, Type: {cam['type']})")
    
    elif args.test is not None:
        print(f"Testing camera {args.test} (type: {args.type or 'auto'})")
        
        if manager.open_camera(args.test, args.type):
            info = manager.get_camera_info()
            print(f"Camera info: {info}")
            
            # Test frame capture
            ret, frame = manager.read_frame()
            if ret:
                print(f"Frame captured: {frame.shape}")
                
                # Save test frame
                if OPENCV_AVAILABLE:
                    cv2.imwrite(f"test_camera_{args.test}.jpg", frame)
                    print(f"Test frame saved as test_camera_{args.test}.jpg")
                else:
                    print("OpenCV not available - cannot save test frame")
            else:
                print("Failed to capture frame")
                
            manager.close_camera()
        else:
            print("Failed to open camera")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()