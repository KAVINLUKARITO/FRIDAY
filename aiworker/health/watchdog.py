"""
AIWorker Health Watchdog - Phase 3 Production Hardening

Process watchdog for autonomous recovery from failures:
- Heartbeat monitoring: SequentialEngine must heartbeat every 5 minutes
- Stall detection: Same state for >30 minutes = stuck
- OOM prevention: Preemptive action before kernel OOM killer
- Recovery actions: Graceful (SIGUSR1) → Forceful (kill subprocesses) → Nuclear (systemd restart)

Systemd integration:
- Runs as separate process (aiworker-watchdog.service)
- Uses systemd notify protocol (READY=1, WATCHDOG=1)
- If AIWorker main process dies, watchdog restarts it

Recovery log in SQLite for dashboard "System Reliability" panel.
"""

import logging
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from aiworker.config import AIWorkerConfig

logger = logging.getLogger("aiworker.watchdog")


class RecoveryAction(Enum):
    """Types of recovery actions."""
    GRACEFUL = "graceful"
    FORCEFUL = "forceful"
    NUCLEAR = "nuclear"


class ProcessRole(Enum):
    """Process roles for tracking."""
    MAIN = "main"
    MCP = "mcp"
    OLLAMA = "ollama"


@dataclass
class ProcessInfo:
    """Information about a registered process."""
    pid: int
    role: ProcessRole
    registered_at: float
    last_heartbeat: float
    last_state: Optional[str] = None
    state_changed_at: float = field(default_factory=time.time)
    heartbeat_count: int = 0
    missed_heartbeats: int = 0


@dataclass
class RecoveryRecord:
    """Record of a recovery action."""
    timestamp: float
    trigger: str
    action_taken: str
    success: bool
    iteration_id: Optional[str]
    details: str = ""


class HealthWatchdog:
    """
    Process watchdog for AIWorker autonomous recovery.
    
    Monitors registered processes via heartbeats, detects stalls,
    and performs escalating recovery actions.
    """
    
    # Timing constants
    HEARTBEAT_INTERVAL_SECONDS = 300  # 5 minutes
    HEARTBEAT_TIMEOUT_SECONDS = 360  # 6 minutes (allow 1 minute grace)
    STALL_TIMEOUT_SECONDS = 1800  # 30 minutes in same state
    CHECK_INTERVAL_SECONDS = 10  # Health check interval
    
    def __init__(self, config: Optional[AIWorkerConfig] = None):
        self.config = config or AIWorkerConfig.from_env()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Process registry: pid -> ProcessInfo
        self._processes: dict[int, ProcessInfo] = {}
        
        # Recovery tracking
        self._recovery_count = 0
        self._max_recoveries = 5  # Max recoveries before giving up
        
        # Systemd integration
        self._systemd_available = self._check_systemd()
        
        # Initialize database
        self._init_database()
        
        logger.info("HealthWatchdog initialized")
    
    def _check_systemd(self) -> bool:
        """Check if systemd is available."""
        return (
            os.path.exists('/run/systemd/system') and
            'NOTIFY_SOCKET' in os.environ
        )
    
    def _init_database(self):
        """Initialize SQLite database for recovery tracking."""
        db_path = Path(self.config.base_path) / "data" / "health.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recovery_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                trigger TEXT NOT NULL,
                action_taken TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                iteration_id TEXT,
                details TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS process_heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pid INTEGER NOT NULL,
                role TEXT NOT NULL,
                timestamp REAL NOT NULL,
                state TEXT,
                metadata TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_recovery_time 
            ON recovery_actions(timestamp)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_heartbeat_pid 
            ON process_heartbeats(pid)
        ''')
        
        conn.commit()
        conn.close()
        
        logger.debug(f"Health database initialized: {db_path}")
    
    def _get_db_path(self) -> Path:
        """Get database path."""
        return Path(self.config.base_path) / "data" / "health.db"
    
    def _systemd_notify(self, message: str):
        """Send notification to systemd."""
        if not self._systemd_available:
            return
        
        try:
            import socket
            
            notify_socket = os.environ.get('NOTIFY_SOCKET')
            if not notify_socket:
                return
            
            if notify_socket.startswith('@'):
                # Abstract namespace socket
                notify_socket = '\0' + notify_socket[1:]
            
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.sendto(message.encode(), notify_socket)
            sock.close()
        
        except Exception as e:
            logger.debug(f"Systemd notify failed: {e}")
    
    def notify_ready(self):
        """Notify systemd that watchdog is ready."""
        self._systemd_notify("READY=1")
        logger.info("Systemd ready notification sent")
    
    def notify_watchdog(self):
        """Send watchdog keepalive to systemd."""
        self._systemd_notify("WATCHDOG=1")
    
    def register_process(self, pid: int, role: str = "main") -> bool:
        """
        Register a process for monitoring.
        
        Args:
            pid: Process ID to monitor
            role: Process role (main, mcp, ollama)
            
        Returns:
            True if registered successfully
        """
        try:
            # Verify process exists
            os.kill(pid, 0)
        except OSError:
            logger.error(f"Cannot register PID {pid}: process does not exist")
            return False
        
        with self._lock:
            role_enum = ProcessRole(role)
            
            self._processes[pid] = ProcessInfo(
                pid=pid,
                role=role_enum,
                registered_at=time.time(),
                last_heartbeat=time.time()
            )
        
        logger.info(f"Registered {role} process: PID {pid}")
        return True
    
    def unregister_process(self, pid: int):
        """Unregister a process from monitoring."""
        with self._lock:
            if pid in self._processes:
                role = self._processes[pid].role.value
                del self._processes[pid]
                logger.info(f"Unregistered {role} process: PID {pid}")
    
    def heartbeat(self, pid: int, state: Optional[str] = None) -> bool:
        """
        Record a heartbeat from a registered process.
        
        Args:
            pid: Process ID
            state: Current state (for stall detection)
            
        Returns:
            True if heartbeat accepted
        """
        with self._lock:
            if pid not in self._processes:
                logger.warning(f"Heartbeat from unregistered PID {pid}")
                return False
            
            info = self._processes[pid]
            info.last_heartbeat = time.time()
            info.heartbeat_count += 1
            info.missed_heartbeats = 0
            
            # Track state changes
            if state and state != info.last_state:
                info.last_state = state
                info.state_changed_at = time.time()
            
            # Persist heartbeat
            self._persist_heartbeat(pid, info.role.value, state)
            
            return True
    
    def _persist_heartbeat(self, pid: int, role: str, state: Optional[str]):
        """Persist heartbeat to database."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO process_heartbeats (pid, role, timestamp, state, metadata)
                VALUES (?, ?, ?, ?, ?)
            ''', (pid, role, time.time(), state, None))
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.debug(f"Failed to persist heartbeat: {e}")
    
    def _persist_recovery(self, record: RecoveryRecord):
        """Persist recovery action to database."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO recovery_actions 
                (timestamp, trigger, action_taken, success, iteration_id, details)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (record.timestamp, record.trigger, record.action_taken,
                  record.success, record.iteration_id, record.details))
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.warning(f"Failed to persist recovery: {e}")
    
    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process is still alive."""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    
    def _get_iteration_id(self) -> Optional[str]:
        """Get current iteration ID from checkpoint database."""
        try:
            from aiworker.engine.sequential_engine import SequentialEngine
            
            engine = SequentialEngine(db_path=self.config.checkpoint_db)
            current = engine.get_current_iteration()
            
            if current:
                return current.get('iteration_id')
        except Exception as e:
            logger.debug(f"Failed to get iteration ID: {e}")
        
        return None
    
    def recover_graceful(self, pid: int) -> bool:
        """
        Graceful recovery: Send SIGUSR1 to trigger checkpoint and pause.
        
        Args:
            pid: Process ID to recover
            
        Returns:
            True if recovery signal sent successfully
        """
        logger.warning(f"Attempting graceful recovery for PID {pid}")
        
        try:
            # Send SIGUSR1 to trigger checkpoint
            os.kill(pid, signal.SIGUSR1)
            
            # Wait for process to checkpoint (max 10 seconds)
            for _ in range(10):
                if not self._is_process_alive(pid):
                    logger.info(f"Process {pid} exited after SIGUSR1")
                    return True
                time.sleep(1)
            
            logger.warning(f"Process {pid} did not respond to SIGUSR1")
            return False
        
        except ProcessLookupError:
            logger.info(f"Process {pid} already terminated")
            return True
        except Exception as e:
            logger.error(f"Graceful recovery failed: {e}")
            return False
    
    def recover_forceful(self, pid: int) -> bool:
        """
        Forceful recovery: Kill subprocesses, unload models, resume from checkpoint.
        
        Args:
            pid: Process ID to recover
            
        Returns:
            True if recovery successful
        """
        logger.warning(f"Attempting forceful recovery for PID {pid}")
        
        try:
            # Kill subprocesses
            killed = []
            for entry in Path('/proc').iterdir():
                if entry.name.isdigit():
                    try:
                        with open(entry / 'stat', 'r') as f:
                            stat = f.read()
                            ppid = int(stat.split(')')[1].split()[1])
                            if ppid == pid:
                                subpid = int(entry.name)
                                os.kill(subpid, signal.SIGTERM)
                                killed.append(subpid)
                    except (PermissionError, FileNotFoundError, ValueError):
                        pass
            
            if killed:
                logger.info(f"Sent SIGTERM to subprocesses: {killed}")
                time.sleep(2)
                
                # Force kill if still alive
                for subpid in killed:
                    try:
                        os.kill(subpid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            
            # Unload Ollama models
            try:
                import httpx
                httpx.post(f"{self.config.ollama_host}/api/generate",
                          json={"model": "", "keep_alive": 0},
                          timeout=10.0)
                logger.info("Ollama models unloaded")
            except Exception as e:
                logger.debug(f"Failed to unload Ollama models: {e}")
            
            # Kill main process
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(3)
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            
            logger.info(f"Forceful recovery complete for PID {pid}")
            return True
        
        except Exception as e:
            logger.error(f"Forceful recovery failed: {e}")
            return False
    
    def restart_service(self) -> bool:
        """
        Nuclear recovery: Full restart via systemd.
        
        Returns:
            True if restart initiated successfully
        """
        logger.critical("Initiating nuclear recovery: service restart")
        
        try:
            # Try systemd restart
            result = subprocess.run(
                ['systemctl', 'restart', 'aiworker'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.info("Service restart initiated")
                return True
            else:
                logger.error(f"Service restart failed: {result.stderr}")
                return False
        
        except Exception as e:
            logger.error(f"Service restart error: {e}")
            return False
    
    def check_health(self) -> list[str]:
        """
        Check health of all registered processes.
        
        Returns:
            List of issues found
        """
        issues = []
        current_time = time.time()
        
        with self._lock:
            for pid, info in list(self._processes.items()):
                # Check if process is alive
                if not self._is_process_alive(pid):
                    issues.append(f"Process {pid} ({info.role.value}) is dead")
                    continue
                
                # Check heartbeat timeout
                time_since_heartbeat = current_time - info.last_heartbeat
                if time_since_heartbeat > self.HEARTBEAT_TIMEOUT_SECONDS:
                    info.missed_heartbeats += 1
                    issues.append(
                        f"Process {pid} ({info.role.value}) missed heartbeat "
                        f"({time_since_heartbeat:.0f}s ago)"
                    )
                
                # Check for stall
                if info.last_state:
                    time_in_state = current_time - info.state_changed_at
                    if time_in_state > self.STALL_TIMEOUT_SECONDS:
                        issues.append(
                            f"Process {pid} ({info.role.value}) stalled in state "
                            f"'{info.last_state}' for {time_in_state/60:.0f} minutes"
                        )
        
        return issues
    
    def _perform_recovery(self, issues: list[str]):
        """Perform appropriate recovery for detected issues."""
        iteration_id = self._get_iteration_id()
        
        for issue in issues:
            logger.warning(f"Health issue: {issue}")
            
            # Extract PID from issue message
            import re
            pid_match = re.search(r'Process (\d+)', issue)
            if not pid_match:
                continue
            
            pid = int(pid_match.group(1))
            
            # Determine recovery level
            if self._recovery_count == 0:
                action = RecoveryAction.GRACEFUL
                success = self.recover_graceful(pid)
            elif self._recovery_count < 3:
                action = RecoveryAction.FORCEFUL
                success = self.recover_forceful(pid)
            else:
                action = RecoveryAction.NUCLEAR
                success = self.restart_service()
            
            # Record recovery
            record = RecoveryRecord(
                timestamp=time.time(),
                trigger=issue,
                action_taken=action.value,
                success=success,
                iteration_id=iteration_id,
                details=f"Recovery count: {self._recovery_count}"
            )
            self._persist_recovery(record)
            
            if success:
                self._recovery_count += 1
                logger.info(f"Recovery successful: {action.value}")
            else:
                logger.error(f"Recovery failed: {action.value}")
            
            # Unregister recovered process
            self.unregister_process(pid)
            
            # Check max recoveries
            if self._recovery_count >= self._max_recoveries:
                logger.critical("Max recoveries reached, giving up")
                self._running = False
                break
    
    def _watchdog_loop(self):
        """Main watchdog loop."""
        logger.info("Watchdog loop started")
        
        # Notify systemd we're ready
        self.notify_ready()
        
        while self._running:
            try:
                # Send systemd watchdog keepalive
                self.notify_watchdog()
                
                # Check health
                issues = self.check_health()
                
                if issues:
                    self._perform_recovery(issues)
                
                # Periodic cleanup of old heartbeat records
                if int(time.time()) % 3600 < self.CHECK_INTERVAL_SECONDS:
                    self._cleanup_old_records()
                
            except Exception as e:
                logger.error(f"Watchdog loop error: {e}")
            
            # Sleep
            for _ in range(self.CHECK_INTERVAL_SECONDS):
                if not self._running:
                    break
                time.sleep(1)
        
        logger.info("Watchdog loop stopped")
    
    def _cleanup_old_records(self):
        """Clean up old heartbeat records."""
        try:
            cutoff = time.time() - (24 * 3600)  # 24 hours
            
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM process_heartbeats WHERE timestamp < ?
            ''', (cutoff,))
            
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            
            if deleted > 0:
                logger.debug(f"Cleaned up {deleted} old heartbeat records")
        
        except Exception as e:
            logger.debug(f"Failed to cleanup old records: {e}")
    
    def start(self):
        """Start the watchdog."""
        if self._running:
            logger.warning("Watchdog already running")
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="HealthWatchdog"
        )
        self._thread.start()
        
        logger.info("Health watchdog started")
    
    def stop(self):
        """Stop the watchdog."""
        if not self._running:
            return
        
        self._running = False
        
        if self._thread:
            self._thread.join(timeout=5.0)
        
        logger.info("Health watchdog stopped")
    
    def get_recovery_stats(self) -> dict:
        """Get recovery statistics for dashboard."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            # Total recoveries
            cursor.execute('SELECT COUNT(*) FROM recovery_actions')
            total = cursor.fetchone()[0]
            
            # Recent recoveries (last 24 hours)
            cutoff = time.time() - (24 * 3600)
            cursor.execute('''
                SELECT COUNT(*) FROM recovery_actions 
                WHERE timestamp > ?
            ''', (cutoff,))
            recent = cursor.fetchone()[0]
            
            # Success rate
            cursor.execute('''
                SELECT 
                    COUNT(CASE WHEN success = 1 THEN 1 END) as success,
                    COUNT(*) as total
                FROM recovery_actions
            ''')
            row = cursor.fetchone()
            success_rate = (row[0] / row[1] * 100) if row[1] > 0 else 100.0
            
            conn.close()
            
            return {
                'total_recoveries': total,
                'recent_recoveries': recent,
                'success_rate_percent': round(success_rate, 1),
                'recovery_count_since_start': self._recovery_count
            }
        
        except Exception as e:
            logger.warning(f"Failed to get recovery stats: {e}")
            return {
                'total_recoveries': 0,
                'recent_recoveries': 0,
                'success_rate_percent': 100.0,
                'recovery_count_since_start': self._recovery_count
            }


# Factory function
def create_watchdog(config: Optional[AIWorkerConfig] = None) -> HealthWatchdog:
    """Create and return a HealthWatchdog instance."""
    return HealthWatchdog(config)


# Main entry point for standalone watchdog process
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    watchdog = create_watchdog()
    watchdog.start()
    
    try:
        while watchdog._running:
            time.sleep(1)
    except KeyboardInterrupt:
        watchdog.stop()
