# Laser Monitor

Laser Monitor captures a frame, detects machine status from indicator regions, stores annotated outputs, and optionally serves a web dashboard for box editing and status visibility.

## What This Repo Includes

- `cli.py` command line entrypoint (`setup`, `monitor`, `test`, `config`, `info`)
- `laser_monitor.py` core monitoring/detection logic
- `config/config.py` typed configuration + config loading
- `server/app.py` Flask dashboard backend
- `server/templates/dashboard.html` dashboard UI
- `systemd/` service units + helper scripts for always-on deployments

## Quick Start

### 1) Install dependencies

Preferred (Nix):

```bash
nix develop
```

Python only:

```bash
pip install -r requirements.txt
```

### 2) (Optional) run setup helper

```bash
python cli.py setup --interactive
```

### 3) Run one detection

```bash
python cli.py monitor
```

### 4) Run continuous monitoring

```bash
python cli.py monitor --continuous
```

## Dashboard

Start dashboard server:

```bash
cd server
python app.py
```

Open `http://localhost:5000`.

Dashboard features:

- latest detection image + overlay
- detection box add/move/resize/delete
- adjustable box movement/resize step (px)
- save detection boxes to `web_ui.config.py`
- machine status, uptime, and activity charts
- notification settings (pause + recipients)

## Detection Modes

Set via config or `--detection-mode`:

- `text`: text prompts
- `visual`: visual prompt based
- `bbox`: lightweight region analysis (no heavy model required)

Examples:

```bash
python cli.py monitor --detection-mode bbox
python cli.py monitor --config web_ui.config.py
python cli.py test --camera 0
python cli.py test --image tests/test1.jpg --config tests/test.config.py
```

## Configuration

The app supports Python config files and auto-detects visual prompt configs (`*.config.py`).

Common files:

- `web_ui.config.py` dashboard-managed visual prompts
- `example_brightness_config.py` brightness mode example
- `tests/test.config.py` test fixture config

Validate and inspect:

```bash
python cli.py config --validate web_ui.config.py
python cli.py config --summary web_ui.config.py
```

## Output Layout

Runtime artifacts are written to `output/`:

- `output/screenshots/` annotated frames
- `output/detections/` detection JSON
- `output/machine_history.json` machine history used by dashboard

## Systemd Deployment

The `systemd/` directory contains units and helper scripts:

- `laser-monitor.service`
- `laser-monitor-server.service`
- `laser-monitor.target`
- `install-services.sh`
- `manage-services.sh`

Typical flow:

```bash
cd systemd
./install-services.sh
./manage-services.sh start
./manage-services.sh status
```

## Troubleshooting

- camera check: `python cli.py test --camera 0`
- config check: `python cli.py config --validate <config.py>`
- model check: `python cli.py test --model pretrain/yoloe-11s-seg.pt`
- system info: `python cli.py info`

If detections are off:

- lower confidence threshold
- verify box placement in dashboard
- try `bbox` mode for deterministic ROI behavior

## Notes

- `web_ui.config.py` is expected to change frequently while tuning boxes.
- `server/notification_settings.json` and `output/` data are runtime state and not intended as stable source files.
