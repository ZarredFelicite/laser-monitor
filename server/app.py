#!/usr/bin/env python3
"""
Simple Flask web server for Laser Monitor Dashboard
Serves latest detection image and machine stats with manual refresh
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, send_file, request
import glob
from dotenv import load_dotenv, set_key, find_dotenv

app = Flask(__name__)

# Path to the laser monitor output directory
OUTPUT_DIR = Path(__file__).parent.parent / "output"
SCREENSHOTS_DIR = OUTPUT_DIR / "screenshots"
HISTORY_FILE = OUTPUT_DIR / "machine_history.json"
PROJECT_ROOT = Path(__file__).parent.parent
WEB_UI_CONFIG_FILE = PROJECT_ROOT / "web_ui.config.py"

# Store settings in server directory (writable)
SERVER_DIR = Path(__file__).parent
SETTINGS_FILE = SERVER_DIR / "notification_settings.json"
ENV_FILE = Path(__file__).parent.parent / ".env"

@app.route('/')
def dashboard():
    """Main dashboard page"""
    return render_template('dashboard.html')

@app.route('/api/images')
def get_images():
    """Get list of available images"""
    try:
        image_files = list(SCREENSHOTS_DIR.glob('detection_*.jpg'))
        if not image_files:
            return jsonify({'images': [], 'total': 0})
        
        # Sort by modification time (newest first), limit to last 15
        image_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        image_files = image_files[:15]
        
        images = []
        for img in image_files:
            images.append({
                'filename': img.name,
                'timestamp': datetime.fromtimestamp(img.stat().st_mtime).isoformat(),
                'url': f'/api/image/{img.name}'
            })
        
        return jsonify({'images': images, 'total': len(images)})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/image/<filename>')
def get_image(filename):
    """Serve a specific detection image by filename"""
    try:
        image_path = SCREENSHOTS_DIR / filename
        if not image_path.exists():
            return jsonify({'error': 'Image not found'}), 404
        
        return send_file(image_path, mimetype='image/jpeg')
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/latest-image')
def latest_image():
    """Serve the latest detection image (legacy endpoint)"""
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
    """Generate hourly activity data for the last 7 days per machine"""
    now = datetime.now()
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    machine_hourly_data = {}
    
    # Initialize data structure for each machine
    for machine_id in history_data.keys():
        machine_hourly_data[machine_id] = []
    
    # Create 168 hourly buckets (7 days * 24 hours)
    for i in range(168):
        hour_start = current_hour - timedelta(hours=167-i)
        # For the current hour (i == 167), use current time as end
        if i == 167:
            hour_end = now
        else:
            hour_end = hour_start + timedelta(hours=1)
        
        # Calculate uptime for each machine for this hour
        for machine_id, machine_data in history_data.items():
            entries = machine_data.get('entries', [])
            uptime = calculate_machine_uptime(entries, hour_start, hour_end)
            
            machine_hourly_data[machine_id].append({
                'hour': hour_start.strftime('%m/%d %H:00'),
                'activity_percentage': round(uptime, 1),
                'active_minutes': round((uptime / 100) * 60, 1),
                'is_current_hour': i == 167
            })
    
    return machine_hourly_data

def load_web_ui_config():
    """Load detection boxes from web_ui.config.py"""
    if not WEB_UI_CONFIG_FILE.exists():
        return {'boxes': [], 'refer_image': None, 'image_dimensions': [1920, 1080]}
    
    try:
        import importlib.util
        import sys
        
        spec = importlib.util.spec_from_file_location("web_ui_config", WEB_UI_CONFIG_FILE)
        if spec is None or spec.loader is None:
            return {'boxes': [], 'refer_image': None, 'image_dimensions': [1920, 1080]}
        
        module = importlib.util.module_from_spec(spec)
        sys.modules["web_ui_config"] = module
        spec.loader.exec_module(module)
        
        normalized_boxes = getattr(module, 'visual_prompts', [])
        refer_image = getattr(module, 'refer_image', None)
        image_dimensions_dict = getattr(module, 'image_dimensions', {'width': 1920, 'height': 1080})
        
        if isinstance(image_dimensions_dict, dict):
            image_dimensions = [image_dimensions_dict.get('width', 1920), image_dimensions_dict.get('height', 1080)]
        else:
            image_dimensions = [1920, 1080]
        
        # Convert normalized coordinates (0-1) to pixel coordinates
        pixel_boxes = []
        for box in normalized_boxes:
            # Check if box is already in pixel format (values > 1) or normalized (values 0-1)
            if all(coord <= 1.0 for coord in box):
                # Normalized format - convert to pixels
                pixel_box = [
                    box[0] * image_dimensions[0],  # x1
                    box[1] * image_dimensions[1],  # y1
                    box[2] * image_dimensions[0],  # x2
                    box[3] * image_dimensions[1]   # y2
                ]
                pixel_boxes.append(pixel_box)
            else:
                # Already in pixel format
                pixel_boxes.append(box)
        
        return {'boxes': pixel_boxes, 'refer_image': refer_image, 'image_dimensions': image_dimensions}
    
    except Exception as e:
        print(f"Error loading web_ui config: {e}")
        return {'boxes': [], 'refer_image': None, 'image_dimensions': [1920, 1080]}

def save_web_ui_config(boxes, refer_image=None, image_dimensions=None):
    """Save detection boxes to web_ui.config.py in the format expected by ConfigManager"""
    if image_dimensions is None:
        image_dimensions = [1920, 1080]
    
    # Determine refer_image - try to find the latest screenshot if not provided
    if refer_image is None:
        try:
            image_files = list(SCREENSHOTS_DIR.glob('detection_*.jpg'))
            if image_files:
                latest_image = max(image_files, key=lambda f: f.stat().st_mtime)
                refer_image = str(latest_image.absolute())
            else:
                refer_image = ""
        except:
            refer_image = ""
    
    # Convert pixel coordinates to normalized coordinates (0-1) for storage
    normalized_boxes = []
    for box in boxes:
        # Check if box is already normalized or in pixel format
        if all(coord <= 1.0 for coord in box):
            # Already normalized
            normalized_boxes.append(box)
        else:
            # Convert from pixels to normalized
            normalized_box = [
                box[0] / image_dimensions[0],  # x1
                box[1] / image_dimensions[1],  # y1
                box[2] / image_dimensions[0],  # x2
                box[3] / image_dimensions[1]   # y2
            ]
            normalized_boxes.append(normalized_box)
    
    # Generate Python config content
    config_content = f'''#!/usr/bin/env python3
"""
Visual Prompts Configuration
Generated by Laser Monitor Web UI
Auto-loaded by ConfigManager when monitoring starts

This file follows the same format as configs generated by visual_prompt_selector.py
and is compatible with create_config_with_visual_prompts().
"""

# Reference image path (latest detection screenshot)
refer_image = r"{refer_image}"

# Visual prompt bounding boxes (normalized coordinates: x1, y1, x2, y2)
visual_prompts = {normalized_boxes!r}

# Image dimensions (for reference)
image_dimensions = {{
    "width": {image_dimensions[0]},
    "height": {image_dimensions[1]}
}}

# Metadata
metadata = {{
    "created_with": "web_ui_dashboard",
    "num_prompts": {len(boxes)},
    "last_modified": "{datetime.now().isoformat()}"
}}
'''
    
    try:
        with open(WEB_UI_CONFIG_FILE, 'w') as f:
            f.write(config_content)
        return True
    except Exception as e:
        print(f"Error saving web_ui config: {e}")
        return False

@app.route('/api/detection-boxes')
def get_detection_boxes():
    """Get current detection box configuration"""
    try:
        config_data = load_web_ui_config()
        return jsonify({
            'boxes': config_data['boxes'],
            'image_dimensions': config_data['image_dimensions']
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/detection-boxes', methods=['POST'])
def update_detection_boxes():
    """Update detection box configuration"""
    try:
        data = request.json
        if data is None:
            return jsonify({'error': 'No JSON data provided'}), 400
        boxes = data.get('boxes', [])
        
        # Load current config to preserve refer_image and dimensions
        current_config = load_web_ui_config()
        
        # Save config
        if save_web_ui_config(boxes, current_config['refer_image'], current_config['image_dimensions']):
            return jsonify({'success': True, 'boxes': boxes})
        else:
            return jsonify({'error': 'Failed to save config'}), 500
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/detection-boxes/<int:box_index>', methods=['DELETE'])
def delete_detection_box(box_index):
    """Delete a detection box"""
    try:
        config_data = load_web_ui_config()
        boxes = config_data['boxes']
        
        if 0 <= box_index < len(boxes):
            deleted_box = boxes.pop(box_index)
            
            if save_web_ui_config(boxes, config_data['refer_image'], config_data['image_dimensions']):
                return jsonify({'success': True, 'deleted': deleted_box, 'boxes': boxes})
            else:
                return jsonify({'error': 'Failed to save config'}), 500
        else:
            return jsonify({'error': 'Invalid box index'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get notification settings"""
    try:
        # Load from .env file
        load_dotenv(ENV_FILE)
        
        # Load pause state from JSON file
        pause_state = {'notifications_paused': False}
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, 'r') as f:
                pause_state = json.load(f)
        
        settings = {
            'email_recipients': os.getenv('LASER_MONITOR_EMAIL_RECIPIENTS', ''),
            'sms_recipients': os.getenv('LASER_MONITOR_SMS_RECIPIENTS', ''),
            'notifications_paused': pause_state.get('notifications_paused', False)
        }
        
        return jsonify(settings)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Update notification settings"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Ensure .env file exists
        if not ENV_FILE.exists():
            ENV_FILE.touch()
            # Copy from .env.example if it exists
            env_example = ENV_FILE.parent / '.env.example'
            if env_example.exists():
                with open(env_example, 'r') as src:
                    content = src.read()
                with open(ENV_FILE, 'w') as dst:
                    dst.write(content)
        
        # Update .env file for recipients
        if 'email_recipients' in data:
            set_key(str(ENV_FILE), 'LASER_MONITOR_EMAIL_RECIPIENTS', str(data['email_recipients']))
        
        if 'sms_recipients' in data:
            set_key(str(ENV_FILE), 'LASER_MONITOR_SMS_RECIPIENTS', str(data['sms_recipients']))
        
        # Update pause state in JSON file
        if 'notifications_paused' in data:
            pause_state = {'notifications_paused': bool(data['notifications_paused'])}
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(pause_state, f, indent=2)
        
        return jsonify({'success': True, 'message': 'Settings updated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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