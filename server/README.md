# Laser Monitor Dashboard Server

A simple web dashboard for monitoring laser cutter status with detection images and activity charts.

## Features

- 📸 **Latest Detection Image** - Shows the most recent detection screenshot
- 📊 **Machine Statistics** - Current status, active/inactive machine counts
- 📈 **24-Hour Activity Chart** - Bar chart showing machine activity over time
- 🔄 **Manual Refresh** - Click refresh button to update data

## Quick Start

```bash
# Start the server
./start_server.sh

# Or run directly
cd /home/zarred/dev/laser_monitor
nix develop -c python server/app.py
```

The dashboard will be available at: **http://localhost:5000**

## API Endpoints

- `GET /` - Main dashboard page
- `GET /api/latest-image` - Serves the latest detection image
- `GET /api/stats` - Returns machine statistics and activity data as JSON

## Requirements

- Flask 3.0+
- Access to laser monitor output directory
- Detection images in `output/screenshots/`
- Machine history in `output/machine_history.json`

## Dashboard Features

### Current Status
- Shows overall machine status (Active/Inactive/Unknown)
- Last update timestamp
- Manual refresh button

### Statistics Grid
- Total machines monitored
- Currently active machines  
- Currently inactive machines
- Overall uptime percentage

### Activity Chart
- 24-hour bar chart showing activity percentages
- Hourly breakdown of machine usage
- Visual representation of operational patterns

## Technical Details

- **Static refresh only** - No auto-refresh, manual button click required
- **Desktop optimized** - Designed for full desktop viewing
- **Simple architecture** - Flask backend, vanilla JS frontend
- **Chart.js integration** - For activity visualization

## Data Sources

The dashboard reads from:
- `output/screenshots/detection_*.jpg` - Latest detection images
- `output/machine_history.json` - Machine status history and timestamps

## Troubleshooting

**No images showing:**
- Check that detection images exist in `output/screenshots/`
- Verify image files follow naming pattern `detection_YYYYMMDD_HHMMSS.jpg`

**No statistics:**
- Ensure `output/machine_history.json` exists and contains valid data
- Check that laser monitor has been running and generating history

**Server won't start:**
- Verify Flask is installed: `nix develop -c python -c "import flask"`
- Check that port 5000 is available