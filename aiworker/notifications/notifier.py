"""
AIWorker Notification System - Phase 3 Production Hardening

Multi-channel alerting for critical events:
- Console: Rich-formatted to stdout (always)
- Log: Structured JSON to file
- Email: SMTP for critical alerts (optional)
- Webhook: HTTP POST to external service (optional)
- Dashboard: In-app notification queue

Event types:
- CRITICAL: Kill switch tripped, OOM imminent, data corruption
- WARNING: High memory, stalled iteration, test failure
- INFO: Patch applied, goal completed, backup completed
- DEBUG: State transitions, model loads, cache hits

Rate limiting: Same event type max 1 per 5 minutes, digest mode for warnings.
"""

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx

from aiworker.config import AIWorkerConfig

logger = logging.getLogger("aiworker.notifications")


class EventSeverity(Enum):
    """Event severity levels."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"


class NotificationChannel(Enum):
    """Available notification channels."""
    CONSOLE = "console"
    LOG = "log"
    EMAIL = "email"
    WEBHOOK = "webhook"
    DASHBOARD = "dashboard"


@dataclass
class NotificationEvent:
    """A notification event."""
    timestamp: float
    severity: EventSeverity
    event_type: str
    message: str
    iteration_id: Optional[str]
    context: dict = field(default_factory=dict)
    
    @property
    def datetime(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp)


class NotificationManager:
    """
    Multi-channel notification system for AIWorker.
    
    Routes events to configured channels with rate limiting
    and digest mode for non-critical alerts.
    """
    
    # Rate limiting: max 1 per 5 minutes per event type
    RATE_LIMIT_SECONDS = 300
    
    # Quiet hours: no non-critical alerts 00:00-06:00
    QUIET_HOURS_START = 0
    QUIET_HOURS_END = 6
    
    def __init__(self, config: Optional[AIWorkerConfig] = None):
        self.config = config or AIWorkerConfig.from_env()
        self.base_path = Path(self.config.base_path)
        
        # Channel configuration
        self.channels = self._load_channel_config()
        
        # Rate limiting state
        self._last_notification: dict[str, float] = {}
        
        # Digest buffer for warnings
        self._digest_buffer: list[NotificationEvent] = []
        self._last_digest_time = time.time()
        
        # Initialize database
        self._init_database()
        
        logger.info("NotificationManager initialized")
    
    def _load_channel_config(self) -> dict[NotificationChannel, dict]:
        """Load channel configuration from config."""
        # Default: console and log always enabled
        channels = {
            NotificationChannel.CONSOLE: {'enabled': True},
            NotificationChannel.LOG: {'enabled': True},
            NotificationChannel.DASHBOARD: {'enabled': True},
        }
        
        # Email configuration
        email_config = getattr(self.config, 'email', {})
        if email_config.get('enabled'):
            channels[NotificationChannel.EMAIL] = {
                'enabled': True,
                'smtp_host': email_config.get('smtp_host', 'localhost'),
                'smtp_port': email_config.get('smtp_port', 587),
                'username': email_config.get('username'),
                'password': email_config.get('password'),
                'from_addr': email_config.get('from', 'aiworker@localhost'),
                'to_addrs': email_config.get('to', []),
                'use_tls': email_config.get('use_tls', True),
            }
        
        # Webhook configuration
        webhook_url = getattr(self.config, 'webhook_url', None)
        if webhook_url:
            channels[NotificationChannel.WEBHOOK] = {
                'enabled': True,
                'url': webhook_url,
                'headers': getattr(self.config, 'webhook_headers', {}),
            }
        
        return channels
    
    def _init_database(self):
        """Initialize SQLite database for notifications."""
        db_path = self.base_path / "data" / "notifications.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                severity TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                iteration_id TEXT,
                context TEXT,
                channels_delivered TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_notifications_time 
            ON notifications(timestamp)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_notifications_severity 
            ON notifications(severity)
        ''')
        
        conn.commit()
        conn.close()
        
        logger.debug(f"Notifications database initialized: {db_path}")
    
    def _get_db_path(self) -> Path:
        """Get database path."""
        return self.base_path / "data" / "notifications.db"
    
    def _is_quiet_hours(self) -> bool:
        """Check if currently in quiet hours."""
        current_hour = datetime.now().hour
        return self.QUIET_HOURS_START <= current_hour < self.QUIET_HOURS_END
    
    def _should_rate_limit(self, event: NotificationEvent) -> bool:
        """Check if event should be rate limited."""
        # Never rate limit critical events
        if event.severity == EventSeverity.CRITICAL:
            return False
        
        key = f"{event.severity.value}:{event.event_type}"
        last_time = self._last_notification.get(key, 0)
        
        if time.time() - last_time < self.RATE_LIMIT_SECONDS:
            return True
        
        self._last_notification[key] = time.time()
        return False
    
    def _send_console(self, event: NotificationEvent):
        """Send notification to console (Rich-formatted)."""
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.text import Text
            
            console = Console()
            
            # Color by severity
            colors = {
                EventSeverity.CRITICAL: 'red',
                EventSeverity.WARNING: 'yellow',
                EventSeverity.INFO: 'blue',
                EventSeverity.DEBUG: 'dim'
            }
            
            color = colors.get(event.severity, 'white')
            
            # Build message
            text = Text()
            text.append(f"[{event.severity.value.upper()}] ", style=f"bold {color}")
            text.append(event.message)
            
            if event.iteration_id:
                text.append(f"\nIteration: {event.iteration_id}", style="dim")
            
            panel = Panel(
                text,
                title=f"AIWorker Alert",
                border_style=color
            )
            
            console.print(panel)
        
        except Exception as e:
            # Fallback to plain print
            print(f"[{event.severity.value.upper()}] {event.message}")
    
    def _send_log(self, event: NotificationEvent):
        """Send notification to structured log."""
        log_entry = {
            'timestamp': event.timestamp,
            'severity': event.severity.value,
            'event_type': event.event_type,
            'message': event.message,
            'iteration_id': event.iteration_id,
            'context': event.context
        }
        
        # Write to JSON log file
        log_path = self.base_path / "logs" / "notifications.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(log_path, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        # Also log to Python logger
        log_method = getattr(logger, event.severity.value, logger.info)
        log_method(f"{event.event_type}: {event.message}")
    
    def _send_email(self, event: NotificationEvent, config: dict):
        """Send notification via email."""
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            # Only send critical and some warnings via email
            if event.severity not in [EventSeverity.CRITICAL, EventSeverity.WARNING]:
                return
            
            msg = MIMEMultipart()
            msg['From'] = config['from_addr']
            msg['To'] = ', '.join(config['to_addrs'])
            msg['Subject'] = f"[AIWorker] {event.severity.value.upper()}: {event.event_type}"
            
            body = f"""
AIWorker Alert

Severity: {event.severity.value.upper()}
Event Type: {event.event_type}
Time: {event.datetime.isoformat()}
Iteration: {event.iteration_id or 'N/A'}

Message:
{event.message}

Context:
{json.dumps(event.context, indent=2)}
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Connect and send
            server = smtplib.SMTP(config['smtp_host'], config['smtp_port'])
            
            if config['use_tls']:
                server.starttls()
            
            if config.get('username') and config.get('password'):
                server.login(config['username'], config['password'])
            
            server.send_message(msg)
            server.quit()
            
            logger.debug(f"Email sent to {config['to_addrs']}")
        
        except Exception as e:
            logger.warning(f"Failed to send email: {e}")
    
    def _send_webhook(self, event: NotificationEvent, config: dict):
        """Send notification via webhook."""
        try:
            payload = {
                'timestamp': event.timestamp,
                'severity': event.severity.value,
                'event_type': event.event_type,
                'message': event.message,
                'iteration_id': event.iteration_id,
                'context': event.context,
                'action_url': f"/api/iterations/{event.iteration_id}" if event.iteration_id else None
            }
            
            response = httpx.post(
                config['url'],
                json=payload,
                headers=config.get('headers', {}),
                timeout=30.0
            )
            
            if response.status_code >= 400:
                logger.warning(f"Webhook returned {response.status_code}")
        
        except Exception as e:
            logger.warning(f"Failed to send webhook: {e}")
    
    def _send_dashboard(self, event: NotificationEvent):
        """Store notification for dashboard display."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO notifications 
                (timestamp, severity, event_type, message, iteration_id, context, channels_delivered)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                event.timestamp,
                event.severity.value,
                event.event_type,
                event.message,
                event.iteration_id,
                json.dumps(event.context),
                'dashboard'
            ))
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.debug(f"Failed to store dashboard notification: {e}")
    
    def _persist_notification(self, event: NotificationEvent, channels: list[str]):
        """Persist notification to database."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO notifications 
                (timestamp, severity, event_type, message, iteration_id, context, channels_delivered)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                event.timestamp,
                event.severity.value,
                event.event_type,
                event.message,
                event.iteration_id,
                json.dumps(event.context),
                ','.join(channels)
            ))
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.debug(f"Failed to persist notification: {e}")
    
    def send(
        self,
        severity: EventSeverity,
        event_type: str,
        message: str,
        iteration_id: Optional[str] = None,
        context: Optional[dict] = None,
        force: bool = False
    ) -> bool:
        """
        Send a notification through configured channels.
        
        Args:
            severity: Event severity level
            event_type: Type of event
            message: Notification message
            iteration_id: Optional iteration ID
            context: Optional additional context
            force: Bypass rate limiting
            
        Returns:
            True if notification was sent
        """
        event = NotificationEvent(
            timestamp=time.time(),
            severity=severity,
            event_type=event_type,
            message=message,
            iteration_id=iteration_id,
            context=context or {}
        )
        
        # Check quiet hours for non-critical
        if self._is_quiet_hours() and severity not in [EventSeverity.CRITICAL]:
            # Buffer for digest
            if severity == EventSeverity.WARNING:
                self._digest_buffer.append(event)
            return False
        
        # Check rate limiting
        if not force and self._should_rate_limit(event):
            logger.debug(f"Rate limited: {event_type}")
            return False
        
        # Send to enabled channels
        delivered_channels = []
        
        for channel, config in self.channels.items():
            if not config.get('enabled', False):
                continue
            
            try:
                if channel == NotificationChannel.CONSOLE:
                    self._send_console(event)
                    delivered_channels.append('console')
                
                elif channel == NotificationChannel.LOG:
                    self._send_log(event)
                    delivered_channels.append('log')
                
                elif channel == NotificationChannel.EMAIL:
                    self._send_email(event, config)
                    delivered_channels.append('email')
                
                elif channel == NotificationChannel.WEBHOOK:
                    self._send_webhook(event, config)
                    delivered_channels.append('webhook')
                
                elif channel == NotificationChannel.DASHBOARD:
                    self._send_dashboard(event)
                    delivered_channels.append('dashboard')
            
            except Exception as e:
                logger.warning(f"Failed to send to {channel.value}: {e}")
        
        # Persist notification
        self._persist_notification(event, delivered_channels)
        
        return len(delivered_channels) > 0
    
    def send_digest(self):
        """Send digest of buffered warnings."""
        if not self._digest_buffer:
            return
        
        # Group by event type
        by_type = {}
        for event in self._digest_buffer:
            by_type.setdefault(event.event_type, []).append(event)
        
        # Build digest message
        message = "Warning Digest:\n"
        for event_type, events in by_type.items():
            message += f"  - {event_type}: {len(events)} occurrences\n"
        
        # Send as single notification
        self.send(
            severity=EventSeverity.WARNING,
            event_type="digest",
            message=message,
            force=True
        )
        
        # Clear buffer
        self._digest_buffer = []
        self._last_digest_time = time.time()
    
    def get_recent(
        self,
        severity: Optional[EventSeverity] = None,
        limit: int = 20
    ) -> list[NotificationEvent]:
        """Get recent notifications for dashboard."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            if severity:
                cursor.execute('''
                    SELECT * FROM notifications 
                    WHERE severity = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (severity.value, limit))
            else:
                cursor.execute('''
                    SELECT * FROM notifications 
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            
            events = []
            for row in rows:
                events.append(NotificationEvent(
                    timestamp=row['timestamp'],
                    severity=EventSeverity(row['severity']),
                    event_type=row['event_type'],
                    message=row['message'],
                    iteration_id=row['iteration_id'],
                    context=json.loads(row['context']) if row['context'] else {}
                ))
            
            return events
        
        except Exception as e:
            logger.warning(f"Failed to get recent notifications: {e}")
            return []


# Convenience functions
def notify_critical(
    message: str,
    event_type: str = "critical",
    iteration_id: Optional[str] = None,
    context: Optional[dict] = None
):
    """Send critical notification."""
    notifier = NotificationManager()
    return notifier.send(
        severity=EventSeverity.CRITICAL,
        event_type=event_type,
        message=message,
        iteration_id=iteration_id,
        context=context
    )


def notify_warning(
    message: str,
    event_type: str = "warning",
    iteration_id: Optional[str] = None,
    context: Optional[dict] = None
):
    """Send warning notification."""
    notifier = NotificationManager()
    return notifier.send(
        severity=EventSeverity.WARNING,
        event_type=event_type,
        message=message,
        iteration_id=iteration_id,
        context=context
    )


def notify_info(
    message: str,
    event_type: str = "info",
    iteration_id: Optional[str] = None,
    context: Optional[dict] = None
):
    """Send info notification."""
    notifier = NotificationManager()
    return notifier.send(
        severity=EventSeverity.INFO,
        event_type=event_type,
        message=message,
        iteration_id=iteration_id,
        context=context
    )


# Factory function
def create_notification_manager(config: Optional[AIWorkerConfig] = None) -> NotificationManager:
    """Create and return a NotificationManager instance."""
    return NotificationManager(config)
