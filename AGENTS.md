# AGENTS.md — Laser Monitor Project Reference

## Project Overview
Real-time laser cutter monitoring system using indicator light detection (brightness or color-based).

## Current Features
- **Detection modes**: brightness threshold (default) or color-based (red/orange)
- **Brightness detection**: analyzes top/middle thirds vs bottom baseline, 92.9% success rate (optimized)
- **Color detection**: red=working, orange=machine_on, both=active (41% success rate)
- **Alerts**: email + SMS (Twilio) on state transitions
  - 15-minute startup grace period (no alerts on program start for pre-existing inactivity)
  - Pause/resume via web dashboard
- **Web Dashboard**: Flask server with live stats, 7-day activity charts, settings management
- **Config**: .env for recipients/credentials, Python dataclass configs
- **History**: 7-day retention, auto-cleanup
- **Optimization**: grid search tool for finding optimal threshold ratios

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
- `output/notification_settings.json` — pause state persistence

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
