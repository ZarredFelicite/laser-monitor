#!/usr/bin/env python3
"""
Laser Monitor - Detection system with continuous monitoring support

Supports both single-shot detection and continuous monitoring modes.
Continuous mode captures frames every 2 minutes and tracks machine status history.
Alerts when machines are inactive for more than 15 minutes and when they become active again.
"""

import warnings
import os
import sys
import json
import logging
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

# Suppress warnings
warnings.filterwarnings("ignore")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

try:
    # Core runtime dependencies for bbox mode
    from config.config import LaserMonitorConfig
    from camera_manager import CameraManager
    from image_uploader import ImageUploader
    import cv2
    import numpy as np
except ImportError as e:
    print(f"Required core packages not available: {e}")
    print("Please install opencv-python and ensure config.py and camera_manager.py are available.")
    sys.exit(1)


class DetectionResult:
    """Single detection result

    Added optional extras dictionary to carry mode-specific metrics (e.g., red/green ratios
    in indicator mode) without breaking existing consumers.
    """
    
    def __init__(self, timestamp: str, confidence: float, bbox: List[float], 
                 class_name: str, laser_status: str, zone_name: Optional[str] = None,
                 extras: Optional[Dict[str, Any]] = None):
        self.timestamp = timestamp
        self.confidence = confidence
        self.bbox = bbox  # [x1, y1, x2, y2]
        self.class_name = class_name
        self.laser_status = laser_status
        self.zone_name = zone_name
        self.extras = extras or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        data = {
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "bbox": self.bbox,
            "class_name": self.class_name,
            "laser_status": self.laser_status,
            "zone_name": self.zone_name
        }
        if self.extras:
            data["extras"] = self.extras
        return data


@dataclass
class MachineStatusEntry:
    """Single machine status entry for history tracking"""
    timestamp: datetime
    status: str  # "active", "inactive"
    class_name: str  # "machine_active", "machine_working_only", etc.
    confidence: float
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MachineHistory:
    """Machine status history tracker"""
    machine_id: str
    entries: List[MachineStatusEntry] = field(default_factory=list)
    last_active_time: Optional[datetime] = None
    last_inactive_time: Optional[datetime] = None
    
    def add_entry(self, status: str, class_name: str, confidence: float, details: Dict[str, Any] = None):
        """Add a new status entry"""
        entry = MachineStatusEntry(
            timestamp=datetime.now(),
            status=status,
            class_name=class_name,
            confidence=confidence,
            details=details or {}
        )
        self.entries.append(entry)
        
        # Update last active/inactive times
        if status == "active":
            self.last_active_time = entry.timestamp
        else:
            self.last_inactive_time = entry.timestamp
        
        # Clean up old entries (keep only last 7 days)
        self.cleanup_old_entries(entry.timestamp)
    
    def cleanup_old_entries(self, cutoff_time: Optional[datetime] = None):
        """Remove entries older than 7 days"""
        if cutoff_time is None:
            cutoff_time = datetime.now() - timedelta(days=7)
        else:
            cutoff_time = cutoff_time - timedelta(days=7)
        
        self.entries = [
            entry for entry in self.entries 
            if entry.timestamp >= cutoff_time
        ]
    
    def get_inactive_duration(self) -> Optional[timedelta]:
        """Get duration since last active status"""
        if self.last_active_time is None:
            return None
        if self.last_inactive_time is None or self.last_active_time > self.last_inactive_time:
            return timedelta(0)  # Currently active
        return datetime.now() - self.last_active_time
    
    def is_inactive_too_long(self, threshold_minutes: int = 10) -> bool:
        """Check if machine has been inactive for too long"""
        duration = self.get_inactive_duration()
        if duration is None:
            return False
        return duration.total_seconds() > (threshold_minutes * 60)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        # Filter entries to keep only the last 7 days
        seven_days_ago = datetime.now() - timedelta(days=7)
        recent_entries = [
            entry for entry in self.entries 
            if entry.timestamp >= seven_days_ago
        ]
        
        return {
            "machine_id": self.machine_id,
            "last_active_time": self.last_active_time.isoformat() if self.last_active_time else None,
            "last_inactive_time": self.last_inactive_time.isoformat() if self.last_inactive_time else None,
            "entries": [
                {
                    "timestamp": entry.timestamp.isoformat(),
                    "status": entry.status,
                    "class_name": entry.class_name,
                    "confidence": entry.confidence,
                    "details": entry.details
                }
                for entry in recent_entries
            ]
        }


class EmailAlertManager:
    """Manages email alerts for machine status"""
    
    def __init__(self, config: LaserMonitorConfig):
        self.config = config
        self.logger = logging.getLogger(__name__ + ".EmailAlert")
        self.last_alert_times: Dict[str, datetime] = {}
        # Track whether we've already sent an alert for the current inactive period
        self.alert_sent_for_current_inactive_period: Dict[str, bool] = {}
        # Track the last known status for each machine to detect transitions
        self.last_machine_status: Dict[str, str] = {}
        
        # Load environment variables from .env file
        self._load_env_file()
        
        # Get email credentials from environment variables
        self.smtp_username = os.getenv('LASER_MONITOR_EMAIL_USER', self.config.alerts.email_username)
        self.smtp_password = os.getenv('LASER_MONITOR_EMAIL_PASS', self.config.alerts.email_password)
        # Get email recipients from environment (fallback to config for backward compatibility)
        self.recipients = self._parse_list_env('LASER_MONITOR_EMAIL_RECIPIENTS', self.config.alerts.email_recipients)
        
        if not self.smtp_username or not self.smtp_password:
            self.logger.warning("Email credentials not configured. Create a .env file with LASER_MONITOR_EMAIL_USER and LASER_MONITOR_EMAIL_PASS variables.")

    @staticmethod
    def _parse_list_env(var_name: str, fallback: Optional[List[str]] = None) -> List[str]:
        raw = os.getenv(var_name, "").strip()
        if raw:
            # Split on commas, semicolons, or whitespace and strip blanks
            items = []
            for sep in [',', ';', '\n', '\t', ' ']:
                raw = raw.replace(sep, ',')
            items = [x.strip() for x in raw.split(',') if x.strip()]
            return items
        return list(fallback or [])
    
    def _load_env_file(self):
        """Load environment variables from .env file"""
        try:
            from dotenv import load_dotenv
            
            # Look for .env file in current directory and project root
            env_paths = ['.env', Path(__file__).parent / '.env']
            
            for env_path in env_paths:
                if Path(env_path).exists():
                    load_dotenv(env_path)
                    self.logger.debug(f"Loaded environment variables from {env_path}")
                    return
            
            self.logger.debug("No .env file found, using system environment variables")
            
        except ImportError:
            self.logger.warning("python-dotenv not installed. Install with: pip install python-dotenv")
        except Exception as e:
            self.logger.warning(f"Failed to load .env file: {e}")
    
    def update_machine_status(self, machine_id: str, current_status: str, machine_history=None):
        """Update machine status and send active alert when transitioning from inactive to active"""
        previous_status = self.last_machine_status.get(machine_id)
        self.last_machine_status[machine_id] = current_status
        
        # If machine transitions from inactive to active, send active alert and reset flag
        if previous_status == "inactive" and current_status == "active":
            # Send active alert if we previously sent an inactive alert
            if self.alert_sent_for_current_inactive_period.get(machine_id, False):
                inactive_duration_minutes = 0.0
                if machine_history:
                    duration = machine_history.get_inactive_duration()
                    inactive_duration_minutes = duration.total_seconds() / 60
                
                # Send active alert
                active_sent = self.send_active_alert(machine_id, inactive_duration_minutes)
                if active_sent:
                    self.logger.info(f"Active email alert sent for {machine_id}")
                else:
                    self.logger.warning(f"Failed to send active email alert for {machine_id}")
            
            self.alert_sent_for_current_inactive_period[machine_id] = False
            self.logger.debug(f"Machine {machine_id} transitioned to active - reset alert flag")
    
    def should_send_alert(self, machine_id: str) -> bool:
        """Check if we should send an alert for this machine"""
        if not self.config.alerts.email_alerts:
            return False
        
        if machine_id not in self.config.alerts.alert_machines:
            return False
        
        # Don't send alert if we've already sent one for the current inactive period
        if self.alert_sent_for_current_inactive_period.get(machine_id, False):
            return False
        
        return True
    
    def send_inactive_alert(self, machine_id: str, inactive_duration_minutes: float, last_active_time: Optional[datetime] = None, is_test: bool = False):
        """Send email alert for inactive machine"""
        if not is_test and not self.should_send_alert(machine_id):
            self.logger.debug(f"Skipping alert for {machine_id} - cooldown active or not configured")
            return False
        
        if not self.smtp_username or not self.smtp_password:
            self.logger.error("Cannot send email alert - credentials not configured")
            return False
        
        try:
            # Create email message
            msg = MIMEMultipart()
            msg['From'] = self.config.alerts.email_from
            msg['To'] = ', '.join(self.recipients)
            
            # Use different subject for test emails
            if is_test:
                msg['Subject'] = "🧪 TEST - " + self.config.alerts.email_subject
            else:
                msg['Subject'] = self.config.alerts.email_subject
            
            # Create email body
            body = self._create_alert_body(machine_id, inactive_duration_minutes, last_active_time, is_test)
            msg.attach(MIMEText(body, 'html'))
            
            # Send email
            with smtplib.SMTP(self.config.alerts.email_smtp_server, self.config.alerts.email_smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            
            # Record alert time and mark that we've sent an alert for this inactive period
            self.last_alert_times[machine_id] = datetime.now()
            self.alert_sent_for_current_inactive_period[machine_id] = True
            
            self.logger.info(f"Email alert sent for {machine_id} (inactive for {inactive_duration_minutes:.1f} minutes)")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to send email alert for {machine_id}: {e}")
            return False
    
    def _create_alert_body(self, machine_id: str, inactive_duration_minutes: float, last_active_time: Optional[datetime], is_test: bool = False) -> str:
        """Create HTML email body for alert"""
        last_active_str = last_active_time.strftime("%Y-%m-%d %H:%M:%S") if last_active_time else "Unknown"
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Different styling and content for test emails
        if is_test:
            header_color = "#2196F3"  # Blue for test
            header_text = "🧪 Laser Monitor Test Alert"
            status_text = "TEST - INACTIVE"
            test_notice = """
            <div style="background-color: #e3f2fd; padding: 10px; border-left: 4px solid #2196F3; margin: 10px 0;">
                <strong>🧪 This is a test email</strong><br>
                This email was sent using the --test-email flag to verify the alert system is working correctly.
            </div>
            """
        else:
            header_color = "#d32f2f"  # Red for real alerts
            header_text = "🚨 Laser Monitor Alert"
            status_text = "INACTIVE"
            test_notice = ""
        
        return f"""
        <html>
        <body>
            <h2 style="color: {header_color};">{header_text}</h2>
            
            {test_notice}
            
            <p><strong>Machine:</strong> {machine_id}</p>
            <p><strong>Status:</strong> <span style="color: {header_color};">{status_text}</span></p>
            <p><strong>Inactive Duration:</strong> {inactive_duration_minutes:.1f} minutes</p>
            <p><strong>Last Active:</strong> {last_active_str}</p>
            <p><strong>Alert Time:</strong> {current_time}</p>
            
            <hr>
            
            <h3>Details:</h3>
            <ul>
                <li>The machine has been inactive for more than 15 minutes</li>
                <li>This indicates the laser may not be working properly</li>
                <li>Please check the machine status and investigate if necessary</li>
            </ul>
            
            <p><em>This is an automated alert from the Laser Monitor system.</em></p>
        </body>
        </html>
        """
    
    def send_active_alert(self, machine_id: str, inactive_duration_minutes: float, is_test: bool = False):
        """Send email alert when machine becomes active again"""
        if not is_test and not self.should_send_alert_for_active(machine_id):
            self.logger.debug(f"Skipping active alert for {machine_id} - not configured or no previous inactive alert")
            return False
        
        if not self.smtp_username or not self.smtp_password:
            self.logger.error("Cannot send email alert - credentials not configured")
            return False
        
        try:
            # Create email message
            msg = MIMEMultipart()
            msg['From'] = self.config.alerts.email_from
            msg['To'] = ', '.join(self.recipients)
            
            # Use different subject for test emails
            if is_test:
                msg['Subject'] = "🧪 TEST - Machine Active Again - " + self.config.alerts.email_subject
            else:
                msg['Subject'] = "✅ Machine Active Again - " + self.config.alerts.email_subject
            
            # Create email body
            body = self._create_active_alert_body(machine_id, inactive_duration_minutes, is_test)
            msg.attach(MIMEText(body, 'html'))
            
            # Send email
            with smtplib.SMTP(self.config.alerts.smtp_server, self.config.alerts.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            
            # Mark that we've sent an active alert for this machine
            if not is_test:
                self.alert_sent_for_current_inactive_period[machine_id] = False  # Reset for next cycle
            
            self.logger.info(f"Active email alert sent for {machine_id} (was inactive for {inactive_duration_minutes:.1f} minutes)")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to send active email alert for {machine_id}: {e}")
            return False
    
    def should_send_alert_for_active(self, machine_id: str) -> bool:
        """Check if we should send an active alert (only if we previously sent an inactive alert)"""
        if not self.config.alerts.email_alerts:
            return False
        
        if machine_id not in self.config.alerts.alert_machines:
            return False
        
        # Only send active alert if we previously sent an inactive alert for this period
        return self.alert_sent_for_current_inactive_period.get(machine_id, False)
    
    def _create_active_alert_body(self, machine_id: str, inactive_duration_minutes: float, is_test: bool = False) -> str:
        """Create HTML email body for active alert"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Different styling and content for test emails
        if is_test:
            header_color = "#2196F3"  # Blue for test
            header_text = "🧪 Laser Monitor Test - Machine Active"
            status_text = "TEST - ACTIVE AGAIN"
            test_notice = """
            <div style="background-color: #e3f2fd; padding: 10px; border-left: 4px solid #2196F3; margin: 10px 0;">
                <strong>🧪 This is a test email</strong><br>
                This email was sent to test the active alert system.
            </div>
            """
        else:
            header_color = "#4caf50"  # Green for active alerts
            header_text = "✅ Laser Monitor - Machine Active Again"
            status_text = "ACTIVE AGAIN"
            test_notice = ""
        
        return f"""
        <html>
        <body>
            <h2 style="color: {header_color};">{header_text}</h2>
            {test_notice}
            <p><strong>Machine ID:</strong> {machine_id}</p>
            <p><strong>Status:</strong> <span style="color: {header_color}; font-weight: bold;">{status_text}</span></p>
            <p><strong>Previous Inactive Duration:</strong> {inactive_duration_minutes:.1f} minutes</p>
            <p><strong>Alert Time:</strong> {current_time}</p>
            
            <div style="background-color: #e8f5e8; padding: 10px; border-left: 4px solid #4caf50; margin: 10px 0;">
                <strong>✅ Good news!</strong><br>
                The machine is now active again after being inactive for {inactive_duration_minutes:.1f} minutes.
            </div>
            
            <hr>
            <p style="font-size: 12px; color: #666;">
                This alert was generated by the Laser Monitor system.<br>
                Machine became active again at {current_time}.
            </p>
        </body>
        </html>
        """


class SMSAlertManager:
    """Manages SMS alerts for machine status using Twilio"""
    
    def __init__(self, config: LaserMonitorConfig):
        self.config = config
        self.logger = logging.getLogger(__name__ + ".SMSAlert")
        self.last_alert_times: Dict[str, datetime] = {}
        # Track whether we've already sent an alert for the current inactive period
        self.alert_sent_for_current_inactive_period: Dict[str, bool] = {}
        # Track the last known status for each machine to detect transitions
        self.last_machine_status: Dict[str, str] = {}
        
        # Load environment variables from .env file
        self._load_env_file()
        
        # Get Twilio credentials from environment variables
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID', self.config.alerts.twilio_account_sid)
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN', self.config.alerts.twilio_auth_token)
        self.from_number = os.getenv('TWILIO_FROM_NUMBER', self.config.alerts.twilio_from_number)
        # Get SMS recipients from environment (fallback to config for backward compatibility)
        self.recipients = self._parse_list_env('LASER_MONITOR_SMS_RECIPIENTS', self.config.alerts.sms_recipients)
        
        if not self.account_sid or not self.auth_token or not self.from_number:
            self.logger.warning("Twilio credentials not configured. Create a .env file with TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER variables.")
        
        # Initialize Twilio client
        self.client = None
        if self.account_sid and self.auth_token:
            try:
                from twilio.rest import Client
                self.client = Client(self.account_sid, self.auth_token)
                self.logger.debug("Twilio client initialized successfully")
            except ImportError:
                self.logger.warning("Twilio library not installed. Install with: pip install twilio")
            except Exception as e:
                self.logger.error(f"Failed to initialize Twilio client: {e}")
    
    def _load_env_file(self):
        """Load environment variables from .env file"""
        try:
            from dotenv import load_dotenv
            
            # Look for .env file in current directory and project root
            env_paths = ['.env', Path(__file__).parent / '.env']
            
            for env_path in env_paths:
                if Path(env_path).exists():
                    load_dotenv(env_path)
                    self.logger.debug(f"Loaded environment variables from {env_path}")
                    return
            
            self.logger.debug("No .env file found, using system environment variables")
            
        except ImportError:
            self.logger.warning("python-dotenv not installed. Install with: pip install python-dotenv")
        except Exception as e:
            self.logger.warning(f"Failed to load .env file: {e}")

    @staticmethod
    def _parse_list_env(var_name: str, fallback: Optional[List[str]] = None) -> List[str]:
        raw = os.getenv(var_name, "").strip()
        if raw:
            for sep in [',', ';', '\n', '\t', ' ']:
                raw = raw.replace(sep, ',')
            return [x.strip() for x in raw.split(',') if x.strip()]
        return list(fallback or [])
    
    def update_machine_status(self, machine_id: str, current_status: str, machine_history=None):
        """Update machine status and send active alert when transitioning from inactive to active"""
        previous_status = self.last_machine_status.get(machine_id)
        self.last_machine_status[machine_id] = current_status
        
        # If machine transitions from inactive to active, send active alert and reset flag
        if previous_status == "inactive" and current_status == "active":
            # Send active alert if we previously sent an inactive alert
            if self.alert_sent_for_current_inactive_period.get(machine_id, False):
                inactive_duration_minutes = 0.0
                if machine_history:
                    duration = machine_history.get_inactive_duration()
                    inactive_duration_minutes = duration.total_seconds() / 60
                
                # Send active alert
                active_sent = self.send_active_alert(machine_id, inactive_duration_minutes)
                if active_sent:
                    self.logger.info(f"Active SMS alert sent for {machine_id}")
                else:
                    self.logger.warning(f"Failed to send active SMS alert for {machine_id}")
            
            self.alert_sent_for_current_inactive_period[machine_id] = False
            self.logger.debug(f"Machine {machine_id} transitioned to active - reset SMS alert flag")
    
    def should_send_alert(self, machine_id: str) -> bool:
        """Check if we should send an SMS alert for this machine"""
        if not self.config.alerts.sms_alerts:
            return False
        
        if machine_id not in self.config.alerts.alert_machines:
            return False
        
        # Don't send alert if we've already sent one for the current inactive period
        if self.alert_sent_for_current_inactive_period.get(machine_id, False):
            return False
        
        return True
    
    def send_inactive_alert(self, machine_id: str, inactive_duration_minutes: float, last_active_time: Optional[datetime] = None, is_test: bool = False):
        """Send SMS alert for inactive machine"""
        if not is_test and not self.should_send_alert(machine_id):
            self.logger.debug(f"Skipping SMS alert for {machine_id} - already sent or not configured")
            return False
        
        if not self.client:
            self.logger.error("Cannot send SMS alert - Twilio client not initialized")
            return False
        
        if not self.recipients:
            self.logger.warning("No SMS recipients configured")
            return False
        
        try:
            # Create SMS message
            message_body = self._create_alert_message(machine_id, inactive_duration_minutes, last_active_time, is_test)
            
            # Send SMS to all recipients
            sent_count = 0
            for recipient in self.recipients:
                try:
                    message = self.client.messages.create(
                        body=message_body,
                        from_=self.from_number,
                        to=recipient
                    )
                    self.logger.debug(f"SMS sent to {recipient}: {message.sid}")
                    sent_count += 1
                except Exception as e:
                    self.logger.error(f"Failed to send SMS to {recipient}: {e}")
            
            if sent_count > 0:
                # Record alert time and mark that we've sent an alert for this inactive period
                self.last_alert_times[machine_id] = datetime.now()
                self.alert_sent_for_current_inactive_period[machine_id] = True
                
                self.logger.info(f"SMS alert sent for {machine_id} to {sent_count} recipients (inactive for {inactive_duration_minutes:.1f} minutes)")
                return True
            else:
                self.logger.error(f"Failed to send SMS alert to any recipients for {machine_id}")
                return False
            
        except Exception as e:
            self.logger.error(f"Failed to send SMS alert for {machine_id}: {e}")
            return False
    
    def _create_alert_message(self, machine_id: str, inactive_duration_minutes: float, last_active_time: Optional[datetime], is_test: bool = False) -> str:
        """Create SMS message for alert"""
        last_active_str = last_active_time.strftime("%Y-%m-%d %H:%M:%S") if last_active_time else "Unknown"
        
        if is_test:
            return f"🧪 TEST ALERT: Laser Monitor SMS system is working correctly. Machine: {machine_id}"
        else:
            return f"🚨 LASER ALERT: {machine_id} has been inactive for {inactive_duration_minutes:.1f} minutes. Last active: {last_active_str}. Please check the machine."
    
    def send_active_alert(self, machine_id: str, inactive_duration_minutes: float, is_test: bool = False):
        """Send SMS alert when machine becomes active again"""
        if not is_test and not self.should_send_alert_for_active(machine_id):
            self.logger.debug(f"Skipping active SMS alert for {machine_id} - not configured or no previous inactive alert")
            return False
        
        if not self.client:
            self.logger.error("Cannot send SMS alert - Twilio client not initialized")
            return False
        
        if not self.recipients:
            self.logger.warning("No SMS recipients configured")
            return False
        
        try:
            # Create SMS message
            message_body = self._create_active_alert_message(machine_id, inactive_duration_minutes, is_test)
            
            # Send to all recipients
            sent_count = 0
            for recipient in self.recipients:
                try:
                    message = self.client.messages.create(
                        body=message_body,
                        from_=self.from_number,
                        to=recipient
                    )
                    sent_count += 1
                    self.logger.debug(f"SMS sent to {recipient}: {message.sid}")
                except Exception as e:
                    self.logger.error(f"Failed to send SMS to {recipient}: {e}")
            
            if sent_count > 0:
                # Mark that we've sent an active alert for this machine
                if not is_test:
                    self.alert_sent_for_current_inactive_period[machine_id] = False  # Reset for next cycle
                
                self.logger.info(f"Active SMS alert sent for {machine_id} to {sent_count} recipients (was inactive for {inactive_duration_minutes:.1f} minutes)")
                return True
            else:
                self.logger.error(f"Failed to send active SMS alert to any recipients for {machine_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to send active SMS alert for {machine_id}: {e}")
            return False
    
    def should_send_alert_for_active(self, machine_id: str) -> bool:
        """Check if we should send an active SMS alert (only if we previously sent an inactive alert)"""
        if not self.config.alerts.sms_alerts:
            return False
        
        if machine_id not in self.config.alerts.alert_machines:
            return False
        
        # Only send active alert if we previously sent an inactive alert for this period
        return self.alert_sent_for_current_inactive_period.get(machine_id, False)
    
    def _create_active_alert_message(self, machine_id: str, inactive_duration_minutes: float, is_test: bool = False) -> str:
        """Create SMS message for active alert"""
        if is_test:
            return f"🧪 TEST: Laser Monitor active alert system working. Machine: {machine_id}"
        else:
            return f"✅ LASER UPDATE: {machine_id} is now ACTIVE again after being inactive for {inactive_duration_minutes:.1f} minutes. 🎉"


class LaserMonitor:
    """Laser monitor with continuous monitoring and machine history tracking"""
    
    def __init__(self, config: LaserMonitorConfig):
        self.config = config
        self.logger = self._setup_logging()
        self.camera_manager = CameraManager()
        self.model = None
        
        # Create output directories
        self.output_dir = Path(self.config.output.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.detections_dir = self.output_dir / 'detections'
        self.detections_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir = self.output_dir / 'screenshots'
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # Machine history tracking
        self.machine_histories: Dict[str, MachineHistory] = {}
        self.history_file = self.output_dir / 'machine_history.json'
        self.load_machine_history()
        
        # Alert systems
        self.email_alert_manager = EmailAlertManager(config)
        self.sms_alert_manager = SMSAlertManager(config)
        
        # Image uploader
        self.image_uploader = ImageUploader(self.config.output.upload_url) if self.config.output.upload_images else None
        
        # Monitoring control
        self.monitoring_active = False
        self.monitoring_interval = self.config.monitoring.monitoring_interval_seconds
        self.inactive_alert_threshold = self.config.monitoring.inactive_alert_threshold_minutes
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration with dynamic console log level.
        Ensures DEBUG messages appear when config.logging.log_level is set to DEBUG."""
        logger = logging.getLogger(__name__)
        logger.setLevel(getattr(logging, self.config.logging.log_level.upper()))

        # Avoid adding duplicate handlers if re-instantiated
        if not logger.handlers:
            # Console handler mirrors logger level so DEBUG is visible when requested
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logger.level)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

            # File handler if enabled
            if self.config.logging.log_to_file:
                file_handler = logging.FileHandler(self.config.logging.log_file)
                file_handler.setLevel(logger.level)
                file_formatter = logging.Formatter(self.config.logging.log_format)
                file_handler.setFormatter(file_formatter)
                logger.addHandler(file_handler)
        else:
            # Update existing handler levels to match new config if needed
            for h in logger.handlers:
                h.setLevel(logger.level)

        logger.propagate = False
        return logger
    
    def load_model(self) -> bool:
        """Load YOLOE model (only needed for text/visual modes)"""
        # Skip model loading for bbox mode
        if self.config.detection.mode == "bbox":
            self.logger.info("Bbox mode selected - skipping model loading")
            return True
            
        try:
            # Lazy import ultralytics only when necessary
            try:
                from ultralytics import YOLOE  # type: ignore
            except ImportError:
                self.logger.error("ultralytics not installed - required for text/visual detection modes. Install with 'pip install ultralytics' or enable optional ai extras.")
                return False

            model_path = Path(self.config.model_path)
            if not model_path.exists():
                self.logger.error(f"Model file not found: {model_path}")
                return False
            
            self.logger.info(f"Loading model: {model_path}")
            self.model = YOLOE(str(model_path))
            self.logger.info("Model loaded successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load model: {e}")
            return False
    
    def open_camera(self) -> bool:
        """Open camera for capture"""
        try:
            if not self.camera_manager.open_camera(
                self.config.camera.camera_id,
                self.config.camera.camera_type
            ):
                self.logger.error("Failed to open camera")
                return False
            
            # Configure camera settings
            camera_settings = {
                'width': self.config.camera.resolution_width,
                'height': self.config.camera.resolution_height,
                'fps': self.config.camera.fps,
                'auto_exposure': self.config.camera.auto_exposure,
                'exposure': self.config.camera.exposure_value,
                'brightness': self.config.camera.brightness,
                'contrast': self.config.camera.contrast,
                'saturation': self.config.camera.saturation,
            }
            
            self.camera_manager.configure_camera(camera_settings)
            
            # Log camera info
            camera_info = self.camera_manager.get_camera_info()
            self.logger.info(f"Camera opened: {camera_info}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to open camera: {e}")
            return False
    
    def capture_frame(self) -> Optional[np.ndarray]:
        """Capture a single frame from camera"""
        try:
            ret, frame = self.camera_manager.read_frame()
            if not ret or frame is None:
                self.logger.error("Failed to capture frame")
                return None
            
            self.logger.info(f"Frame captured: {frame.shape}")
            return frame
            
        except Exception as e:
            self.logger.error(f"Error capturing frame: {e}")
            return None
    
    def detect_objects(self, frame: np.ndarray) -> List[DetectionResult]:
        """Perform object detection on frame"""
        if self.config.detection.mode in ["text", "visual"] and self.model is None:
            self.logger.error("Model not loaded for AI detection mode (install ultralytics or switch to --detection-mode bbox)")
            return []
        
        try:
            timestamp = datetime.now().isoformat()
            
            # Perform detection based on mode
            if self.config.detection.mode == "text":
                results = self._detect_with_text_prompts(frame)
            elif self.config.detection.mode == "visual":
                results = self._detect_with_visual_prompts(frame)
            elif self.config.detection.mode == "bbox":
                results = self._detect_with_fixed_bboxes(frame)
            else:
                self.logger.error(f"Unknown detection mode: {self.config.detection.mode}")
                return []
            
            # Convert to DetectionResult objects (for AI-based detection modes)
            detections = []
            if self.config.detection.mode in ["text", "visual"]:
                for result in results:
                    for box in result.boxes:
                        if box.conf[0] >= self.config.detection.confidence_threshold:
                            bbox = box.xyxy[0].cpu().numpy().tolist()
                            confidence = float(box.conf[0])
                            class_name = result.names[int(box.cls[0])]
                            
                            # Determine laser status based on detection
                            laser_status = self._determine_laser_status(class_name, confidence)
                            
                            # Check if detection is in any zone
                            zone_name = self._check_zones(bbox)
                            
                            detection = DetectionResult(
                                timestamp=timestamp,
                                confidence=confidence,
                                bbox=bbox,
                                class_name=class_name,
                                laser_status=laser_status,
                                zone_name=zone_name
                            )
                            detections.append(detection)
            else:
                # For bbox mode, results are already DetectionResult objects
                detections = results
            
            self.logger.info(f"Detected {len(detections)} objects")
            return detections
            
        except Exception as e:
            self.logger.error(f"Detection failed: {e}")
            return []
    
    def _detect_with_text_prompts(self, frame: np.ndarray):
        """Detect using text prompts"""
        keywords = self.config.detection.laser_keywords
        prompt = ", ".join(keywords)
        return self.model(frame, prompt=prompt)
    
    def _detect_with_visual_prompts(self, frame: np.ndarray):
        """Detect using visual prompts"""
        if self.config.detection.refer_image and self.config.detection.visual_prompts:
            # Use refer_image with bounding boxes
            refer_image = cv2.imread(self.config.detection.refer_image)
            if refer_image is None:
                self.logger.error(f"Could not load refer_image: {self.config.detection.refer_image}")
                return []
            
            # Use first visual prompt bbox
            bbox = self.config.detection.visual_prompts[0]
            h, w = refer_image.shape[:2]
            x1, y1, x2, y2 = [int(coord * dim) for coord, dim in zip(bbox, [w, h, w, h])]
            visual_prompt = refer_image[y1:y2, x1:x2]
            
            return self.model(frame, visual_prompts=[visual_prompt])
        
        elif self.config.detection.visual_prompt_path:
            # Use single visual prompt image
            visual_prompt = cv2.imread(self.config.detection.visual_prompt_path)
            if visual_prompt is None:
                self.logger.error(f"Could not load visual prompt: {self.config.detection.visual_prompt_path}")
                return []
            
            return self.model(frame, visual_prompts=[visual_prompt])
        
        else:
            self.logger.error("Visual mode selected but no visual prompts configured")
            return []
    
    def _detect_with_fixed_bboxes(self, frame: np.ndarray) -> List[DetectionResult]:
        """Detect using fixed bounding boxes (naive approach)"""
        if not self.config.detection.visual_prompts:
            # Fallback: if a single bbox is specified via visual_prompt_bbox, use it
            if self.config.detection.visual_prompt_bbox:
                self.logger.warning("visual_prompts list missing; falling back to visual_prompt_bbox for bbox mode")
                self.config.detection.visual_prompts = [self.config.detection.visual_prompt_bbox]
            else:
                self.logger.error("Bbox mode selected but no visual_prompts configured (and no visual_prompt_bbox fallback)")
                return []
        
        detections = []
        timestamp = datetime.now().isoformat()
        
        # Get frame dimensions
        h, w = frame.shape[:2]
        
        self.logger.debug(f"Processing {len(self.config.detection.visual_prompts)} fixed bbox regions (frame {w}x{h})")
        # Process each bounding box
        for i, bbox in enumerate(self.config.detection.visual_prompts):
            # Convert normalized coordinates to pixel coordinates
            x1, y1, x2, y2 = [int(coord * dim) for coord, dim in zip(bbox, [w, h, w, h])]
            self.logger.debug(f"Raw bbox {i} (normalized) {bbox} -> pixels ({x1},{y1},{x2},{y2}) before clamp")
            
            # Ensure coordinates are within frame bounds
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if (x1, y1, x2, y2) != tuple([int(coord * dim) for coord, dim in zip(bbox, [w, h, w, h])]):
                self.logger.debug(f"Clamped bbox {i} to within frame -> ({x1},{y1},{x2},{y2})")
            
            # Skip invalid boxes
            if x2 <= x1 or y2 <= y1:
                self.logger.warning(f"Invalid bbox {i}: {bbox} -> pixels ({x1},{y1},{x2},{y2})")
                continue
            
            # Extract region of interest
            roi = frame[y1:y2, x1:x2]
            self.logger.debug(f"ROI {i} shape: {roi.shape}")
            
            # Simple analysis of the ROI
            detection_result = self._analyze_roi(roi, [x1, y1, x2, y2], f"region_{i}")
            if not detection_result and getattr(self.config.detection, 'bbox_force_detection', False):
                # Fabricate a baseline detection so downstream activation logic runs
                detection_result = DetectionResult(
                    timestamp="",
                    confidence=1.0,  # Full confidence for forced bbox presence
                    bbox=[x1, y1, x2, y2],
                    class_name="region",
                    laser_status="normal",
                    zone_name=f"region_{i}"
                )
                self.logger.debug(f"ROI {i} forced detection emitted (bbox_force_detection=True)")

            if detection_result:
                detection_result.timestamp = timestamp
                detections.append(detection_result)
            else:
                self.logger.debug(f"ROI {i} produced no detection (below confidence threshold {self.config.detection.confidence_threshold})")
        
        return detections
    
    def _analyze_roi(self, roi: np.ndarray, bbox: List[int], region_name: str) -> Optional[DetectionResult]:
        """Analyze a region of interest using simple image processing"""
        try:
            # Convert to different color spaces for analysis
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            
            # Calculate basic statistics
            mean_brightness = float(np.mean(gray))
            std_brightness = float(np.std(gray))
            
            # Analyze color distribution
            mean_hue = float(np.mean(hsv[:, :, 0]))
            mean_saturation = float(np.mean(hsv[:, :, 1]))
            mean_value = float(np.mean(hsv[:, :, 2]))
            
            # Simple heuristics for detection
            confidence = 0.0
            class_name = "unknown"
            laser_status = "normal"
            decision_path = "none"
            
            # Brightness threshold mode (alternative to color-based detection)
            if getattr(self.config.detection, 'use_brightness_threshold', False):
                # Divide ROI into thirds like color-based detection
                h, w = gray.shape
                third = max(1, h // 3)
                top_region = gray[0:third, :]
                mid_region = gray[third:2*third, :]
                bottom_region = gray[2*third:, :]
                
                # Calculate brightness for each region
                top_brightness = float(np.mean(top_region)) if top_region.size > 0 else mean_brightness
                mid_brightness = float(np.mean(mid_region)) if mid_region.size > 0 else mean_brightness
                bottom_brightness = float(np.mean(bottom_region)) if bottom_region.size > 0 else mean_brightness
                
                # Calculate thresholds for top and middle regions based on bottom third
                top_threshold = bottom_brightness * self.config.detection.brightness_threshold_ratio
                mid_threshold = bottom_brightness * self.config.detection.brightness_threshold_ratio
                
                # Count bright pixels in each region
                top_bright_pixels = np.sum(top_region > top_threshold) if top_region.size > 0 else 0
                mid_bright_pixels = np.sum(mid_region > mid_threshold) if mid_region.size > 0 else 0
                
                top_bright_ratio = top_bright_pixels / top_region.size if top_region.size > 0 else 0.0
                mid_bright_ratio = mid_bright_pixels / mid_region.size if mid_region.size > 0 else 0.0
                
                # Determine activation status for each region
                top_active = top_bright_ratio >= self.config.detection.brightness_active_ratio  # Working indicator
                mid_active = mid_bright_ratio >= self.config.detection.brightness_active_ratio  # Machine on indicator
                
                decision_parts = []
                if top_active:
                    decision_parts.append(f"working({top_bright_ratio:.3f})")  # top = working
                if mid_active:
                    decision_parts.append(f"machine_on({mid_bright_ratio:.3f})")  # middle = machine on
                if not decision_parts:
                    decision_parts.append("machine_off")
                
                # Calculate brightness factor (higher brightness = more confident the light is on)
                brightness_factor = 0.7 + 0.6 * min(1.0, mean_brightness / 200.0)
                
                # Determine composite class & derive confidence (same logic as color-based)
                if top_active and mid_active:
                    class_name = "machine_active"  # Both on: machine is on AND working
                    # Confidence based on how far above threshold both ratios are
                    top_excess = max(0, top_bright_ratio - self.config.detection.brightness_active_ratio)
                    mid_excess = max(0, mid_bright_ratio - self.config.detection.brightness_active_ratio)
                    top_conf = 0.5 + min(0.5, top_excess / (2 * self.config.detection.brightness_active_ratio))
                    mid_conf = 0.5 + min(0.5, mid_excess / (2 * self.config.detection.brightness_active_ratio))
                    base_confidence = (top_conf + mid_conf) / 2.0
                    confidence = min(1.0, base_confidence * brightness_factor)
                    laser_status = "active"  # Machine is actively working
                elif top_active:
                    class_name = "machine_working_only"  # Top only: working but machine may not be fully on
                    top_excess = max(0, top_bright_ratio - self.config.detection.brightness_active_ratio)
                    base_confidence = 0.5 + min(0.5, top_excess / (2 * self.config.detection.brightness_active_ratio))
                    confidence = min(1.0, base_confidence * brightness_factor)
                    laser_status = "inactive"  # Not fully active without middle (machine on)
                elif mid_active:
                    class_name = "machine_on_only"  # Middle only: machine is on but not working
                    mid_excess = max(0, mid_bright_ratio - self.config.detection.brightness_active_ratio)
                    base_confidence = 0.5 + min(0.5, mid_excess / (2 * self.config.detection.brightness_active_ratio))
                    confidence = min(1.0, base_confidence * brightness_factor)
                    laser_status = "inactive"  # Not active - machine on but not working
                else:
                    class_name = "machine_off"  # Both off: machine is completely off
                    # Confidence based on how far below threshold we are
                    top_deficit = max(0, self.config.detection.brightness_active_ratio - top_bright_ratio)
                    mid_deficit = max(0, self.config.detection.brightness_active_ratio - mid_bright_ratio)
                    # Lower confidence when we're far below threshold
                    top_conf = max(0.1, 0.5 - top_deficit / self.config.detection.brightness_active_ratio)
                    mid_conf = max(0.1, 0.5 - mid_deficit / self.config.detection.brightness_active_ratio)
                    base_confidence = min(top_conf, mid_conf)  # Use the lower confidence
                    # For inactive states, lower brightness should increase confidence (dark = more likely off)
                    inverse_brightness_factor = 2.0 - brightness_factor  # 1.3 becomes 0.7, 0.7 becomes 1.3
                    confidence = min(1.0, max(0.1, base_confidence * inverse_brightness_factor))
                    laser_status = "inactive"
                
                decision_path = "+".join(decision_parts)
                
                extras = {
                    "mean_brightness": mean_brightness,
                    "std_brightness": std_brightness,
                    "brightness_factor": brightness_factor,
                    "top_brightness": top_brightness,
                    "mid_brightness": mid_brightness,
                    "bottom_brightness": bottom_brightness,
                    "top_threshold": top_threshold,
                    "mid_threshold": mid_threshold,
                    "top_bright_ratio": top_bright_ratio,
                    "mid_bright_ratio": mid_bright_ratio,
                    "decision_path": decision_path,
                    "mean_hue": mean_hue,
                    "mean_saturation": mean_saturation,
                    "mean_value": mean_value
                }
                
            # Specialized indicator composite mode
            elif getattr(self.config.detection, 'indicator_mode', False):
                # Optional denoise
                if self.config.detection.indicator_blur_ksize > 1:
                    try:
                        roi_proc = cv2.medianBlur(roi, self.config.detection.indicator_blur_ksize)
                        hsv_proc = cv2.cvtColor(roi_proc, cv2.COLOR_BGR2HSV)
                    except Exception:
                        hsv_proc = hsv
                else:
                    hsv_proc = hsv

                h_proc, w_proc = hsv_proc.shape[:2]
                third = max(1, h_proc // 3)
                top_region = hsv_proc[0:third, :, :]
                mid_region = hsv_proc[third:2*third, :, :]

                sat_min = self.config.detection.indicator_min_saturation
                val_min = self.config.detection.indicator_min_value

                # Masks for red (two ranges) and orange (mid segment)
                top_h = top_region[:, :, 0]
                top_s = top_region[:, :, 1]
                top_v = top_region[:, :, 2]
                mid_h = mid_region[:, :, 0]
                mid_s = mid_region[:, :, 1]
                mid_v = mid_region[:, :, 2]

                # Configurable hue bounds
                red_low_max = getattr(self.config.detection, 'red_hue_low_max', 10)
                red_high_min = getattr(self.config.detection, 'red_hue_high_min', 170)
                orange_min = getattr(self.config.detection, 'orange_hue_min', 8)
                orange_max = getattr(self.config.detection, 'orange_hue_max', 30)

                red_mask = ((top_h <= red_low_max) | (top_h >= red_high_min)) & (top_s >= sat_min) & (top_v >= val_min)
                orange_mask = (mid_h >= orange_min) & (mid_h <= orange_max) & (mid_s >= sat_min) & (mid_v >= val_min)

                red_ratio = red_mask.sum() / red_mask.size if red_mask.size else 0.0
                orange_ratio = orange_mask.sum() / orange_mask.size if orange_mask.size else 0.0

                # Backward compatibility: if legacy green_activation_ratio set, prefer it else use orange_activation_ratio
                orange_activation_threshold = None
                if getattr(self.config.detection, 'orange_activation_ratio', None) is not None:
                    orange_activation_threshold = self.config.detection.orange_activation_ratio
                elif getattr(self.config.detection, 'green_activation_ratio', None) is not None:
                    orange_activation_threshold = self.config.detection.green_activation_ratio
                else:
                    orange_activation_threshold = 0.02

                red_active = red_ratio >= self.config.detection.red_activation_ratio
                orange_active = orange_ratio >= orange_activation_threshold

                decision_parts = []
                if red_active:
                    decision_parts.append(f"working({red_ratio:.3f})")  # red = working
                if orange_active:
                    decision_parts.append(f"machine_on({orange_ratio:.3f})")  # orange = machine on
                if not decision_parts:
                    decision_parts.append("machine_off")

                # Calculate brightness factor (higher brightness = more confident the light is on)
                # Scale brightness from 0-255 to a multiplier between 0.7-1.3
                brightness_factor = 0.7 + 0.6 * min(1.0, mean_brightness / 200.0)
                
                # Determine composite class & derive confidence from activation ratio(s)
                # New logic: red=working, orange=on, both=active, both_off_or_red_off=inactive
                if red_active and orange_active:
                    class_name = "machine_active"  # Both on: machine is on AND working
                    # Confidence based on how far above threshold both ratios are
                    # Scale: at threshold = 0.5, at 3x threshold = 1.0
                    red_excess = max(0, red_ratio - self.config.detection.red_activation_ratio)
                    orange_excess = max(0, orange_ratio - orange_activation_threshold)
                    red_conf = 0.5 + min(0.5, red_excess / (2 * self.config.detection.red_activation_ratio))
                    orange_conf = 0.5 + min(0.5, orange_excess / (2 * orange_activation_threshold))
                    base_confidence = (red_conf + orange_conf) / 2.0
                    confidence = min(1.0, base_confidence * brightness_factor)
                    laser_status = "active"  # Machine is actively working
                elif red_active:
                    class_name = "machine_working_only"  # Red only: working but machine may not be fully on
                    red_excess = max(0, red_ratio - self.config.detection.red_activation_ratio)
                    base_confidence = 0.5 + min(0.5, red_excess / (2 * self.config.detection.red_activation_ratio))
                    confidence = min(1.0, base_confidence * brightness_factor)
                    laser_status = "inactive"  # Not fully active without orange (machine on)
                elif orange_active:
                    class_name = "machine_on_only"  # Orange only: machine is on but not working
                    orange_excess = max(0, orange_ratio - orange_activation_threshold)
                    base_confidence = 0.5 + min(0.5, orange_excess / (2 * orange_activation_threshold))
                    confidence = min(1.0, base_confidence * brightness_factor)
                    laser_status = "inactive"  # Not active - machine on but not working
                else:
                    class_name = "machine_off"  # Both off: machine is completely off
                    # Confidence based on how far below threshold we are
                    red_deficit = max(0, self.config.detection.red_activation_ratio - red_ratio)
                    orange_deficit = max(0, orange_activation_threshold - orange_ratio)
                    # Lower confidence when we're far below threshold
                    red_conf = max(0.1, 0.5 - red_deficit / self.config.detection.red_activation_ratio)
                    orange_conf = max(0.1, 0.5 - orange_deficit / orange_activation_threshold)
                    base_confidence = min(red_conf, orange_conf)  # Use the lower confidence
                    # For inactive states, lower brightness should increase confidence (dark = more likely off)
                    inverse_brightness_factor = 2.0 - brightness_factor  # 1.3 becomes 0.7, 0.7 becomes 1.3
                    confidence = min(1.0, max(0.1, base_confidence * inverse_brightness_factor))
                    laser_status = "inactive"

                decision_path = "+".join(decision_parts)
                # Attach extras for downstream analysis (keep legacy key green_ratio for compatibility if present)
                extras = {
                    "mean_brightness": mean_brightness,
                    "std_brightness": std_brightness,
                    "brightness_factor": brightness_factor,
                    "mean_hue": mean_hue,
                    "mean_saturation": mean_saturation,
                    "mean_value": mean_value,
                    "red_ratio": red_ratio,
                    "orange_ratio": orange_ratio,
                    "decision_path": decision_path
                }
                # Legacy duplicate for downstream tools expecting green_ratio
                extras["green_ratio"] = orange_ratio
            else:
                # Original heuristic paths (non-indicator composite mode)
                if (mean_hue < 10 or mean_hue > 170) and mean_saturation > 100:
                    confidence = min(0.9, mean_saturation / 255.0 + 0.3)
                    class_name = "red_light"
                    laser_status = "warning" if confidence > 0.6 else "normal"
                    decision_path = "red_light"
                elif 15 < mean_hue < 35 and mean_saturation > 100:
                    # Approximate orange hue band replacing prior green logic
                    confidence = min(0.9, mean_saturation / 255.0 + 0.3)
                    class_name = "orange_light"
                    laser_status = "normal"
                    decision_path = "orange_light"
                elif mean_brightness > 200:
                    confidence = min(0.8, mean_brightness / 255.0)
                    class_name = "bright_light"
                    laser_status = "normal"
                    decision_path = "bright_light"
                elif mean_brightness < 50 and std_brightness < 20:
                    confidence = 0.7
                    class_name = "off"
                    laser_status = "normal"
                    decision_path = "off"

                extras = {
                    "mean_brightness": mean_brightness,
                    "std_brightness": std_brightness,
                    "mean_hue": mean_hue,
                    "mean_saturation": mean_saturation,
                    "mean_value": mean_value,
                    "decision_path": decision_path
                }

            debug_msg = (
                f"ROI analysis {region_name} metrics: brightness(mean={mean_brightness:.2f}, std={std_brightness:.2f}), "
                f"HSV(mean_hue={mean_hue:.2f}, mean_sat={mean_saturation:.2f}, mean_val={mean_value:.2f}) -> "
                f"decision={decision_path}, class={class_name}, confidence={confidence:.3f} "
                f"(threshold {self.config.detection.confidence_threshold})"
            )
            if 'red_ratio' in extras and 'orange_ratio' in extras:
                debug_msg += f", red_ratio={extras['red_ratio']:.3f}, orange_ratio={extras['orange_ratio']:.3f}"
            self.logger.debug(debug_msg)
            
            # In bbox mode, always emit a detection for the provided ROI so we
            # can classify the machine state directly from the region without
            # applying a confidence gate. For AI modes, keep thresholding.
            if self.config.detection.mode == "bbox":
                return DetectionResult(
                    timestamp="",
                    confidence=confidence,
                    bbox=bbox,
                    class_name=class_name,
                    laser_status=laser_status,
                    zone_name=region_name,
                    extras=extras
                )

            # For non-bbox (AI) modes, honor the confidence threshold
            if confidence >= self.config.detection.confidence_threshold:
                return DetectionResult(
                    timestamp="",  # Will be set by caller
                    confidence=confidence,
                    bbox=bbox,
                    class_name=class_name,
                    laser_status=laser_status,
                    zone_name=region_name,
                    extras=extras
                )

            return None
            
        except Exception as e:
            self.logger.error(f"Error analyzing ROI: {e}")
            return None
    
    def _determine_laser_status(self, class_name: str, confidence: float) -> str:
        """Determine laser status based on detection"""
        # Simple logic - can be extended
        if confidence >= self.config.alerts.error_threshold:
            return "error"
        elif confidence >= self.config.alerts.warning_threshold:
            return "warning"
        else:
            return "normal"
    
    def _check_zones(self, bbox: List[float]) -> Optional[str]:
        """Check if detection is within any monitoring zone"""
        x1, y1, x2, y2 = bbox
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        
        for zone in self.config.monitoring.enabled_zones:
            if zone.enabled:
                zx1, zy1, zx2, zy2 = zone.bbox
                if zx1 <= center_x <= zx2 and zy1 <= center_y <= zy2:
                    return zone.name
        
        return None
    
    def draw_detection_overlays(self, frame: np.ndarray, detections: List[DetectionResult]) -> np.ndarray:
        """Draw detection overlays on frame and return annotated frame"""
        annotated_frame = frame.copy()
        
        # Draw detections on frame
        for detection in detections:
            x1, y1, x2, y2 = [int(coord) for coord in detection.bbox]
            
            # Choose color based on laser status
            if detection.laser_status == "active":
                color = (0, 255, 0)  # Green for active
            elif detection.laser_status == "inactive":
                color = (0, 165, 255)  # Orange for inactive
            else:
                color = (128, 128, 128)  # Gray for other
            
            # Draw bounding box
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
            
            # Draw main label
            label = f"{detection.class_name}: {detection.confidence:.3f}"
            cv2.putText(annotated_frame, label, (x1, y1 - 10), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            
            # Draw detection-specific scores based on detection mode
            if hasattr(detection, 'extras') and detection.extras:
                # Check if using brightness threshold mode
                if getattr(self.config.detection, 'use_brightness_threshold', False):
                    # Brightness threshold mode - show per-region brightness values
                    top_brightness = detection.extras.get('top_brightness', 0)
                    mid_brightness = detection.extras.get('mid_brightness', 0)
                    top_bright_ratio = detection.extras.get('top_bright_ratio', 0)
                    mid_bright_ratio = detection.extras.get('mid_bright_ratio', 0)
                    
                    # Top region brightness (working indicator)
                    top_text = f"Top: {top_brightness:.1f} ({top_bright_ratio:.3f})"
                    cv2.putText(annotated_frame, top_text, (x1, y1 - 30), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
                    
                    # Middle region brightness (machine on indicator)
                    mid_text = f"Mid: {mid_brightness:.1f} ({mid_bright_ratio:.3f})"
                    cv2.putText(annotated_frame, mid_text, (x1, y1 - 45), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
                    
                else:
                    # Color-based mode - show red/orange ratios
                    red_ratio = detection.extras.get('red_ratio', 0)
                    orange_ratio = detection.extras.get('orange_ratio', 0)
                    brightness = detection.extras.get('mean_brightness', 0)
                    brightness_factor = detection.extras.get('brightness_factor', 1.0)
                    
                    # Red score
                    red_text = f"Red: {red_ratio:.3f}"
                    cv2.putText(annotated_frame, red_text, (x1, y1 - 30), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
                    
                    # Orange score
                    orange_text = f"Org: {orange_ratio:.3f}"
                    cv2.putText(annotated_frame, orange_text, (x1, y1 - 45), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 165, 255), 1)
                    
                    # Brightness info
                    bright_text = f"Br: {brightness:.0f} ({brightness_factor:.2f}x)"
                    cv2.putText(annotated_frame, bright_text, (x1, y1 - 60), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        
        # Add status information in bottom left corner
        height, width = annotated_frame.shape[:2]
        status_y_start = height - 80
        
        # Current timestamp
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(annotated_frame, f"Time: {current_time}", (10, status_y_start), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # Detection count and overall status
        active_count = sum(1 for d in detections if d.laser_status == "active")
        inactive_count = sum(1 for d in detections if d.laser_status == "inactive")
        total_count = len(detections)
        
        cv2.putText(annotated_frame, f"Detections: {total_count} (Active: {active_count}, Inactive: {inactive_count})", 
                   (10, status_y_start + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # Overall machine status
        if active_count > 0:
            overall_status = "MACHINE ACTIVE"
            status_color = (0, 255, 0)  # Green
        elif total_count > 0:
            overall_status = "MACHINE INACTIVE"
            status_color = (0, 165, 255)  # Orange
        else:
            overall_status = "NO DETECTIONS"
            status_color = (128, 128, 128)  # Gray
        
        cv2.putText(annotated_frame, f"Status: {overall_status}", (10, status_y_start + 40), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, 2)
        
        # Thresholds info - show different info based on detection mode
        if getattr(self.config.detection, 'use_brightness_threshold', False):
            # Brightness threshold mode - show per-region threshold info
            # Get brightness values from first detection if available
            if detections and hasattr(detections[0], 'extras') and detections[0].extras:
                bottom_brightness = detections[0].extras.get('bottom_brightness', 0)
                top_threshold = detections[0].extras.get('top_threshold', 0)
                mid_threshold = detections[0].extras.get('mid_threshold', 0)
                threshold_text = f"Bottom: {bottom_brightness:.1f} | Thresholds: T={top_threshold:.1f} M={mid_threshold:.1f} | Active: {self.config.detection.brightness_active_ratio:.2f}"
            else:
                threshold_text = f"Brightness mode | Ratio: {self.config.detection.brightness_threshold_ratio:.1f}x | Active: {self.config.detection.brightness_active_ratio:.2f}"
            cv2.putText(annotated_frame, threshold_text, 
                       (10, status_y_start + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
        else:
            # Color-based mode - show red/orange thresholds
            cv2.putText(annotated_frame, f"Thresholds: R={self.config.detection.red_activation_ratio:.2f} O={self.config.detection.orange_activation_ratio:.2f}", 
                       (10, status_y_start + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
        
        return annotated_frame
    
    def save_frame(self, frame: np.ndarray, detections: List[DetectionResult]) -> tuple[str, Optional[str]]:
        """Save frame with detection annotations"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"detection_{timestamp}.jpg"
        filepath = self.screenshots_dir / filename
        
        # Use helper method to draw overlays
        annotated_frame = self.draw_detection_overlays(frame, detections)
        
        # Save annotated frame
        cv2.imwrite(str(filepath), annotated_frame)
        self.logger.info(f"Annotated frame saved: {filepath}")
        
        # Upload image if enabled
        image_url = None
        if self.image_uploader:
            try:
                image_url = self.image_uploader.upload_image(str(filepath))
                if image_url:
                    self.logger.info(f"Image uploaded: {image_url}")
                else:
                    self.logger.warning("Failed to upload image")
            except Exception as e:
                self.logger.error(f"Error uploading image: {e}")
        
        return str(filepath), image_url
    
    def save_detections(self, detections: List[DetectionResult]) -> str:
        """Save detection results to JSON"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"detections_{timestamp}.json"
        filepath = self.detections_dir / filename
        
        # Convert detections to dict format
        detection_data = {
            "timestamp": datetime.now().isoformat(),
            "detection_count": len(detections),
            "detections": [d.to_dict() for d in detections],
            "config": {
                "model_path": self.config.model_path,
                "detection_mode": self.config.detection.mode,
                "confidence_threshold": self.config.detection.confidence_threshold,
                "camera_info": self.camera_manager.get_camera_info()
            }
        }
        
        # Save to JSON
        with open(filepath, 'w') as f:
            json.dump(detection_data, f, indent=2)
        
        self.logger.info(f"Detection results saved: {filepath}")
        return str(filepath)
    
    def cleanup_old_files(self):
        """Clean up old detection images and logs to keep only the most recent ones"""
        if not self.config.output.enable_auto_cleanup:
            return
            
        try:
            self.cleanup_detection_images()
            self.cleanup_detection_logs()
            self.cleanup_machine_history()
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
    
    def cleanup_detection_images(self):
        """Remove old detection images, keeping only the most recent max_detection_images"""
        if not self.screenshots_dir.exists():
            return
            
        # Get all detection image files sorted by modification time (newest first)
        image_files = []
        for pattern in ['detection_*.jpg', 'detection_*.png', 'detection_*.jpeg']:
            image_files.extend(self.screenshots_dir.glob(pattern))
        
        if not image_files:
            return
            
        # Sort by modification time (newest first)
        image_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        
        # Keep only the most recent max_detection_images
        max_images = self.config.output.max_detection_images
        files_to_delete = image_files[max_images:]
        
        if files_to_delete:
            self.logger.info(f"Cleaning up {len(files_to_delete)} old detection images (keeping {max_images} most recent)")
            for file_path in files_to_delete:
                try:
                    file_path.unlink()
                    self.logger.debug(f"Deleted old detection image: {file_path.name}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete {file_path.name}: {e}")
    
    def cleanup_detection_logs(self):
        """Remove old detection log files, keeping only the most recent max_detection_logs"""
        if not self.detections_dir.exists():
            return
            
        # Get all detection JSON files sorted by modification time (newest first)
        log_files = list(self.detections_dir.glob('detections_*.json'))
        
        if not log_files:
            return
            
        # Sort by modification time (newest first)
        log_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        
        # Keep only the most recent max_detection_logs
        max_logs = self.config.output.max_detection_logs
        files_to_delete = log_files[max_logs:]
        
        if files_to_delete:
            self.logger.info(f"Cleaning up {len(files_to_delete)} old detection logs (keeping {max_logs} most recent)")
            for file_path in files_to_delete:
                try:
                    file_path.unlink()
                    self.logger.debug(f"Deleted old detection log: {file_path.name}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete {file_path.name}: {e}")
    
    def cleanup_machine_history(self):
        """Remove machine history entries older than 7 days"""
        try:
            total_entries_before = sum(len(h.entries) for h in self.machine_histories.values())
            entries_removed = 0
            
            for machine_id, history in self.machine_histories.items():
                entries_before = len(history.entries)
                history.cleanup_old_entries()
                entries_after = len(history.entries)
                entries_removed += entries_before - entries_after
            
            if entries_removed > 0:
                self.logger.info(f"Cleaned up {entries_removed} old machine history entries (keeping last 7 days)")
                # Save the cleaned history
                self.save_machine_history()
            
        except Exception as e:
            self.logger.error(f"Failed to cleanup machine history: {e}")
    
    def load_machine_history(self):
        """Load machine history from file"""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    seven_days_ago = datetime.now() - timedelta(days=7)
                    
                    for machine_id, machine_data in data.items():
                        history = MachineHistory(machine_id=machine_id)
                        if machine_data.get('last_active_time'):
                            history.last_active_time = datetime.fromisoformat(machine_data['last_active_time'])
                        if machine_data.get('last_inactive_time'):
                            history.last_inactive_time = datetime.fromisoformat(machine_data['last_inactive_time'])
                        
                        # Only load entries from the last 7 days
                        for entry_data in machine_data.get('entries', []):
                            entry_timestamp = datetime.fromisoformat(entry_data['timestamp'])
                            if entry_timestamp >= seven_days_ago:
                                entry = MachineStatusEntry(
                                    timestamp=entry_timestamp,
                                    status=entry_data['status'],
                                    class_name=entry_data['class_name'],
                                    confidence=entry_data['confidence'],
                                    details=entry_data.get('details', {})
                                )
                                history.entries.append(entry)
                        
                        self.machine_histories[machine_id] = history
                        
                total_entries = sum(len(h.entries) for h in self.machine_histories.values())
                self.logger.info(f"Loaded history for {len(self.machine_histories)} machines ({total_entries} entries from last 7 days)")
            except Exception as e:
                self.logger.warning(f"Failed to load machine history: {e}")
    
    def save_machine_history(self):
        """Save machine history to file"""
        try:
            data = {machine_id: history.to_dict() for machine_id, history in self.machine_histories.items()}
            with open(self.history_file, 'w') as f:
                json.dump(data, f, indent=2)
            self.logger.debug(f"Machine history saved to {self.history_file}")
        except Exception as e:
            self.logger.error(f"Failed to save machine history: {e}")
    
    def update_machine_status(self, detections: List[DetectionResult]):
        """Update machine status history based on detections"""
        # For now, treat each detection as a separate machine
        # In the future, this could be enhanced to group detections by zone or other criteria
        
        if not detections:
            # No detections - update machine_0 as inactive
            machine_id = "machine_0"
            if machine_id not in self.machine_histories:
                self.machine_histories[machine_id] = MachineHistory(machine_id=machine_id)
            
            self.machine_histories[machine_id].add_entry(
                status="inactive",
                class_name="machine_off",
                confidence=0.0,
                details={"reason": "no_detections"}
            )
            
            # Update alert managers with status change
            history = self.machine_histories.get(machine_id)
            self.email_alert_manager.update_machine_status(machine_id, "inactive", history)
            self.sms_alert_manager.update_machine_status(machine_id, "inactive", history)
        else:
            # Process each detection
            for i, detection in enumerate(detections):
                machine_id = f"machine_{i}"
                
                if machine_id not in self.machine_histories:
                    self.machine_histories[machine_id] = MachineHistory(machine_id=machine_id)
                
                # Determine status based on laser_status
                status = "active" if detection.laser_status == "active" else "inactive"
                
                self.machine_histories[machine_id].add_entry(
                    status=status,
                    class_name=detection.class_name,
                    confidence=detection.confidence,
                    details={
                        "bbox": detection.bbox,
                        "zone": detection.zone_name,
                        "extras": detection.extras
                    }
                )
                
                # Update alert managers with status change
                history = self.machine_histories[machine_id]
                self.email_alert_manager.update_machine_status(machine_id, status, history)
                self.sms_alert_manager.update_machine_status(machine_id, status, history)
                
                self.logger.info(f"Updated {machine_id}: {status} ({detection.class_name}, conf={detection.confidence:.3f})")
    
    def check_inactive_alerts(self):
        """Check for machines that have been inactive too long and send email/SMS alerts"""
        alerts = []
        for machine_id, history in self.machine_histories.items():
            if history.is_inactive_too_long(threshold_minutes=self.inactive_alert_threshold):
                duration = history.get_inactive_duration()
                duration_minutes = duration.total_seconds() / 60
                
                alert_info = {
                    "machine_id": machine_id,
                    "inactive_duration": duration_minutes,
                    "last_active": history.last_active_time.isoformat() if history.last_active_time else None
                }
                alerts.append(alert_info)
                
                self.logger.warning(f"ALERT: {machine_id} inactive for {duration_minutes:.1f} minutes")
                
                # Send email alert if configured and machine is in alert list
                if self.config.alerts.email_alerts and machine_id in self.config.alerts.alert_machines:
                    email_sent = self.email_alert_manager.send_inactive_alert(
                        machine_id=machine_id,
                        inactive_duration_minutes=duration_minutes,
                        last_active_time=history.last_active_time
                    )
                    if email_sent:
                        self.logger.info(f"Email alert sent for {machine_id}")
                    else:
                        self.logger.warning(f"Failed to send email alert for {machine_id}")
                
                # Send SMS alert if configured and machine is in alert list
                if self.config.alerts.sms_alerts and machine_id in self.config.alerts.alert_machines:
                    sms_sent = self.sms_alert_manager.send_inactive_alert(
                        machine_id=machine_id,
                        inactive_duration_minutes=duration_minutes,
                        last_active_time=history.last_active_time
                    )
                    if sms_sent:
                        self.logger.info(f"SMS alert sent for {machine_id}")
                    else:
                        self.logger.warning(f"Failed to send SMS alert for {machine_id}")
        
        return alerts
    
    def run_single_cycle(self) -> bool:
        """Run a single detection cycle"""
        try:
            # Capture frame
            frame = self.capture_frame()
            if frame is None:
                return False
            
            # Perform detection
            detections = self.detect_objects(frame)
            
            # Update machine status history
            self.update_machine_status(detections)
            
            # Save results
            if self.config.output.save_screenshots:
                frame_path, image_url = self.save_frame(frame, detections)
                self.logger.info(f"Frame saved: {frame_path}")
                if image_url:
                    self.logger.info(f"Image URL: {image_url}")
            
            if self.config.output.save_detections:
                detection_path = self.save_detections(detections)
                self.logger.info(f"Detections saved: {detection_path}")
            
            # Clean up old files
            self.cleanup_old_files()
            
            # Save machine history
            self.save_machine_history()
            
            # Check for inactive alerts
            alerts = self.check_inactive_alerts()
            if alerts:
                self.logger.warning(f"Found {len(alerts)} inactive machine alerts")
            
            # Log summary
            self.logger.info(f"Detection cycle complete: {len(detections)} objects found")
            for detection in detections:
                self.logger.info(f"  {detection.class_name}: {detection.confidence:.3f} ({detection.laser_status})")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Detection cycle failed: {e}")
            return False
    
    def run(self, continuous: bool = False) -> bool:
        """Run laser monitor in single-shot or continuous mode
        
        Args:
            continuous: If True, run continuous monitoring with 2-minute intervals
                       If False, run single detection cycle (default)
        """
        try:
            mode = "continuous monitoring" if continuous else "single-shot"
            self.logger.info(f"Starting laser monitor ({mode} mode)")
            
            # Load model
            if not self.load_model():
                return False
            
            # Open camera
            if not self.open_camera():
                return False
            
            if continuous:
                return self._run_continuous_monitoring()
            else:
                return self._run_single_shot()
                
        except KeyboardInterrupt:
            self.logger.info("Monitor stopped by user")
            return True
        except Exception as e:
            self.logger.error(f"Monitor run failed: {e}")
            return False
        finally:
            # Clean up
            self.camera_manager.close_camera()
            self.logger.info("Monitor session ended")
    
    def _run_single_shot(self) -> bool:
        """Run single detection cycle (legacy behavior)"""
        success = self.run_single_cycle()
        if success:
            # For single-shot mode, also update machine history
            self.save_machine_history()
        return success
    
    def _run_continuous_monitoring(self) -> bool:
        """Run continuous monitoring with 2-minute intervals"""
        self.monitoring_active = True
        self.logger.info(f"Starting continuous monitoring (interval: {self.monitoring_interval}s)")
        
        cycle_count = 0
        try:
            while self.monitoring_active:
                cycle_count += 1
                start_time = time.time()
                
                self.logger.info(f"=== Monitoring Cycle {cycle_count} ===")
                
                # Run detection cycle
                success = self.run_single_cycle()
                if not success:
                    self.logger.error("Detection cycle failed, continuing...")
                
                # Calculate sleep time to maintain 2-minute intervals
                elapsed = time.time() - start_time
                sleep_time = max(0, self.monitoring_interval - elapsed)
                
                if sleep_time > 0:
                    self.logger.info(f"Cycle completed in {elapsed:.1f}s, sleeping for {sleep_time:.1f}s")
                    time.sleep(sleep_time)
                else:
                    self.logger.warning(f"Cycle took {elapsed:.1f}s (longer than {self.monitoring_interval}s interval)")
                    
        except KeyboardInterrupt:
            self.logger.info("Continuous monitoring stopped by user")
        
        self.monitoring_active = False
        self.logger.info(f"Continuous monitoring ended after {cycle_count} cycles")
        return True
    
    def stop_monitoring(self):
        """Stop continuous monitoring"""
        self.monitoring_active = False
    
    def test_email_alert(self) -> bool:
        """Send a test email alert immediately for testing purposes"""
        try:
            self.logger.info("🧪 Testing email alert system...")
            
            # Check if email alerts are enabled
            if not self.config.alerts.email_alerts:
                self.logger.error("❌ Email alerts are disabled in configuration")
                print("❌ Email alerts are disabled in configuration")
                print("   Set alerts.email_alerts = True in your config")
                return False
            
            # Check if machine_0 is in alert list
            if 'machine_0' not in self.config.alerts.alert_machines:
                self.logger.warning("⚠️  machine_0 is not in alert_machines list")
                print("⚠️  machine_0 is not in alert_machines list")
                print("   This test will still send an email, but real alerts won't be sent")
            
            # Create a test timestamp (15 minutes ago)
            test_last_active = datetime.now() - timedelta(minutes=15)
            test_duration = 15.5  # 15.5 minutes inactive
            
            print(f"📧 Sending test email alert...")
            print(f"   Recipients: {', '.join(self.email_alert_manager.recipients) if getattr(self.email_alert_manager, 'recipients', None) else '(none)'}")
            print(f"   Test scenario: machine_0 inactive for {test_duration} minutes")
            print(f"   Last active: {test_last_active.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Temporarily bypass cooldown for testing
            original_cooldown = self.email_alert_manager.last_alert_times.get('machine_0')
            if 'machine_0' in self.email_alert_manager.last_alert_times:
                del self.email_alert_manager.last_alert_times['machine_0']
            
            # Send test email
            success = self.email_alert_manager.send_inactive_alert(
                machine_id='machine_0',
                inactive_duration_minutes=test_duration,
                last_active_time=test_last_active,
                is_test=True
            )
            
            # Restore original cooldown state
            if original_cooldown:
                self.email_alert_manager.last_alert_times['machine_0'] = original_cooldown
            
            if success:
                print("✅ Test email sent successfully!")
                print("   Check your inbox for the alert email")
                self.logger.info("✅ Test email alert sent successfully")
                return True
            else:
                print("❌ Failed to send test email")
                print("   Check your .env file and email configuration")
                print("   Run: python setup_email.py")
                self.logger.error("❌ Failed to send test email alert")
                return False
                
        except Exception as e:
            self.logger.error(f"Test email failed: {e}")
            print(f"❌ Test email failed: {e}")
            print("   Check your .env file and email configuration")
            return False
    
    def test_sms_alert(self) -> bool:
        """Send a test SMS alert immediately for testing purposes"""
        try:
            self.logger.info("🧪 Testing SMS alert system...")
            
            # Check if SMS alerts are enabled
            if not self.config.alerts.sms_alerts:
                self.logger.error("❌ SMS alerts are disabled in configuration")
                print("❌ SMS alerts are disabled in configuration")
                print("   Set alerts.sms_alerts = True in your config")
                return False
            
            # Check if machine_0 is in alert list
            if 'machine_0' not in self.config.alerts.alert_machines:
                self.logger.warning("⚠️  machine_0 is not in alert_machines list")
                print("⚠️  machine_0 is not in alert_machines list")
                print("   This test will still send an SMS, but real alerts won't be sent")
            
            # Create a test timestamp (15 minutes ago)
            test_last_active = datetime.now() - timedelta(minutes=15)
            test_duration = 15.5  # 15.5 minutes inactive
            
            print(f"📱 Sending test SMS alert...")
            print(f"   Recipients: {', '.join(self.sms_alert_manager.recipients) if getattr(self.sms_alert_manager, 'recipients', None) else '(none)'}")
            print(f"   Test scenario: machine_0 inactive for {test_duration} minutes")
            print(f"   Last active: {test_last_active.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Temporarily bypass cooldown for testing
            original_cooldown = self.sms_alert_manager.last_alert_times.get('machine_0')
            if 'machine_0' in self.sms_alert_manager.last_alert_times:
                del self.sms_alert_manager.last_alert_times['machine_0']
            
            # Send test SMS
            success = self.sms_alert_manager.send_inactive_alert(
                machine_id='machine_0',
                inactive_duration_minutes=test_duration,
                last_active_time=test_last_active,
                is_test=True
            )
            
            # Restore original cooldown state
            if original_cooldown:
                self.sms_alert_manager.last_alert_times['machine_0'] = original_cooldown
            
            if success:
                print("✅ Test SMS sent successfully!")
                print("   Check your phone for the alert message")
                self.logger.info("✅ Test SMS alert sent successfully")
                return True
            else:
                print("❌ Failed to send test SMS")
                print("   Check your .env file and Twilio configuration")
                print("   Ensure TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER are set")
                self.logger.error("❌ Failed to send test SMS alert")
                return False
                
        except Exception as e:
            self.logger.error(f"Test SMS failed: {e}")
            print(f"❌ Test SMS failed: {e}")
            print("   Check your .env file and Twilio configuration")
            return False
    
    def test_active_email_alert(self) -> bool:
        """Send a test active email alert immediately for testing purposes"""
        try:
            self.logger.info("🧪 Testing active email alert system...")
            
            # Check if email alerts are enabled
            if not self.config.alerts.email_alerts:
                self.logger.error("❌ Email alerts are disabled in configuration")
                print("❌ Email alerts are disabled in configuration")
                print("   Set alerts.email_alerts = True in your config")
                return False
            
            # Check if machine_0 is in alert list
            if 'machine_0' not in self.config.alerts.alert_machines:
                self.logger.warning("⚠️  machine_0 is not in alert_machines list")
                print("⚠️  machine_0 is not in alert_machines list")
                print("   This test will still send an email, but real alerts won't be sent")
            
            test_inactive_duration = 15.5  # 15.5 minutes that it was inactive
            
            print(f"📧 Sending test active email alert...")
            print(f"   Recipients: {', '.join(self.email_alert_manager.recipients) if getattr(self.email_alert_manager, 'recipients', None) else '(none)'}")
            print(f"   Test scenario: machine_0 became active after {test_inactive_duration} minutes inactive")
            
            # Send test active email
            success = self.email_alert_manager.send_active_alert(
                machine_id='machine_0',
                inactive_duration_minutes=test_inactive_duration,
                is_test=True
            )
            
            if success:
                print("✅ Test active email sent successfully!")
                print("   Check your email for the alert message")
                self.logger.info("✅ Test active email alert sent successfully")
                return True
            else:
                print("❌ Failed to send test active email")
                print("   Check your .env file and email configuration")
                self.logger.error("❌ Failed to send test active email alert")
                return False
                
        except Exception as e:
            self.logger.error(f"Test active email failed: {e}")
            print(f"❌ Test active email failed: {e}")
            print("   Check your .env file and email configuration")
            return False
    
    def test_active_sms_alert(self) -> bool:
        """Send a test active SMS alert immediately for testing purposes"""
        try:
            self.logger.info("🧪 Testing active SMS alert system...")
            
            # Check if SMS alerts are enabled
            if not self.config.alerts.sms_alerts:
                self.logger.error("❌ SMS alerts are disabled in configuration")
                print("❌ SMS alerts are disabled in configuration")
                print("   Set alerts.sms_alerts = True in your config")
                return False
            
            # Check if machine_0 is in alert list
            if 'machine_0' not in self.config.alerts.alert_machines:
                self.logger.warning("⚠️  machine_0 is not in alert_machines list")
                print("⚠️  machine_0 is not in alert_machines list")
                print("   This test will still send an SMS, but real alerts won't be sent")
            
            test_inactive_duration = 15.5  # 15.5 minutes that it was inactive
            
            print(f"📱 Sending test active SMS alert...")
            print(f"   Recipients: {', '.join(self.sms_alert_manager.recipients) if getattr(self.sms_alert_manager, 'recipients', None) else '(none)'}")
            print(f"   Test scenario: machine_0 became active after {test_inactive_duration} minutes inactive")
            
            # Send test active SMS
            success = self.sms_alert_manager.send_active_alert(
                machine_id='machine_0',
                inactive_duration_minutes=test_inactive_duration,
                is_test=True
            )
            
            if success:
                print("✅ Test active SMS sent successfully!")
                print("   Check your phone for the alert message")
                self.logger.info("✅ Test active SMS alert sent successfully")
                return True
            else:
                print("❌ Failed to send test active SMS")
                print("   Check your .env file and Twilio configuration")
                print("   Ensure TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER are set")
                self.logger.error("❌ Failed to send test active SMS alert")
                return False
                
        except Exception as e:
            self.logger.error(f"Test active SMS failed: {e}")
            print(f"❌ Test active SMS failed: {e}")
            print("   Check your .env file and Twilio configuration")
            return False


def main():
    """Main entry point for testing"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Laser Monitor - Single Shot Detection")
    parser.add_argument("--config", help="Configuration file (uses built-in defaults if not specified)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    # Load configuration
    from config.config import ConfigManager
    config_manager = ConfigManager(args.config)
    config = config_manager.load_config()
    
    if args.verbose:
        config.logging.log_level = "DEBUG"
    
    # Run monitor
    monitor = LaserMonitor(config)
    success = monitor.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
