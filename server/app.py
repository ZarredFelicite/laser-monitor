#!/usr/bin/env python3
"""
Simple Flask web server for Laser Monitor Dashboard
Serves latest detection image and machine stats with manual refresh
"""

import os
import json
import tempfile
import math
import threading
from numbers import Real
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, send_file, request
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

_stats_cache_lock = threading.RLock()
_stats_cache_state = None
_stats_cache = None


def _empty_stats(error=None):
    return {
        'current_status': 'unknown',
        'last_update': None,
        'total_machines': 0,
        'active_machines': 0,
        'inactive_machines': 0,
        'unknown_machines': 0,
        'overall_uptime_1h': None,
        'machine_uptimes_1h': {},
        'hourly_activity': {},
        'error': error,
    }


def _history_file_state():
    """Return a cache key that changes when the history file is replaced or edited."""
    try:
        stat = HISTORY_FILE.stat()
    except OSError:
        return (str(HISTORY_FILE), None)
    return (str(HISTORY_FILE), stat.st_mtime_ns, stat.st_size)


def _parse_history_entries(entries):
    """Parse and sort valid history entries once, ignoring malformed records."""
    if not isinstance(entries, list):
        return []

    parsed = []
    for entry in entries:
        if not isinstance(entry, dict) or 'timestamp' not in entry:
            continue
        try:
            timestamp = datetime.fromisoformat(str(entry['timestamp']))
            # Runtime history is naive, but accept offset timestamps without
            # allowing one malformed record to break the dashboard response.
            if timestamp.tzinfo is not None:
                timestamp = timestamp.astimezone().replace(tzinfo=None)
        except (TypeError, ValueError, OverflowError):
            continue
        parsed.append((timestamp, entry.get('status', 'unknown')))
    parsed.sort(key=lambda item: item[0])
    return parsed


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
    """Get current machine statistics and recent history."""
    return jsonify(_get_cached_stats())


def _build_stats(history_data, now=None):
    """Build dashboard statistics from one parsed snapshot of the history."""
    if not isinstance(history_data, dict):
        return _empty_stats('Invalid machine history format')
    if not history_data:
        return _empty_stats('Empty machine history')

    now = now or datetime.now()
    parsed_history = {
        machine_id: _parse_history_entries(
            machine_data.get('entries', [])
            if isinstance(machine_data, dict) else []
        )
        for machine_id, machine_data in history_data.items()
    }

    active_count = 0
    inactive_count = 0
    unknown_count = 0
    latest_timestamp = None

    for entries in parsed_history.values():
        latest_entry = next(
            (entry for entry in reversed(entries) if entry[0] <= now),
            None,
        )
        if latest_entry is None:
            continue
        entry_time, status = latest_entry
        if latest_timestamp is None or entry_time > latest_timestamp:
            latest_timestamp = entry_time
        if status == 'active':
            active_count += 1
        elif status == 'inactive':
            inactive_count += 1
        else:
            unknown_count += 1

    overall_uptime, machine_uptimes = calculate_overall_uptime(
        history_data,
        hours_back=1,
        now=now,
        parsed_history=parsed_history,
    )
    stats = _empty_stats()
    stats.update({
        'total_machines': len(history_data),
        'active_machines': active_count,
        'inactive_machines': inactive_count,
        'unknown_machines': unknown_count,
        'last_update': latest_timestamp.isoformat() if latest_timestamp else None,
        'current_status': (
            'active' if active_count > 0
            else 'unknown' if unknown_count > 0
            else 'inactive'
        ),
        'overall_uptime_1h': overall_uptime,
        'machine_uptimes_1h': machine_uptimes,
        'hourly_activity': generate_hourly_activity(
            history_data, now=now, parsed_history=parsed_history
        ),
    })
    return stats


def _get_cached_stats():
    """Load and cache stats while invalidating on any history file change."""
    global _stats_cache_state, _stats_cache

    with _stats_cache_lock:
        for attempt in range(2):
            state = _history_file_state()
            if state == _stats_cache_state and _stats_cache is not None:
                return _stats_cache

            if state[1] is None:
                stats = _empty_stats('No machine history found')
            else:
                try:
                    with HISTORY_FILE.open('r') as history_file:
                        history_data = json.load(history_file)
                except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                    stats = _empty_stats(f'Unable to load machine history: {exc}')
                else:
                    stats = _build_stats(history_data)

            # History writes are atomic, but retry if a replacement happened
            # while this request was reading the file.
            current_state = _history_file_state()
            if current_state != state and attempt == 0:
                continue
            if current_state == state:
                _stats_cache_state = state
                _stats_cache = stats
            return stats

        return stats

def _calculate_machine_uptime_and_coverage(
    entries, start_time, end_time, parsed_entries=None
):
    """Return uptime over trusted intervals and their duration in seconds."""
    parsed = parsed_entries if parsed_entries is not None else _parse_history_entries(entries)
    current_status = 'unknown'
    period_entries = []
    for timestamp, status in parsed:
        if timestamp > end_time:
            break
        if timestamp <= start_time:
            current_status = status
        else:
            period_entries.append((timestamp, status))

    total_active_seconds = 0.0
    total_known_seconds = 0.0
    last_timestamp = start_time
    for timestamp, status in period_entries:
        elapsed = (timestamp - last_timestamp).total_seconds()
        if current_status in {'active', 'inactive'}:
            total_known_seconds += elapsed
            if current_status == 'active':
                total_active_seconds += elapsed
        current_status = status
        last_timestamp = timestamp

    elapsed = (end_time - last_timestamp).total_seconds()
    if current_status in {'active', 'inactive'}:
        total_known_seconds += elapsed
        if current_status == 'active':
            total_active_seconds += elapsed

    if total_known_seconds <= 0:
        return 0.0, 0.0
    return (total_active_seconds / total_known_seconds) * 100, total_known_seconds


def calculate_machine_uptime(entries, start_time, end_time):
    """Calculate uptime while excluding unknown intervals."""
    uptime, _ = _calculate_machine_uptime_and_coverage(entries, start_time, end_time)
    return uptime


def calculate_overall_uptime(
    history_data, hours_back=1, now=None, parsed_history=None
):
    """Calculate overall uptime and per-machine uptime for the last N hours."""
    now = now or datetime.now()
    start_time = now - timedelta(hours=hours_back)
    parsed_history = parsed_history or {
        machine_id: _parse_history_entries(
            machine_data.get('entries', [])
            if isinstance(machine_data, dict) else []
        )
        for machine_id, machine_data in history_data.items()
    }

    machine_uptimes = {}
    total_uptime_sum = 0
    machine_count = 0

    for machine_id, entries in parsed_history.items():
        uptime, known_seconds = _calculate_machine_uptime_and_coverage(
            [], start_time, now, parsed_entries=entries
        )
        if known_seconds <= 0:
            machine_uptimes[machine_id] = None
            continue
        machine_uptimes[machine_id] = round(uptime, 1)
        total_uptime_sum += uptime
        machine_count += 1

    overall_uptime = (
        round(total_uptime_sum / machine_count, 1)
        if machine_count > 0 else None
    )

    return overall_uptime, machine_uptimes


def _hourly_uptime(parsed_entries, now, bucket_count=24):
    """Aggregate trusted active/inactive intervals into hourly buckets in one pass."""
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    window_start = current_hour - timedelta(hours=bucket_count - 1)
    buckets = [[0.0, 0.0] for _ in range(bucket_count)]  # active, known seconds

    current_status = 'unknown'
    entry_index = 0
    while entry_index < len(parsed_entries):
        timestamp, status = parsed_entries[entry_index]
        if timestamp > window_start:
            break
        if timestamp <= now:
            current_status = status
        entry_index += 1

    cursor = window_start
    for bucket_index in range(bucket_count):
        bucket_end = now if bucket_index == bucket_count - 1 else cursor + timedelta(hours=1)
        while entry_index < len(parsed_entries):
            timestamp, status = parsed_entries[entry_index]
            if timestamp > bucket_end or timestamp > now:
                break
            elapsed = (timestamp - cursor).total_seconds()
            if current_status in {'active', 'inactive'}:
                buckets[bucket_index][1] += elapsed
                if current_status == 'active':
                    buckets[bucket_index][0] += elapsed
            current_status = status
            cursor = timestamp
            entry_index += 1

        elapsed = (bucket_end - cursor).total_seconds()
        if current_status in {'active', 'inactive'}:
            buckets[bucket_index][1] += elapsed
            if current_status == 'active':
                buckets[bucket_index][0] += elapsed
        cursor = bucket_end

    return buckets


def generate_hourly_activity(history_data, now=None, parsed_history=None):
    """Generate 24 hourly activity buckets for each machine."""
    now = now or datetime.now()
    parsed_history = parsed_history or {
        machine_id: _parse_history_entries(
            machine_data.get('entries', [])
            if isinstance(machine_data, dict) else []
        )
        for machine_id, machine_data in history_data.items()
    }
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    machine_hourly_data = {}

    for machine_id, entries in parsed_history.items():
        hourly_uptime = _hourly_uptime(entries, now)
        machine_hourly_data[machine_id] = []
        for index, (active_seconds, known_seconds) in enumerate(hourly_uptime):
            hour_start = current_hour - timedelta(hours=23 - index)
            uptime = (
                (active_seconds / known_seconds) * 100
                if known_seconds > 0 else 0.0
            )
            machine_hourly_data[machine_id].append({
                'hour': hour_start.strftime('%m/%d %H:00'),
                'activity_percentage': round(uptime, 1),
                'active_minutes': round((uptime / 100) * 60, 1),
                'is_current_hour': index == 23,
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
    """Validate and atomically save dashboard detection boxes."""
    if image_dimensions is None:
        image_dimensions = [1920, 1080]
    if (
        not isinstance(image_dimensions, (list, tuple))
        or len(image_dimensions) != 2
        or not all(
            isinstance(value, Real)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and value > 0
            for value in image_dimensions
        )
    ):
        print("Error saving web_ui config: invalid image dimensions")
        return False
    if not isinstance(boxes, list):
        print("Error saving web_ui config: boxes must be a list")
        return False
    for index, box in enumerate(boxes):
        if (
            not isinstance(box, (list, tuple))
            or len(box) != 4
            or not all(
                isinstance(value, Real)
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                for value in box
            )
        ):
            print(f"Error saving web_ui config: invalid box {index}")
            return False
        normalized = all(value <= 1.0 for value in box)
        max_x = 1.0 if normalized else image_dimensions[0]
        max_y = 1.0 if normalized else image_dimensions[1]
        if not (
            0 <= box[0] < box[2] <= max_x
            and 0 <= box[1] < box[3] <= max_y
        ):
            print(f"Error saving web_ui config: out-of-range box {index}")
            return False
    
    # Prefer the unannotated frame so overlays cannot corrupt drift matching.
    if refer_image is None:
        try:
            raw_reference = OUTPUT_DIR / "latest_raw.jpg"
            if raw_reference.exists():
                refer_image = str(raw_reference.absolute())
            else:
                image_files = list(SCREENSHOTS_DIR.glob('detection_*.jpg'))
                if image_files:
                    latest_image = max(image_files, key=lambda f: f.stat().st_mtime)
                    refer_image = str(latest_image.absolute())
                else:
                    refer_image = ""
        except OSError:
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
    
    temporary_file = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=WEB_UI_CONFIG_FILE.parent,
            prefix=".web-ui-config-",
            suffix=".py",
        )
        temporary_file = Path(temporary_name)
        with os.fdopen(descriptor, 'w') as f:
            f.write(config_content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_file, WEB_UI_CONFIG_FILE)
        return True
    except Exception as e:
        if temporary_file is not None:
            temporary_file.unlink(missing_ok=True)
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
        if save_web_ui_config(boxes, None, current_config['image_dimensions']):
            return jsonify({'success': True, 'boxes': boxes})
        else:
            return jsonify({'error': 'Failed to save config'}), 500
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/detection-boxes/<int:box_index>/tighten-red', methods=['POST'])
def tighten_detection_box_red(box_index):
    """Tighten one loose detection box around red pixels in the latest image."""
    try:
        import cv2
        import numpy as np

        config_data = load_web_ui_config()
        boxes = config_data['boxes']
        if not (0 <= box_index < len(boxes)):
            return jsonify({'error': 'Invalid box index'}), 400

        image_files = list(SCREENSHOTS_DIR.glob('detection_*.jpg'))
        if not image_files:
            return jsonify({'error': 'No detection images found'}), 404

        latest_image = max(image_files, key=lambda f: f.stat().st_mtime)
        image = cv2.imread(str(latest_image))
        if image is None:
            return jsonify({'error': 'Failed to read latest image'}), 500

        height, width = image.shape[:2]
        box = boxes[box_index]
        x1 = max(0, min(width - 1, int(round(box[0]))))
        y1 = max(0, min(height - 1, int(round(box[1]))))
        x2 = max(x1 + 1, min(width, int(round(box[2]))))
        y2 = max(y1 + 1, min(height, int(round(box[3]))))

        roi = image[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        hue = hsv[:, :, 0]
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        mask = (((hue <= 25) | (hue >= 170)) & (sat >= 80) & (val >= 80)).astype(np.uint8) * 255

        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = [c for c in contours if cv2.contourArea(c) >= 20]
        if not contours:
            return jsonify({'error': 'No red/orange indicator blob found inside selected box'}), 422

        largest = max(contours, key=cv2.contourArea)
        rx, ry, rw, rh = cv2.boundingRect(largest)
        padding = int((request.json or {}).get('padding', 6))
        tight_box = [
            max(0, x1 + rx - padding),
            max(0, y1 + ry - padding),
            min(width, x1 + rx + rw + padding),
            min(height, y1 + ry + rh + padding),
        ]

        boxes[box_index] = tight_box
        if save_web_ui_config(boxes, str(latest_image.absolute()), [width, height]):
            return jsonify({'success': True, 'box': tight_box, 'boxes': boxes})
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
            
            if save_web_ui_config(boxes, None, config_data['image_dimensions']):
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
    
    app.run(
        debug=False,
        use_reloader=False,
        host='0.0.0.0',
        port=5000,
    )