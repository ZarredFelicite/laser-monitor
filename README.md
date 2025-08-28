# Laser Monitor - Single-Shot Detection System

A simplified laser cutter monitoring system that captures one frame, performs AI-powered detection, saves results, and exits. Designed for integration with external monitoring systems or scheduled execution.

## Features

### 🎯 **Multi-Modal Detection**
- **Text Prompts**: Natural language descriptions ("red light", "laser indicator", "warning light")
- **Visual Prompts**: AI-based detection using reference crops and bounding boxes
- **Fixed Bounding Box**: Simple image analysis within predefined regions (no AI model needed)

### 📷 **Universal Camera Support**
- **Raspberry Pi Camera Modules**: Native support via picamera2/libcamera
- **USB/Webcam Cameras**: OpenCV-based support for standard cameras
- **Auto-Detection**: Automatically selects best available camera

### ⚙️ **Python Configuration**
- **Type-Safe Configs**: Dataclass-based configuration with full IDE support
- **Visual Prompt Integration**: Direct import of visual prompt configurations
- **Simple Setup**: Python-only configs, no JSON/YAML complexity

### 📊 **Output & Logging**
- **Annotated Images**: Saves detection results with bounding boxes
- **JSON Detection Data**: Structured detection results with metadata
- **Comprehensive Logging**: Configurable logging levels and file output

## Quick Start

### 1. Environment Setup

**Using Nix (Recommended):**
```bash
nix develop
```

**Traditional Python:**
```bash
pip install -r requirements.txt
```

### 2. Initial Setup
```bash
python cli.py setup --interactive
```

### 3. Run Detection
```bash
# Single detection with default config
python cli.py monitor

# With custom config
python cli.py monitor --config my_config.py

# With visual prompts
python cli.py monitor --visual-prompt reference_crop.jpg
```

## Configuration

### Basic Configuration (`example_config.py`)
```python
from config import LaserMonitorConfig, CameraConfig, DetectionConfig

config = LaserMonitorConfig(
    model_path="pretrain/yoloe-11s-seg.pt",
    
    camera=CameraConfig(
        camera_id=0,
        camera_type=None,  # None=auto-detect, "pi"=Pi camera, "usb"=USB camera
        resolution_width=1920,
        resolution_height=1080
    ),
    
    detection=DetectionConfig(
        mode="text",  # "text", "visual", or "bbox"
        confidence_threshold=0.3,
        laser_keywords=["red light", "laser indicator", "warning light"]
    )
)
```

### Visual Prompt Configuration
```bash
# 1. Create visual prompts interactively
python visual_prompt_selector.py reference_image.jpg

# 2. This creates reference_image.config.py with visual prompts

# 3. Use directly
python cli.py monitor --config reference_image.config.py
```

## Camera Support

### Raspberry Pi Camera Module
```python
camera=CameraConfig(
    camera_type="pi",  # Force Pi camera
    camera_id=0
)
```

### USB/Webcam
```python
camera=CameraConfig(
    camera_type="usb",  # Force USB camera
    camera_id=0
)
```

### Auto-Detection (Recommended)
```python
camera=CameraConfig(
    camera_type=None,  # Auto-detect best camera
    camera_id=0
)
```

## Detection Modes

### Text Prompts
```python
detection=DetectionConfig(
    mode="text",
    laser_keywords=["red light", "indicator", "laser", "warning light"]
)
```

### Visual Prompts
```python
detection=DetectionConfig(
    mode="visual",
    refer_image="/path/to/reference.jpg",
    visual_prompts=[[0.1, 0.1, 0.3, 0.3]]  # Normalized bbox coordinates
)
```

### Fixed Bounding Box (No AI Model)
```python
detection=DetectionConfig(
    mode="bbox",
    visual_prompts=[[0.1, 0.1, 0.3, 0.3], [0.7, 0.7, 0.9, 0.9]],  # Normalized coordinates
    confidence_threshold=0.5
)
```

This mode analyzes predefined regions using simple image processing:
- **Red light detection**: High saturation in red hue range
- **Green light detection**: High saturation in green hue range  
- **Bright light detection**: High brightness values
- **Off/dark detection**: Low brightness and variation

## Output Structure

```
output/
├── detections/
│   └── detections_20250818_143022.json    # Detection results
├── screenshots/
│   └── detection_20250818_143022.jpg      # Annotated images
└── visual_prompts/
    └── reference_crop.jpg                  # Visual prompt images
```

### Detection JSON Format
```json
{
  "timestamp": "2025-08-18T14:30:22.123456",
  "detection_count": 2,
  "detections": [
    {
      "timestamp": "2025-08-18T14:30:22.123456",
      "confidence": 0.85,
      "bbox": [100, 150, 200, 250],
      "class_name": "red light",
      "laser_status": "warning",
      "zone_name": "control_panel"
    }
  ],
  "config": {
    "model_path": "pretrain/yoloe-11s-seg.pt",
    "detection_mode": "text",
    "confidence_threshold": 0.3,
    "camera_info": {"type": "pi", "camera_id": 0}
  }
}
```

## CLI Commands

### Monitor (Main Command)
```bash
# Basic detection
python cli.py monitor

# With options
python cli.py monitor \
  --config my_config.py \
  --camera 0 \
  --confidence 0.4 \
  --detection-mode visual \
  --verbose
```

### Setup
```bash
# Interactive setup
python cli.py setup --interactive

# Download specific models
python cli.py setup --models s m l
```

### Testing
```bash
# Test camera
python cli.py test --camera 0

# Test specific camera type
python cli.py test --camera 0 --camera-type pi

# Test model loading
python cli.py test --model pretrain/yoloe-11s-seg.pt

# Test configuration
python cli.py test --config my_config.py
```

### Configuration Management
```bash
# Create default config
python cli.py config --create default_config.py

# Validate config
python cli.py config --validate my_config.py

# Show config summary
python cli.py config --summary my_config.py
```

### System Information
```bash
python cli.py info
```

## Bbox Mode (No AI Model Required)

The bbox mode provides a lightweight alternative that doesn't require downloading large AI models. It uses simple image processing to analyze predefined regions:

### Configuration
```python
detection=DetectionConfig(
    mode="bbox",
    visual_prompts=[
        [0.1, 0.1, 0.3, 0.3],  # Top-left region
        [0.7, 0.7, 0.9, 0.9]   # Bottom-right region
    ],
    confidence_threshold=0.5
)
```

### Detection Logic
- **Red Light**: Detects high saturation in red hue range (0-10° or 170-180°)
- **Green Light**: Detects high saturation in green hue range (40-80°)
- **Bright Light**: Detects high brightness values (>200)
- **Off/Dark**: Detects low brightness with low variation (<50 brightness, <20 std dev)

### Advantages
- **No Model Download**: Works immediately without large file downloads
- **Fast**: Simple image processing is very fast
- **Low Memory**: Minimal memory usage
- **Deterministic**: Consistent results based on color/brightness thresholds

### Use Cases
- **Simple indicator monitoring**: Basic on/off or color detection
- **Resource-constrained devices**: When AI models are too large
- **Quick prototyping**: Fast setup without model complexity
- **Backup detection**: Fallback when AI models fail

## Integration Examples

### Cron Job (Periodic Monitoring)
```bash
# Run every 5 minutes
*/5 * * * * cd /path/to/laser_monitor && python cli.py monitor --config production.py
```

### Systemd Service (On-Demand)
```ini
[Unit]
Description=Laser Monitor Detection
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/path/to/laser_monitor
ExecStart=/usr/bin/python cli.py monitor --config production.py
User=pi

[Install]
WantedBy=multi-user.target
```

### External Trigger Script
```bash
#!/bin/bash
# trigger_detection.sh

cd /path/to/laser_monitor
python cli.py monitor --config production.py

# Check exit code
if [ $? -eq 0 ]; then
    echo "Detection completed successfully"
    # Process results...
else
    echo "Detection failed"
    # Handle error...
fi
```

### Python Integration
```python
from laser_monitor import LaserMonitor
from config import ConfigManager

# Load config
config_manager = ConfigManager("my_config.py")
config = config_manager.load_config()

# Run detection
monitor = LaserMonitor(config)
success = monitor.run()

if success:
    print("Detection completed")
    # Process output files...
```

## Deployment

### Raspberry Pi 5 (Recommended)
1. **Install dependencies:**
   ```bash
   sudo apt update
   sudo apt install python3-pip python3-venv
   pip install -r requirements.txt
   ```

2. **Enable Pi camera:**
   ```bash
   sudo raspi-config
   # Interface Options -> Camera -> Enable
   ```

3. **Configure for Pi camera:**
   ```python
   camera=CameraConfig(camera_type="pi", camera_id=0)
   ```

4. **Run detection:**
   ```bash
   python cli.py monitor --config pi_config.py
   ```

### Desktop/Workstation
1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure for USB camera:**
   ```python
   camera=CameraConfig(camera_type="usb", camera_id=0)
   ```

3. **Create visual prompts:**
   ```bash
   python visual_prompt_selector.py reference.jpg
   ```

## Project Structure

```
laser_monitor/
├── cli.py                    # Command-line interface
├── laser_monitor.py          # Core detection logic (simplified)
├── config.py                # Configuration system
├── camera_manager.py         # Camera abstraction
├── visual_prompt_selector.py # Interactive prompt creation
├── setup_yoloe.py           # Model setup and download
├── example_config.py         # Example configuration
├── requirements.txt          # Python dependencies
├── pretrain/                 # Model storage
└── output/                   # Runtime outputs
    ├── detections/           # Detection JSON files
    ├── screenshots/          # Annotated images
    └── visual_prompts/       # Visual prompt images
```

## Model Information

### Supported Models
- **yoloe-11s-seg.pt**: Small, fast model (~22MB)
- **yoloe-11m-seg.pt**: Medium model (~50MB)
- **yoloe-11l-seg.pt**: Large, accurate model (~100MB)
- **yoloe-v8s/m/l-seg.pt**: YOLOv8-based variants

### Model Selection
- **Pi 5**: Use `yoloe-11s-seg.pt` for best performance
- **Desktop**: Use `yoloe-11m-seg.pt` or `yoloe-11l-seg.pt` for accuracy
- **GPU Available**: Any model size works well

## Troubleshooting

### Camera Issues
```bash
# Test camera detection
python cli.py info

# Test specific camera
python cli.py test --camera 0 --camera-type pi
```

### Model Issues
```bash
# Re-download models
python cli.py setup --models s

# Test model loading
python cli.py test --model pretrain/yoloe-11s-seg.pt
```

### Configuration Issues
```bash
# Validate config
python cli.py config --validate my_config.py

# Check config summary
python cli.py config --summary my_config.py
```

### Low Detection Accuracy
1. **Lower confidence threshold**: `confidence_threshold=0.2`
2. **Use visual prompts**: More precise than text prompts
3. **Better lighting**: Ensure good illumination
4. **Larger model**: Use `yoloe-11m-seg.pt` or `yoloe-11l-seg.pt`

## License

This project is designed for laser cutter safety monitoring and automation. Use responsibly and ensure proper safety measures are in place.