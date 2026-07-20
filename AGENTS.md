# AGENTS.md — Laser Monitor Project Reference

## Project Overview
Real-time laser cutter monitoring system using indicator light detection (brightness or color-based).

## Recent Updates

### 2026-07-21: Daylight red-core tuning

- Lowered the red chroma floor for top lamps only when strong brightness and local-contrast safeguards already establish an emitting core.
- Added a live daylight main-stack regression fixture where both lamps are illuminated despite depressed brightness ratios.
- Burst-confirmed active transitions now publish immediately; inactive transitions retain two-cycle debounce to prevent transient missed lamps from triggering inactivity.

### 2026-07-20: Nighttime small-stack tuning

- Tightened and vertically extended the second machine ROI so its red, amber, and dark reference thirds align with the physical stack light.
- Relaxed the strong amber chroma floor only when bright-core and local-contrast safeguards are also satisfied.
- Added a cropped live nighttime regression fixture covering both illuminated segments on the distant stack.

### 2026-07-20: Picamera2 capture timeout recovery

- Persistent Picamera2 captures now time out after 10 seconds instead of blocking the monitor indefinitely after a camera frontend failure.
- Timed-out Picamera2 jobs are cancelled/flushed and the stream is stopped so the next cycle can restart it safely.
- Added regression coverage for capture timeout cleanup and restart state.

### 2026-07-20: Cohesive dashboard settings drawer

- Moved notification settings and all detection-box controls into the existing Settings modal, hidden by default while status, camera, statistics, and activity content remain visible.
- Added responsive full-screen mobile treatment, backdrop/Escape close behavior, focus restoration/trapping, and dialog/button ARIA semantics without changing settings or detection-box APIs.

### 2026-07-20: Drift-Tolerant Indicator Detection

- Added bounded global/local ROI registration against a raw reference frame.
- Added local background-normalized light classification and marginal-evidence rejection.
- Added three-frame burst voting, temporal state hysteresis, and explicit unknown health states.
- Unknown observations preserve the last trusted state and cannot trigger inactivity alerts.
- Added atomic history/config writes and strict drift/lighting regression tests.

### 2026-07-20: Persistent Raspberry Pi Camera Backend

- Added a persistent Picamera2 backend that opens and configures libcamera once, then reuses one capture stream.
- Uses one camera buffer to reduce CMA pressure and avoids launching `rpicam-still` every detection cycle.
- Keeps `rpicam-still` as a fallback, now with explicit camera ID selection and one buffer.
- Raspberry Pi camera ID now defaults to `0`; explicit Pi requests never silently switch to USB.
- Added camera lifecycle, buffer, fallback, and configuration tests in `tests/test_camera_manager.py`.

### 2025-11-12: Web UI Detection Box Controls

- Added web dashboard UI for managing detection boxes (visual prompts) at `server/templates/dashboard.html`.
- Detection box controls allow real-time adjustment of position (X+/X-/Y+/Y-) and size (W+/W-/H+/H-) with 10px increments.
- **Live visual overlay**: Detection boxes rendered in real-time on the latest image with green borders, semi-transparent fill, and labels.
  - Canvas overlay shows box position, dimensions, corner handles, and center crosshair
  - Instant visual feedback when adjusting boxes - no need to wait for next detection
  - Dimensions displayed on each box (e.g., "128×96px")
  - Boxes numbered for easy identification
- Each box displays coordinates and has a delete button with confirmation.
- New Flask API endpoints: GET/POST `/api/detection-boxes`, DELETE `/api/detection-boxes/<index>`.
- **Configuration persistence**: Web UI saves to `web_ui.config.py` in Python format compatible with ConfigManager.
- `web_ui.config.py` follows same format as `visual_prompt_selector.py` output (has `refer_image`, `visual_prompts`, `image_dimensions`, `metadata`).
- ConfigManager auto-detects `web_ui.config.py` via `_find_visual_prompt_config()` pattern matching (`*.config.py`).
- Config is loaded using `create_config_with_visual_prompts()` which sets `detection.mode = "visual"` and populates `detection.visual_prompts`.
- **Hot-reload**: Changes take effect on the NEXT image/detection cycle - no monitor restart required!
  - `LaserMonitor.reload_visual_prompts()` checks `web_ui.config.py` modification time before each cycle
  - Automatically reloads visual prompts when web UI changes are detected
  - Works in both continuous monitoring and single-shot modes
- Responsive layout: 2-column on desktop (Position|Size), single column on mobile/tall screens.
- `refer_image` auto-set to latest detection screenshot in `output/screenshots/detection_*.jpg`.
- **STATUS**: Fully integrated and verified (see DETECTION_BOX_INTEGRATION_COMPLETE.md)

## Quick Start
```bash
nix develop  # or venv with requirements.txt
python cli.py setup --interactive  # optional
python cli.py monitor --config example_brightness_config.py

# Web Dashboard (optional)
cd server && python app.py  # http://localhost:5000
```

## Key Files
- `cli.py` — CLI entry point
- `laser_monitor.py` — core detection logic
- `config/config.py` — configuration dataclasses (default ratios: [1.7, 2.2])
- `example_brightness_config.py` — brightness mode example
- `optimize_brightness_thresholds.py` — grid search for optimal ratios
- `tests/test_detections.py` — pytest tests
- `.env.example` — alert recipients/credentials template
- `server/app.py` — Flask web dashboard backend
- `server/templates/dashboard.html` — Web UI with settings
- `server/notification_settings.json` — pause state persistence (writable)

## Environment Variables
- `LASER_MONITOR_EMAIL_RECIPIENTS` — CSV/space/semicolon separated
- `LASER_MONITOR_SMS_RECIPIENTS` — E.164 format, CSV/space/semicolon
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`

## Configuration
- Brightness mode: `use_brightness_threshold=True`, `brightness_threshold_ratios` (per-ROI, per-section `[[top, mid], ...]`)
  - Default: `[[1.7, 2.2]]` (optimized via grid search for 92.9% accuracy)
  - Format: `[[top_ratio, mid_ratio], ...]` for each visual_prompt ROI
  - Compares average brightness to `bottom_brightness * ratio`
- Color mode: `red_hue_low_max`, `red_hue_high_min`, `orange_hue_min`, `orange_hue_max`, `orange_activation_ratio`
- Uses built-in defaults when no config specified

## Testing & Optimization
```bash
# Run tests
pytest tests/test_detections.py
python test_brightness_detection.py
python run_brightness_tests.py

# Optimize brightness thresholds (grid search)
python optimize_brightness_thresholds.py
# Outputs: optimization_results.json with top configurations
```

## Agent Rules
- Work only in `/home/zarred/dev/laser-monitor`
- Read files before editing
- Test changes locally when possible
- Use `.env.example` for secrets templates
- Update this file with change summaries
