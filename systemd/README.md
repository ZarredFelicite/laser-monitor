# Laser Monitor systemd Services

This directory contains systemd service files to run the Laser Monitor system as background services with automatic restart capabilities.

## 📁 Files

- **`laser-monitor.service`** - Main detection system service
- **`laser-monitor-server.service`** - Web dashboard server service  
- **`laser-monitor.target`** - Target to manage both services together
- **`install-services.sh`** - Installation script
- **`manage-services.sh`** - Service management script

## 🚀 Quick Setup

```bash
# Install the services
cd /home/hilton/laser-monitor/systemd
./install-services.sh

# Start both services
./manage-services.sh start

# Check status
./manage-services.sh status
```

## 📋 Service Details

### laser-monitor.service
- **Command**: `systemd/start-laser-monitor.sh` (wrapper script)
- **Actual**: `python cli.py monitor --config config/test.config.py --detection-mode bbox --camera-type pi -v --continuous`
- **User**: hilton
- **Restart**: Always (10 second delay)
- **Resources**: 2GB RAM max, 80% CPU max
- **Security**: Relaxed for Pi camera access

### laser-monitor-server.service  
- **Command**: `systemd/start-server.sh` (wrapper script)
- **Actual**: `python server/app.py`
- **User**: hilton
- **Port**: 5000
- **Restart**: Always (5 second delay)
- **Resources**: 512MB RAM max, 50% CPU max
- **Dependencies**: Starts after laser-monitor.service

### laser-monitor.target
- **Purpose**: Manages both services as a unit
- **Behavior**: Start/stop both services together

## 🔧 Management Commands

```bash
# Service control
./manage-services.sh start      # Start both services
./manage-services.sh stop       # Stop both services  
./manage-services.sh restart    # Restart both services
./manage-services.sh status     # Show service status

# Logging
./manage-services.sh logs           # Follow logs for both services
./manage-services.sh logs-monitor   # Follow only monitor logs
./manage-services.sh logs-server    # Follow only server logs

# Boot behavior
./manage-services.sh enable     # Start services on boot
./manage-services.sh disable    # Don't start on boot
```

## 🔍 Manual systemctl Commands

```bash
# Target control (both services)
sudo systemctl start laser-monitor.target
sudo systemctl stop laser-monitor.target
sudo systemctl status laser-monitor.target

# Individual service control
sudo systemctl start laser-monitor.service
sudo systemctl start laser-monitor-server.service

# View logs
sudo journalctl -u laser-monitor.service -f
sudo journalctl -u laser-monitor-server.service -f
sudo journalctl -u laser-monitor.target
```

## ⚙️ Configuration

### Environment Variables
Both services run with:
- **PATH**: Standard system paths (/usr/bin:/bin:/usr/local/bin)
- **PYTHONPATH**: Set to project directory
- **User**: hilton (not root for security)
- **Package Manager**: uv (replaces nix for Python dependencies)

### File Permissions
Services have restricted access:
- **Read-only**: Home directory and system files
- **Read-write**: Only `output/` directory and log files
- **Device access**: Camera devices (`/dev/video*`)

### Resource Limits
- **Monitor service**: 2GB RAM, 80% CPU
- **Server service**: 512MB RAM, 50% CPU

## 🛡️ Security Features

- **NoNewPrivileges**: Prevents privilege escalation
- **PrivateTmp**: Isolated temporary directories
- **ProtectSystem**: Read-only system directories
- **ProtectHome**: Read-only home directory access
- **Device restrictions**: Only camera access allowed

## 🔧 Troubleshooting

### Services won't start
```bash
# Check service status
sudo systemctl status laser-monitor.service
sudo systemctl status laser-monitor-server.service

# View detailed logs
sudo journalctl -u laser-monitor.service -n 50
sudo journalctl -u laser-monitor-server.service -n 50
```

### Common issues
1. **Config file missing**: Ensure `config/test.config.py` exists
2. **Camera permissions**: User 'zarred' needs video group access
3. **Nix environment**: Services use hardcoded nix paths
4. **Port conflicts**: Web server uses port 5000

### Camera permissions
```bash
# Add user to required groups for Pi camera
sudo usermod -a -G video,render,gpio hilton

# Check camera devices
ls -la /dev/video*

# Test camera access
v4l2-ctl --list-devices
```

### Update paths for deployment system
Before deploying, verify and update paths in service files:
```bash
# Find nix binary location on target system
which nix

# Common nix paths:
# /nix/var/nix/profiles/default/bin/nix  (multi-user install)
# /run/current-system/sw/bin/nix         (NixOS)
# ~/.nix-profile/bin/nix                 (single-user install)

# Update service files with correct paths
sudo nano /etc/systemd/system/laser-monitor.service
sudo nano /etc/systemd/system/laser-monitor-server.service

# Reload after changes
sudo systemctl daemon-reload
sudo systemctl restart laser-monitor.target
```

## 📊 Monitoring

### Service health
```bash
# Check if services are running
systemctl is-active laser-monitor.target

# Check service uptime
systemctl show laser-monitor.service --property=ActiveEnterTimestamp

# View restart count
systemctl show laser-monitor.service --property=NRestarts
```

### Log monitoring
```bash
# Real-time log monitoring
sudo journalctl -u laser-monitor.service -f

# Log analysis
sudo journalctl -u laser-monitor.service --since "1 hour ago"
sudo journalctl -u laser-monitor.service --grep "ERROR"
```

## 🔄 Updates

When updating the laser monitor code:
```bash
# Stop services
./manage-services.sh stop

# Update code (git pull, etc.)
git pull

# Restart services  
./manage-services.sh start
```

For service file changes:
```bash
# Reinstall services
./install-services.sh

# Or manually reload
sudo systemctl daemon-reload
sudo systemctl restart laser-monitor.target
```
