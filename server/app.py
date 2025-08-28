#!/usr/bin/env python3
"""
Simple Flask web server for Laser Monitor Dashboard
Serves latest detection image and machine stats with manual refresh
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, send_file
import glob

app = Flask(__name__)

# Path to the laser monitor output directory
OUTPUT_DIR = Path(__file__).parent.parent / "output"
SCREENSHOTS_DIR = OUTPUT_DIR / "screenshots"
HISTORY_FILE = OUTPUT_DIR / "machine_history.json"

@app.route('/')
def dashboard():
    """Main dashboard page"""
    return render_template('dashboard.html')

@app.route('/api/latest-image')
def latest_image():
    """Serve the latest detection image"""
    try:
        # Find the most recent detection image
        image_files = list(SCREENSHOTS_DIR.glob('detection_*.jpg'))
        if not image_files:
            return jsonify({'error': 'No detection images found'}), 404
        
        # Sort by modification time, get the newest
        latest_image = max(image_files, key=lambda f: f.stat().st_mtime)
        return send_file(latest_image, mimetype='image/jpeg')
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats')
def machine_stats():
    """Get current machine statistics and recent history"""
    try:
        stats = {
            'current_status': 'unknown',
            'last_update': None,
            'total_machines': 0,
            'active_machines': 0,
            'inactive_machines': 0,
            'hourly_activity': [],
            'error': None
        }
        
        # Check if history file exists
        if not HISTORY_FILE.exists():
            stats['error'] = 'No machine history found'
            return jsonify(stats)
        
        # Load machine history
        with open(HISTORY_FILE, 'r') as f:
            history_data = json.load(f)
        
        if not history_data:
            stats['error'] = 'Empty machine history'
            return jsonify(stats)
        
        # Calculate current status from all machines
        active_count = 0
        inactive_count = 0
        latest_timestamp = None
        
        for machine_id, machine_data in history_data.items():
            entries = machine_data.get('entries', [])
            if entries:
                # Get the latest entry for this machine
                latest_entry = max(entries, key=lambda e: e['timestamp'])
                entry_time = datetime.fromisoformat(latest_entry['timestamp'])
                
                if latest_timestamp is None or entry_time > latest_timestamp:
                    latest_timestamp = entry_time
                
                # Count active/inactive machines
                if latest_entry['status'] == 'active':
                    active_count += 1
                else:
                    inactive_count += 1
        
        # Calculate true uptime for the last hour
        overall_uptime, machine_uptimes = calculate_overall_uptime(history_data, hours_back=1)
        
        stats.update({
            'total_machines': len(history_data),
            'active_machines': active_count,
            'inactive_machines': inactive_count,
            'last_update': latest_timestamp.isoformat() if latest_timestamp else None,
            'current_status': 'active' if active_count > 0 else 'inactive',
            'overall_uptime_1h': overall_uptime,
            'machine_uptimes_1h': machine_uptimes
        })
        
        # Generate hourly activity data for the last 24 hours (per machine)
        stats['hourly_activity'] = generate_hourly_activity(history_data)
        
        return jsonify(stats)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def calculate_machine_uptime(entries, start_time, end_time):
    """Calculate true uptime percentage for a machine within a time period"""
    if not entries:
        return 0.0
    
    # Filter entries within the time period and sort by timestamp
    period_entries = []
    for entry in entries:
        entry_time = datetime.fromisoformat(entry['timestamp'])
        if start_time <= entry_time <= end_time:
            period_entries.append({
                'timestamp': entry_time,
                'status': entry['status']
            })
    
    if not period_entries:
        return 0.0
    
    period_entries.sort(key=lambda e: e['timestamp'])
    
    # Calculate active time by tracking state transitions
    total_active_seconds = 0
    current_status = period_entries[0]['status']
    last_timestamp = start_time
    
    for entry in period_entries:
        # If we were active, add the time since last timestamp
        if current_status == 'active':
            total_active_seconds += (entry['timestamp'] - last_timestamp).total_seconds()
        
        current_status = entry['status']
        last_timestamp = entry['timestamp']
    
    # Handle the final period until end_time
    if current_status == 'active':
        total_active_seconds += (end_time - last_timestamp).total_seconds()
    
    # Calculate percentage
    total_period_seconds = (end_time - start_time).total_seconds()
    if total_period_seconds == 0:
        return 0.0
    
    return (total_active_seconds / total_period_seconds) * 100

def calculate_overall_uptime(history_data, hours_back=1):
    """Calculate overall uptime and per-machine uptime for the last N hours"""
    now = datetime.now()
    start_time = now - timedelta(hours=hours_back)
    
    machine_uptimes = {}
    total_uptime_sum = 0
    machine_count = 0
    
    for machine_id, machine_data in history_data.items():
        entries = machine_data.get('entries', [])
        uptime = calculate_machine_uptime(entries, start_time, now)
        machine_uptimes[machine_id] = round(uptime, 1)
        total_uptime_sum += uptime
        machine_count += 1
    
    overall_uptime = round(total_uptime_sum / machine_count, 1) if machine_count > 0 else 0.0
    
    return overall_uptime, machine_uptimes

def generate_hourly_activity(history_data):
    """Generate hourly activity data for the last 24 hours per machine"""
    now = datetime.now()
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    machine_hourly_data = {}
    
    # Initialize data structure for each machine
    for machine_id in history_data.keys():
        machine_hourly_data[machine_id] = []
    
    # Create 24 hourly buckets aligned to actual hour boundaries
    for i in range(24):
        hour_start = current_hour - timedelta(hours=23-i)
        # For the current hour (i == 23), use current time as end
        if i == 23:
            hour_end = now
        else:
            hour_end = hour_start + timedelta(hours=1)
        
        # Calculate uptime for each machine for this hour
        for machine_id, machine_data in history_data.items():
            entries = machine_data.get('entries', [])
            uptime = calculate_machine_uptime(entries, hour_start, hour_end)
            
            machine_hourly_data[machine_id].append({
                'hour': hour_start.strftime('%H:00'),
                'activity_percentage': round(uptime, 1),
                'active_minutes': round((uptime / 100) * 60, 1),
                'is_current_hour': i == 23
            })
    
    return machine_hourly_data

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    templates_dir = Path(__file__).parent / 'templates'
    templates_dir.mkdir(exist_ok=True)
    
    print(f"Starting Laser Monitor Dashboard Server...")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Screenshots directory: {SCREENSHOTS_DIR}")
    print(f"History file: {HISTORY_FILE}")
    print(f"Dashboard will be available at: http://localhost:5000")
    
    app.run(debug=True, host='0.0.0.0', port=5000)