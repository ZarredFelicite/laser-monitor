---
applyTo: '**'
---

# AGENTS.md — Instructions & README summary for agents

## Update (2025-08-29 - Machine History Retention Policy)

- Changed machine history retention from "last 20/50 entries" to "last 7 days" time-based retention.
- Updated MachineHistory.to_dict() to filter entries by date instead of entry count.
- Added automatic cleanup of old history entries when adding new entries.
- Modified load_machine_history() to only load entries from the last 7 days.
- Added cleanup_machine_history() method to the cleanup process.
- History cleanup now runs during regular file cleanup operations.

## Update (2025-08-26 - Configuration System Improvements)

- Removed automatic loading of example_config.py - system now uses built-in defaults when no config is specified.
- ConfigManager now only loads explicit config files or auto-detected visual prompt configs.
- When no config is specified, uses the production-ready defaults from config.py dataclasses.
- Updated CLI help text to clarify that built-in defaults are used when no config is provided.

## Update (2025-08-26 - Twilio SMS Integration)

- Added Twilio SMS alert functionality alongside existing email alerts.
- New SMS configuration options in AlertConfig: sms_alerts, sms_recipients, twilio_account_sid, twilio_auth_token, twilio_from_number.
- SMS alerts follow same state transition logic as email alerts (only notify once per inactive cycle).
- Added SMSAlertManager class with same interface as EmailAlertManager.
- New CLI flag: --test-sms to test SMS functionality.
- Environment variables: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER.
- SMS recipients should be in E.164 format (e.g., +61412345678).
- Added twilio>=8.0.0 to requirements.txt.
- Updated example configs with SMS settings (disabled by default).

## Update (2025-08-21 - Machine Status Logic)

- Updated indicator detection logic: red=working, orange=machine_on, both=active state.
- New class names: machine_active (both red+orange), machine_working_only (red only), machine_on_only (orange only), machine_off (neither).
- New status logic: only "machine_active" (both red+orange) results in laser_status="active"; all other states are "inactive".
- Updated decision path logging: working(ratio) for red, machine_on(ratio) for orange.
- Active state requires BOTH red (working) AND orange (machine on) to be detected.
- Inactive state occurs when: both off, red off (not working), or orange off (machine not on).

## Update (2025-08-21 - Dependency Gating)

- Gated AI/ML dependencies (ultralytics, clip, huggingface-hub, ftfy, regex, wcwidth) into optional extras.
- Added optional extras group [project.optional-dependencies.ai] in pyproject.toml; core install now supports bbox heuristic mode only.
- Removed top-level ultralytics import from laser_monitor.py; lazy-loaded only for text/visual modes.
- setup_yoloe.py now performs lazy imports and reports missing AI deps without exiting non-AI workflows.
- cli.py messages updated to clarify ultralytics is only required for AI detection modes; bbox mode remains functional without it.
- requirements.txt trimmed to minimal core; AI stack commented with instructions to enable.
- Validation now reports missing ultralytics as informational (only affects AI modes).

## Update (2025-08-21)

- Indicator composite mode color change: middle segment light reclassified from green to orange.
- Added configurable hue ranges in DetectionConfig (red_hue_low_max, red_hue_high_min, orange_hue_min, orange_hue_max).
- Renamed config field green_activation_ratio -> orange_activation_ratio (green_activation_ratio retained for backward compatibility; will map to orange).
- Updated class names: green_active -> orange_active, red_green_active -> red_orange_active, green_light -> orange_light.
- Extras now emit orange_ratio (legacy green_ratio key preserved for consumers not yet updated).
- Non-indicator heuristic path now uses orange hue band (approx 15–35) instead of prior green band (40–80).
- Debug logging emits red_ratio and orange_ratio.

## Update (2025-08-20)

- Added indicator composite mode extras: DetectionResult now carries an `extras` dict (red_ratio, green_ratio, decision_path, basic metrics) serialized into detection JSON.
- Fixed cv2 local import scoping bug inside `_analyze_roi` that previously triggered `cannot access local variable 'cv2'` errors.
- Enhanced ROI debug logging with per-bbox normalization, clamping notice, ratios, and decision path.
- Added forced bbox detection debug message and richer detection fabrication path.
- Introduced dynamic confidence derivation from activation ratios in indicator mode.


## Update (2025-08-17)

### Visual Prompt Selection Revision (click-based)
- Changed interactive visual prompt ROI selection from drag-release to click-start, click-end, ENTER to save.
- Added R key to reset during selection; third click restarts selection from new start point; ESC cancels.
- Invalid zero-area selection now shows on-screen warning (2s) instead of silently ignoring.
- Normalizes inverted corner clicks automatically (no need to drag top-left to bottom-right).
- Removed persistent drawing of saved visual prompt ROI on main display (reduces clutter); replaced with optional top-right thumbnail (80px tall) only when in visual mode.
- Detection box overlay now updates every frame using last detection cycle results; boxes disappear immediately after an empty cycle (no stale persistence).
- Window title updated: 'Select Visual Prompt (click start, click end, ENTER save)'.
- Interactive runtime visual prompt detection now uses YOLOE visual_prompts (bboxes+cls) with YOLOEVPSegPredictor; refer_image argument removed from live selection path.

Added documentation for EnhancedLaserMonitor runtime features:
- Environment activation: run `nix develop` (or `nix develop .`) first to enter the dev shell with all Python dependencies (ultralytics, opencv-python, etc.) available. Outside the shell, imports may fail.
- Core runtime enhancements:
  - Interactive detection mode cycling (text, visual, prompt_free) with key `p`.
  - Interactive visual prompt ROI selection with key `v` (saves cropped prompt image to output/ with timestamp and switches to visual mode).
  - Dynamic confidence threshold adjustment with `+` / `-` (increments 0.05, clamped 0.01–0.99).
  - On-demand screenshot capture with `s` (if output.save_screenshots enabled).
  - Graceful quit with `q` or Ctrl+C (session summary always written).
  - Prompt-free detection path (`prompt_free`) using base model classes when no text or visual prompt is desired.
  - Performance metrics: rolling average FPS and average detection latency (ms) over recent frames (overlay bottom-left if display.show_fps true).
  - Periodic detection JSON saving (per second) to output/detections/ when output.save_detections is enabled.
  - Session summary (session_summary.json) written at shutdown containing duration, frames processed, counts, avg_fps, avg_detection_ms, status_counts.
  - Zone overlays (enabled zones outlined) and ignore-zone filtering for detections.
  - AlertManager scaffold with cooldown logic—currently logs WARNING messages (extend here for sound/webhook/email integrations).
  - Headless mode support when display.display_video=false (no OpenCV windows; visual prompt selection disabled gracefully).
- Keyboard shortcuts summary (active when display window visible):
  - q : quit monitoring
  - v : select / redefine a visual prompt ROI (switches detection mode to visual)
  - p : cycle detection modes (text -> visual -> prompt_free -> ...)
  - + / - : increase / decrease confidence threshold
  - s : save screenshot (if enabled)
- File outputs:
  - Visual prompt crops: output/visual_prompt_YYYYMMDD_HHMMSS.jpg
  - Screenshots: output/screenshot_YYYYMMDD_HHMMSS.jpg
  - Detections: output/detections/detections_YYYYMMDD_HHMMSS.json
  - Session summary: session_summary.json in project root

Usage quick start (updated):
1. Enter environment: `nix develop`   (or ensure a venv with requirements.txt & ultralytics>=8.3.0)
2. Run setup (optional interactive): `python cli.py setup --interactive`
3. Start monitoring: `python cli.py monitor --config example_config.json`
4. Use runtime keys (q, v, p, +, -, s) as needed.

For headless operation (e.g., systemd service / remote): set in config:
```
"display": { "display_video": false }
```
Ensure detection.mode preset (text / visual / prompt_free) and (for visual) a valid detection.visual_prompt_path is set beforehand.


Purpose: Provide concise guidance for automated agents and contributors about the project, how to use it, and where to find key resources locally (so agents avoid unrestricted web fetches).

Summary of README.md (Laser Monitor)

- Project: Laser Monitor — real-time laser cutter monitoring system using YOLOE for detection and instance segmentation.
- Core features: real-time laser indicator detection, multi-modal prompting (text, visual, prompt-free), zone-based monitoring, configurable alerts, session logging, and performance monitoring (FPS/timing).
- Quick start: install ultralytics>=8.3.0 and requirements.txt or use `nix develop`; run `python cli.py setup --interactive` and `python cli.py monitor`.
- Models supported: yoloe-11s/m/l (YOLO11-based), yoloe-v8s/m/l (YOLOv8-based), plus prompt-free variants. Models auto-download on first use.
- Detection modes: text prompts (default), visual prompts (intra-image or refer_image), and prompt-free built-in vocabulary.
- Configuration: JSON/YAML configs control camera, detection, zones, alerts, and performance. Example config snippets reside in README.md.
- Output & logs: output/ contains detections, screenshots, and visual_prompt templates; laser_monitor.log and session_summary.json track activity.
- Troubleshooting: camera tests, model download help, low-accuracy mitigations (lower confidence, visual prompts), and performance tips (frame skipping, smaller models, GPU).
- Development: add custom classes via config, create visual prompts, implement alert handlers, and profile with debug logging.

Important local files

- cli.py — main command-line interface
- enhanced_monitor.py — core monitoring logic
- config_manager.py — config utilities
- setup_yoloe.py — model setup/download helpers
- visual_prompt_selector.py — visual prompt selection tool
- pretrain/ — local model storage (pretrain/*.pt)
- output/ — runtime outputs (detections, screenshots, visual_prompts)

Agent guidance / rules

- Only operate inside the repository root (/home/zarred/dev/laser_monitor) unless explicitly instructed otherwise.
- Prefer local files over web fetches. Use yoloe-docs.md for YOLOE reference instead of fetching docs each time.
- If a required web fetch is necessary (e.g., downloading model weights), confirm with the user or use the provided `setup_yoloe.py` helper which handles downloads.
- Do not run wide filesystem searches or access user home files outside this repo.
- When making code edits:
  - Read files before modifying them.
  - Create small, testable changes and run local tests if possible.
  - If changes require environment variables, create a `.env.example` with placeholders rather than real secrets.
- If you update any local docs or files, add a short summary of changes at the top of AGENTS.md and notify the user.

If you need the README expanded into developer docs or converted into issue/task templates, ask and I will generate them here locally.
