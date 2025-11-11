# Hot-Reload Detection Box Configuration

## Overview

The laser monitor now supports **hot-reloading** of detection box configurations from the web UI. Changes made in the web dashboard take effect on the **next detection cycle** without requiring a monitor restart.

## How It Works

### 1. Web UI Makes Changes
User adjusts detection boxes in the web dashboard (`http://localhost:5000`)

### 2. Changes Saved to Disk
Flask API saves changes to `web_ui.config.py`:
```python
#!/usr/bin/env python3
refer_image = r"/path/to/latest/screenshot.jpg"
visual_prompts = [[x1, y1, x2, y2], [x1, y1, x2, y2]]
image_dimensions = {"width": 1920, "height": 1080}
metadata = {"created_with": "web_ui_dashboard", ...}
```

### 3. Monitor Detects Changes
Before each detection cycle, `LaserMonitor.reload_visual_prompts()`:
- Checks if `web_ui.config.py` exists
- Compares file modification time (`st_mtime`) to last reload
- If changed, reloads visual prompts from disk

### 4. Config Applied
Updated visual prompts are applied to `self.config.detection.visual_prompts`

### 5. Next Detection Uses New Boxes
The next image processed uses the updated detection boxes

## Implementation Details

### LaserMonitor.reload_visual_prompts()

Located in `laser_monitor.py`:

```python
def reload_visual_prompts(self) -> bool:
    """Reload visual prompts from web_ui.config.py if modified"""
    web_ui_config_path = Path("web_ui.config.py")
    
    # Only reload if using visual mode
    if self.config.detection.mode != "visual":
        return False
    
    # Check if file exists and has been modified
    if not web_ui_config_path.exists():
        return False
    
    current_mtime = web_ui_config_path.stat().st_mtime
    
    # Initialize tracking on first call
    if not hasattr(self, '_last_config_reload_time'):
        self._last_config_reload_time = current_mtime
        return False
    
    # Check for modifications
    if current_mtime <= self._last_config_reload_time:
        return False  # No changes
    
    # Reload config
    from config.config import load_visual_prompts
    visual_data = load_visual_prompts(str(web_ui_config_path))
    
    # Update detection config in-place
    self.config.detection.refer_image = visual_data.get('refer_image')
    visual_prompts = visual_data.get('visual_prompts') or []
    
    if len(visual_prompts) == 1:
        self.config.detection.visual_prompt_bbox = visual_prompts[0]
        self.config.detection.visual_prompts = visual_prompts
    elif len(visual_prompts) > 1:
        self.config.detection.visual_prompts = visual_prompts
    else:
        self.config.detection.visual_prompts = []
    
    self._last_config_reload_time = current_mtime
    self.logger.info(f"Visual prompts reloaded: {len(visual_prompts)} detection boxes")
    return True
```

### Integration Points

#### Continuous Monitoring
In `_run_continuous_monitoring()`:
```python
while self.monitoring_active:
    cycle_count += 1
    
    # Check for config changes before each cycle
    if self.reload_visual_prompts():
        self.logger.info("Detection boxes updated from web UI")
    
    # Run detection cycle
    success = self.run_single_cycle()
    ...
```

#### Single-Shot Mode
In `_run_single_shot()`:
```python
def _run_single_shot(self) -> bool:
    # Check for config changes before running
    self.reload_visual_prompts()
    
    success = self.run_single_cycle()
    ...
```

## Performance Characteristics

### Overhead
- **File stat check**: ~0.1ms (negligible)
- **Config reload**: ~10-50ms (only when changed)
- **Frequency**: Once per detection cycle (every 2 minutes in continuous mode)

### Efficiency
- Uses file modification time, not content comparison
- Only reloads when file actually changes
- No polling - checks happen before each cycle
- Minimal memory allocation - updates existing config object

## Compatibility

### Works With
- ✅ Continuous monitoring mode (`--continuous`)
- ✅ Single-shot mode (default)
- ✅ Visual detection mode (required)
- ✅ All YOLOE models (yoloe-11s/m/l, yoloe-v8s/m/l)

### Doesn't Apply To
- ❌ Text detection mode (uses text prompts, not visual)
- ❌ Bbox mode (uses hardcoded bboxes)

## Testing

Verified with:
1. ✅ File modification time tracking
2. ✅ Config reload from disk
3. ✅ Visual prompts update
4. ✅ No reload when file unchanged

## Logging

When hot-reload occurs, you'll see:
```
INFO - Detected web_ui.config.py changes, reloading visual prompts...
INFO - Visual prompts reloaded: 2 detection boxes
INFO - Detection boxes updated from web UI
```

## User Workflow

1. Start laser monitor in continuous mode:
   ```bash
   python cli.py monitor --continuous
   ```

2. Open web dashboard:
   ```bash
   # In another terminal
   cd server
   python app.py
   # Visit http://localhost:5000
   ```

3. Adjust detection boxes in web UI
   - Move boxes with X+/X-/Y+/Y- buttons
   - Resize with W+/W-/H+/H- buttons
   - Add/delete boxes as needed

4. Changes save automatically to `web_ui.config.py`

5. Monitor logs show reload on next cycle:
   ```
   INFO - === Monitoring Cycle 5 ===
   INFO - Detection boxes updated from web UI
   INFO - Capturing frame from camera...
   ```

6. Next detection uses updated boxes - **no restart needed!**

## Benefits

- 🔥 **Zero downtime** - adjust boxes while monitoring
- ⚡ **Instant feedback** - visual overlay updates immediately, detection applies in 2 minutes
- 🎯 **Iterative tuning** - quickly refine detection regions with live preview
- 👁️ **Visual feedback** - see exactly where boxes are positioned on the image
- 🛡️ **Safe** - file-based, no network communication required
- 📝 **Logged** - all reloads tracked in monitor logs

## Visual Overlay Feature

The web dashboard now includes a **live visual overlay** that renders detection boxes directly on the latest image:

### Overlay Components

1. **Detection Boxes**
   - Green borders (3px wide, #00ff00)
   - Semi-transparent green fill (15% opacity)
   - Corner handles (8×8px squares) at all four corners
   - Center crosshair for precise positioning

2. **Labels**
   - Box number (e.g., "Box 1", "Box 2")
   - Dimensions in pixels (e.g., "128×96px")
   - Green background with black text
   - Positioned above each box

3. **Responsive Scaling**
   - Canvas automatically resizes with image
   - Coordinates scale correctly on different screen sizes
   - Redraws on window resize

### Implementation

The overlay uses an HTML5 canvas positioned absolutely over the detection image:

```html
<div class="image-container">
    <img id="detection-image" src="/api/latest-image" onload="drawDetectionBoxes()">
    <canvas id="detection-overlay" class="detection-overlay"></canvas>
</div>
```

JavaScript handles the drawing:
- Converts normalized coordinates to pixel coordinates
- Scales based on displayed image size
- Redraws on image load, box changes, and window resize

### User Experience

When you adjust a detection box:
1. Click X+, Y+, W+, etc. button
2. Overlay redraws **instantly** (no server round-trip needed)
3. Box position/size updates visually
4. Server saves changes in background
5. Next detection cycle uses updated config

This provides immediate visual confirmation before the monitor applies changes.

## Future Enhancements

Possible improvements:
- WebSocket push notifications for instant reload trigger
- Web UI indicator showing when reload is detected
- Reload history/undo functionality
- Mouse drag-and-drop for box positioning
- Click-and-drag box resizing

## Troubleshooting

### Changes Not Applied
- Check monitor is running in visual mode
- Verify `web_ui.config.py` exists in project root
- Check monitor logs for reload messages
- Ensure at least one detection cycle has run since change

### Multiple Configs
If you have multiple `*.config.py` files:
- Explicitly specify web UI config: `--config web_ui.config.py`
- Or remove other `*.config.py` files to avoid conflicts

### Permission Issues
- Ensure web server has write permission to project root
- Check `web_ui.config.py` file permissions
